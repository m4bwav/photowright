#!/usr/bin/env python3
"""photowright CLI: edit raster images from the command line, as replayable recipe steps.

Rung 1 is Pillow + NumPy (plus a stdlib 16-bit PNG codec, because Pillow reduces
16-bit RGB PNG to 8 bits). OpenCV, SciPy and scikit-image are rung 2 optional
backends, probed at run time; PHW_RUNG_MAX=1 (or --rung-max 1) hides them.
Every command reports which rung and tool it used.

Commands here: doctor, explain, inspect, convert, adjust, crop, resize, rotate,
sharpen, denoise, run. masks.py adds select, mask, cutout; compose.py adds layers;
layered.py adds open and save.
Rules followed (references/image-fundamentals.md): linear light for resize, blur
and exposure (R6); curves, levels and LUTs on encoded values (R8); straight alpha,
premultiplied for neighbour filters (R13); EXIF orientation applied on load (R17,
R18); ICC kept unless stripped or converted on purpose (R1-R3); float32 inside,
quantised at save (R10). Outputs never overwrite a file; sources are only read.
"""
import argparse
import difflib
import hashlib
import importlib
import importlib.util
import io
import json
import math
import os
import shutil
import struct
import sys
import time
import zipfile
import zlib
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image, ImageOps, features

try:
    from PIL import ImageCms
except Exception:  # pragma: no cover - Pillow built without LittleCMS
    ImageCms = None

VERSION = "0.11.0"
ROOT = Path(__file__).resolve().parent.parent.parent

# Hooks filled by the other modules of the package (masks, compose, layered).
EXTRA_COMMANDS = []   # callables(sub) adding subparsers
RUN_KINDS = {}        # recipe "kind" -> fn(a, recipe_path, recipe_dict)
DOCTOR_GROUPS = []    # callables() -> {group: (rung, tool)}


# ---------------------------------------------------------------- rungs
def rung_max():
    try:
        return int(os.environ.get("PHW_RUNG_MAX", "9"))
    except ValueError:
        return 9


_PROBED = {}


def probe(name):
    """Return a rung 2 module, or None when absent or hidden by PHW_RUNG_MAX."""
    if rung_max() < 2:
        return None
    if name not in _PROBED:
        try:
            _PROBED[name] = importlib.import_module(name)
        except Exception:
            _PROBED[name] = None
    return _PROBED[name]


class Used:
    """Collects which rung and tool each op used."""

    def __init__(self):
        self.items = []

    def add(self, op, rung, tool):
        self.items.append({"op": op, "rung": rung, "tool": tool})

    def rung(self):
        return max([i["rung"] for i in self.items] or [1])

    def tool(self):
        return sorted({i["tool"] for i in self.items})


# ---------------------------------------------------------------- colour
def to_lin(v):
    v = np.asarray(v, np.float32)
    return np.where(v <= 0.04045, v / 12.92, ((np.clip(v, 0, None) + 0.055) / 1.055) ** 2.4).astype(np.float32)


def to_enc(v):
    v = np.clip(np.asarray(v, np.float32), 0, None)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1 / 2.4) - 0.055).astype(np.float32)


def icc_name(icc):
    if not icc or ImageCms is None:
        return None
    try:
        return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
    except Exception:
        return "unreadable profile"


def srgb_icc():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


# ---------------------------------------------------------------- image object
class Img:
    """px: float32 HxWxC in 0..1, encoded, straight alpha as last channel when alpha."""

    def __init__(self, px, alpha, icc=None, exif=None, xmp=None, bits=8, fmt=None, notes=None):
        self.px = np.ascontiguousarray(px, np.float32)
        self.alpha = alpha
        self.icc, self.exif, self.xmp = icc, exif, xmp
        self.bits, self.fmt = bits, fmt
        self.notes = notes if notes is not None else []

    def copy(self, px=None, alpha=None):
        return Img(self.px.copy() if px is None else px, self.alpha if alpha is None else alpha,
                   self.icc, self.exif, self.xmp, self.bits, self.fmt, self.notes)

    @property
    def nc(self):
        return self.px.shape[2] - (1 if self.alpha else 0)

    def color(self):
        return self.px[..., :self.nc]

    def with_color(self, c):
        px = np.concatenate([c, self.px[..., self.nc:]], axis=2) if self.alpha else c
        return self.copy(px=np.asarray(px, np.float32))


def orient_array(a, o):
    return {2: lambda x: x[:, ::-1], 3: lambda x: x[::-1, ::-1], 4: lambda x: x[::-1],
            5: lambda x: x.swapaxes(0, 1), 6: lambda x: np.rot90(x, -1),
            7: lambda x: np.rot90(x.swapaxes(0, 1), 2), 8: lambda x: np.rot90(x, 1)}.get(o, lambda x: x)(a)


# ---------------------------------------------------------------- stdlib PNG16 codec (rung 1)
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_CT = {0: 1, 4: 2, 2: 3, 6: 4}


def png_chunks(data):
    pos = 8
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        yield data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        pos += 12 + n


def png_bitdepth(path):
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != PNG_SIG:
        return None
    return head[24], head[25], head[28]  # bit depth, colour type, interlace


def read_png16(path):
    """Read a non-interlaced 16-bit PNG (grey, grey+alpha, RGB, RGBA) to uint16 HxWxC."""
    data = Path(path).read_bytes()
    idat, icc, exif = [], None, None
    for typ, body in png_chunks(data):
        if typ == b"IHDR":
            w, h, bd, ct, _, _, il = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat.append(body)
        elif typ == b"iCCP":
            icc = zlib.decompress(body[body.index(b"\0") + 2:])
        elif typ == b"eXIf":
            exif = body
    if bd != 16 or ct not in PNG_CT or il:
        raise ValueError("own PNG16 reader handles non-interlaced 16-bit grey/RGB(A) only")
    c = PNG_CT[ct]
    bpp, stride = 2 * c, 2 * c * w
    raw = np.frombuffer(zlib.decompress(b"".join(idat)), np.uint8).reshape(h, stride + 1)
    out = np.zeros((h, stride), np.uint8)
    prev = np.zeros(stride, np.int32)
    for y in range(h):
        ft, row = raw[y, 0], raw[y, 1:].astype(np.int32)
        if ft == 0:
            cur = row
        elif ft == 1:
            cur = (np.cumsum(row.reshape(w, bpp), axis=0) % 256).reshape(-1)
        elif ft == 2:
            cur = (row + prev) % 256
        else:  # Avg and Paeth depend on the reconstructed left byte: per pixel
            cur = np.zeros(stride, np.int32)
            for x in range(0, stride, bpp):
                a = cur[x - bpp:x] if x else np.zeros(bpp, np.int32)
                b, cc = prev[x:x + bpp], (prev[x - bpp:x] if x else np.zeros(bpp, np.int32))
                if ft == 3:
                    pred = (a + b) // 2
                else:
                    p = a + b - cc
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - cc)
                    pred = np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, cc))
                cur[x:x + bpp] = (row[x:x + bpp] + pred) % 256
        out[y] = cur
        prev = cur
    arr = out.view(">u2").reshape(h, w, c).astype(np.uint16)
    return arr, icc, exif


def write_png16(path, arr16, icc=None, exif=None):
    h, w, c = arr16.shape
    ct = {1: 0, 2: 4, 3: 2, 4: 6}[c]

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)

    rows = arr16.astype(">u2").reshape(h, w * c).view(np.uint8)
    raw = np.concatenate([np.zeros((h, 1), np.uint8), rows], axis=1).tobytes()
    parts = [PNG_SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, ct, 0, 0, 0))]
    if icc:
        parts.append(chunk(b"iCCP", b"ICC profile\0\0" + zlib.compress(icc)))
    if exif:
        parts.append(chunk(b"eXIf", exif[6:] if exif.startswith(b"Exif\0\0") else exif))
    parts += [chunk(b"IDAT", zlib.compress(raw, 6)), chunk(b"IEND", b"")]
    with open(path, "xb") as f:
        f.write(b"".join(parts))


# ---------------------------------------------------------------- load / save
def _exif_bytes(ex):
    if ex is None or len(ex) == 0:
        return None
    return ex.tobytes()


def load(path, used=None):
    """Open, apply EXIF orientation, read ICC/EXIF/XMP, return Img (float32 straight alpha)."""
    path = Path(path)
    notes = []
    with Image.open(path) as im:  # read-only open
        fmt = im.format
        exif = im.getexif()
        orient = exif.get(274, 1)
        icc = im.info.get("icc_profile")
        xmp = im.info.get("xmp") or im.info.get("XML:com.adobe.xmp")
        pd = png_bitdepth(path) if fmt == "PNG" else None
        bits = 8
        if pd and pd[0] == 16 and pd[2] == 0 and pd[1] in PNG_CT:
            arr16, icc16, _ = read_png16(path)
            icc = icc or icc16
            px = orient_array(arr16.astype(np.float32) / 65535.0, orient)
            bits = 16
            if used:
                used.add("load", 1, "own PNG16 reader")
        else:
            cv2 = probe("cv2")
            tif16 = fmt == "TIFF" and im.mode in ("RGB", "RGBA") and im.tag_v2.get(258, (8,))[0] == 16
            if tif16 and cv2 is not None:
                a = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                a = a[..., ::-1] if a.shape[2] == 3 else a[..., [2, 1, 0, 3]]
                px = orient_array(a.astype(np.float32) / 65535.0, orient)
                bits = 16
                if used:
                    used.add("load", 2, "OpenCV imread (16-bit TIFF)")
            else:
                if tif16:
                    notes.append("16-bit RGB TIFF read as 8-bit: OpenCV absent (rung 1 fallback)")
                im2 = ImageOps.exif_transpose(im)
                mode = im2.mode
                if mode in ("I;16", "I;16B", "I;16L", "I"):
                    px = np.asarray(im2, np.float32)[..., None] / 65535.0
                    bits = 16
                elif mode == "F":
                    px = np.asarray(im2, np.float32)[..., None]
                    bits = 32
                else:
                    if mode == "P":
                        im2 = im2.convert("RGBA" if "transparency" in im2.info else "RGB")
                    elif mode not in ("L", "LA", "RGB", "RGBA"):
                        if mode == "CMYK":
                            notes.append("CMYK converted with Pillow's naive formula (R4): no CMYK profile used")
                        im2 = im2.convert("RGBA" if "A" in mode else "RGB")
                    px = np.asarray(im2, np.float32) / 255.0
                    if px.ndim == 2:
                        px = px[..., None]
                if used:
                    used.add("load", 1, "Pillow")
        if orient != 1:
            notes.append(f"EXIF orientation {orient} applied; saved as 1")
        if 274 in exif:
            del exif[274]
        alpha = px.shape[2] in (2, 4)
        if not icc:
            notes.append("no ICC profile: treated as sRGB (R2)")
        return Img(px, alpha, icc, _exif_bytes(exif), xmp, bits, fmt, notes)


SAVE_FMT = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".tif": "TIFF",
            ".tiff": "TIFF", ".bmp": "BMP", ".gif": "GIF", ".avif": "AVIF"}


def free_path(p):
    """Never write over an existing file: name.ext, name-001.ext, name-002.ext ..."""
    p = Path(p)
    if not p.exists():
        return p
    for n in range(1, 10000):
        q = p.with_name(f"{p.stem}-{n:03d}{p.suffix}")
        if not q.exists():
            return q
    raise RuntimeError("no free output name")


def out_for(src, out, tag, ext=None):
    src = Path(src)
    p = Path(out) if out else src.with_name(f"{src.stem}-{tag}{ext or src.suffix}")
    p = free_path(p)
    if p.resolve() == src.resolve():
        raise RuntimeError("refusing to write over the source")
    return p


def save(img, path, bits=None, used=None, quality=95):
    path = Path(path)
    fmt = SAVE_FMT.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(f"unknown output extension {path.suffix}")
    bits = bits or img.bits
    px = np.clip(img.px, 0, 1)
    c = px.shape[2]
    if bits >= 16:
        if fmt == "PNG":
            write_png16(path, np.round(px * 65535).astype(np.uint16), img.icc, img.exif)
            if used:
                used.add("save", 1, "own PNG16 writer")
            return path
        if fmt == "TIFF" and c == 1:
            Image.fromarray(np.round(px[..., 0] * 65535).astype(np.uint16), "I;16").save(
                path, icc_profile=img.icc) if img.icc else Image.fromarray(
                np.round(px[..., 0] * 65535).astype(np.uint16), "I;16").save(path)
            if used:
                used.add("save", 1, "Pillow I;16")
            return path
        cv2 = probe("cv2")
        if fmt == "TIFF" and cv2 is not None and c in (3, 4):
            a = np.round(px * 65535).astype(np.uint16)
            a = a[..., ::-1] if c == 3 else a[..., [2, 1, 0, 3]]
            if not cv2.imwrite(str(path), a):
                raise RuntimeError("OpenCV could not write the TIFF")
            img.notes.append("16-bit TIFF via OpenCV carries no ICC profile or EXIF")
            if used:
                used.add("save", 2, "OpenCV imwrite (16-bit TIFF)")
            return path
        img.notes.append(f"16-bit {fmt} not writable at this rung: saved 8-bit")
    a8 = np.round(px * 255).astype(np.uint8)
    if fmt in ("JPEG", "BMP") and c in (2, 4):
        col, al = px[..., :c - 1], px[..., c - 1:]
        a8 = np.round((col * al + (1 - al)) * 255).astype(np.uint8)
        img.notes.append(f"{fmt} has no alpha: flattened onto white")
        c -= 1
    mode = {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}[c]
    im = Image.fromarray(a8[..., 0] if c == 1 else a8, mode)
    kw = {}
    if img.icc and fmt != "BMP":
        kw["icc_profile"] = img.icc
    if img.exif and fmt in ("JPEG", "PNG", "WEBP", "TIFF", "AVIF"):
        kw["exif"] = img.exif
    if img.xmp and fmt in ("JPEG", "PNG", "WEBP", "TIFF", "AVIF"):
        kw["xmp"] = img.xmp if isinstance(img.xmp, bytes) else str(img.xmp).encode()
    if fmt == "JPEG":
        kw.update(quality=quality, subsampling="4:4:4")
    if fmt == "WEBP":
        kw.update(lossless=True, exact=True)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as f:
        try:
            im.save(f, fmt, **kw)
        except (TypeError, ValueError, OSError):
            kw.pop("xmp", None)
            f.seek(0)
            f.truncate()
            im.save(f, fmt, **kw)
            img.notes.append("XMP not written by this format's saver")
    if used:
        used.add("save", 1, "Pillow")
    return path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- shared filters
def per_channel_linear(img, fn):
    """Run fn(2D)->2D on linear, premultiplied channels (R6, R13); return new px."""
    col = to_lin(img.color())
    if img.alpha:
        a = img.px[..., -1:]
        chans = [col[..., i] * a[..., 0] for i in range(col.shape[2])] + [a[..., 0]]
    else:
        chans = [col[..., i] for i in range(col.shape[2])]
    res = [np.asarray(fn(ch), np.float32) for ch in chans]
    if img.alpha:
        a2 = np.clip(res[-1], 0, 1)
        safe = np.where(a2 > 1e-6, a2, 1)
        col2 = np.stack([np.where(a2 > 1e-6, r / safe, 0) for r in res[:-1]], axis=2)
        return np.concatenate([to_enc(col2), a2[..., None]], axis=2)
    return to_enc(np.stack(res, axis=2))


def gaussian_kernel(sigma):
    r = max(1, int(math.ceil(4 * sigma)))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return (k / k.sum()).astype(np.float32), r


def gaussian_blur(ch, sigma, used=None):
    nd = probe("scipy.ndimage")
    if nd is not None:
        if used:
            used.add("blur", 2, "scipy.ndimage.gaussian_filter")
        return nd.gaussian_filter(ch, sigma, mode="reflect", truncate=4.0)
    if used:
        used.add("blur", 1, "NumPy separable Gaussian")
    k, r = gaussian_kernel(sigma)
    out = ch
    for axis in (0, 1):
        pad = [(r, r) if a == axis else (0, 0) for a in (0, 1)]
        p = np.pad(out, pad, mode="symmetric")
        acc = np.zeros_like(out)
        n = out.shape[axis]
        for i, kv in enumerate(k):
            acc += kv * (p[i:i + n] if axis == 0 else p[:, i:i + n])
        out = acc
    return out


# ---------------------------------------------------------------- curves and LUTs
def monotone_curve(points, x):
    """Fritsch-Carlson monotone cubic through points [(x,y)...], evaluated at x."""
    pts = sorted(points)
    xs = np.array([p[0] for p in pts], np.float64)
    ys = np.array([p[1] for p in pts], np.float64)
    if len(xs) < 2:
        raise ValueError("curves needs at least two points")
    h = np.diff(xs)
    d = np.diff(ys) / h
    m = np.zeros_like(ys)
    m[0], m[-1] = d[0], d[-1]
    for k in range(1, len(xs) - 1):
        if d[k - 1] * d[k] > 0:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
    xc = np.clip(x, xs[0], xs[-1])
    i = np.clip(np.searchsorted(xs, xc, side="right") - 1, 0, len(xs) - 2)
    t = (xc - xs[i]) / h[i]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    return (h00 * ys[i] + h10 * h[i] * m[i] + h01 * ys[i + 1] + h11 * h[i] * m[i + 1]).astype(np.float32)


def read_cube(path):
    size, dim, dmin, dmax, rows = None, 3, [0.0] * 3, [1.0] * 3, []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.split("#")[0].strip()
        if not s:
            continue
        k = s.split()
        if k[0] == "LUT_3D_SIZE":
            size, dim = int(k[1]), 3
        elif k[0] == "LUT_1D_SIZE":
            size, dim = int(k[1]), 1
        elif k[0] == "DOMAIN_MIN":
            dmin = [float(v) for v in k[1:4]]
        elif k[0] == "DOMAIN_MAX":
            dmax = [float(v) for v in k[1:4]]
        else:
            try:
                rows.append([float(v) for v in k[:3]])
            except ValueError:
                pass
    t = np.array(rows, np.float32)
    if size is None or len(t) != size ** dim:
        raise ValueError(f"bad .cube: size {size}, {len(t)} rows")
    return dim, size, np.array(dmin, np.float32), np.array(dmax, np.float32), t


def apply_cube(c, cube):
    dim, n, dmin, dmax, t = cube
    x = np.clip((c - dmin) / (dmax - dmin), 0, 1) * (n - 1)
    if dim == 1:
        g = np.arange(n, dtype=np.float32)
        return np.stack([np.interp(x[..., i], g, t[:, i]) for i in range(3)], axis=2).astype(np.float32)
    lut = t.reshape(n, n, n, 3)  # [b, g, r] with red fastest in the file
    i0 = np.clip(np.floor(x).astype(np.int32), 0, n - 2)
    f = x - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = 0
    for db, wb in ((0, 1 - fb), (1, fb)):
        for dg, wg in ((0, 1 - fg), (1, fg)):
            for dr, wr in ((0, 1 - fr), (1, fr)):
                out = out + wb * wg * wr * lut[b0 + db, g0 + dg, r0 + dr]
    return out.astype(np.float32)


def rgb_to_hsv(c):
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx, mn = c.max(axis=2), c.min(axis=2)
    d = mx - mn
    ds = np.where(d > 0, d, 1)
    h = np.where(mx == r, ((g - b) / ds) % 6, np.where(mx == g, (b - r) / ds + 2, (r - g) / ds + 4))
    h = np.where(d > 0, h / 6, 0)
    s = np.where(mx > 0, d / np.where(mx > 0, mx, 1), 0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    h6 = (h % 1.0) * 6
    i = np.floor(h6).astype(np.int32) % 6
    f = h6 - np.floor(h6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    sel = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    out = [np.choose(i, [s_[k] for s_ in sel]) for k in range(3)]
    return np.stack(out, axis=2).astype(np.float32)


# ---------------------------------------------------------------- ops (recipe steps)
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def on_luma(c, fn):
    """Apply a tone function to luma (Rec. 709 weights on encoded values) and scale the colour by
    the luma ratio, so hue and saturation survive (per-channel curves wash colour out)."""
    y = (c[..., :3] * LUMA).sum(axis=2, keepdims=True)
    y2 = fn(y)
    safe = np.maximum(y, 1e-6)
    out = np.where(y > 1e-6, c[..., :3] * (y2 / safe), y2)
    out = np.clip(out, 0, 1).astype(np.float32)
    return np.concatenate([out, c[..., 3:]], axis=2) if c.shape[2] > 3 else out


def tone(img, p, fn, tool):
    """Run fn on luma for colour images when p['on'] == 'luminance', else on every channel.
    Recipes from before 0.7.0 have no 'on' key and replay per channel, as they were made."""
    c = img.color()
    if p.get("on", "channels") == "luminance" and c.shape[2] >= 3:
        return on_luma(c, fn), tool + " on luminance"
    return fn(c), tool


def op_levels(img, p, used):
    ib, iw, g = p.get("in_black", 0.0), p.get("in_white", 1.0), p.get("gamma", 1.0)
    ob, ow = p.get("out_black", 0.0), p.get("out_white", 1.0)

    def fn(v):
        return ob + np.clip((v - ib) / max(iw - ib, 1e-6), 0, 1) ** (1.0 / g) * (ow - ob)
    r, tool = tone(img, p, fn, "NumPy")
    used.add("adjust.levels", 1, tool)
    return img.with_color(r)


def op_curves(img, p, used):
    ch = p.get("channel", "rgb")
    if ch == "rgb":
        r, tool = tone(img, p, lambda v: monotone_curve(p["points"], v), "NumPy monotone cubic")
        used.add("adjust.curves", 1, tool)
        return img.with_color(r)
    c = img.color().copy()
    i = {"r": 0, "g": 1, "b": 2}[ch]
    c[..., i] = monotone_curve(p["points"], c[..., i])
    used.add("adjust.curves", 1, "NumPy monotone cubic")
    return img.with_color(c)


def _eq_map(v, bins=256):
    """Cumulative-histogram mapping (bin -> 0..1) of a 1-D sample."""
    h, _ = np.histogram(np.clip(v, 0, 1), bins=bins, range=(0, 1))
    if not h.any():
        return np.linspace(0, 1, bins)
    cdf = np.cumsum(h).astype(np.float64)
    lo = cdf[np.nonzero(h)[0][0]]
    return np.clip((cdf - lo) / max(cdf[-1] - lo, 1), 0, 1)


def equalize(y, strength=1.0, tiles=0, bins=256):
    """Histogram equalisation of a HxWx1 plane, mixed with the input by strength. tiles > 0: one curve
    per tile on a tiles x tiles grid, bilinearly interpolated between tile centres (no block seams)."""
    h, w = y.shape[:2]
    y2 = y[..., 0]
    idx = np.clip((y2 * (bins - 1)).round().astype(np.int64), 0, bins - 1)
    if not tiles:
        out = _eq_map(y2.ravel(), bins)[idx]
    else:
        ty, tx = max(1, min(tiles, h)), max(1, min(tiles, w))
        ys, xs = np.linspace(0, h, ty + 1).astype(int), np.linspace(0, w, tx + 1).astype(int)
        maps = np.array([[_eq_map(y2[ys[j]:ys[j + 1], xs[i]:xs[i + 1]].ravel(), bins) for i in range(tx)]
                         for j in range(ty)])
        cy, cx = (ys[:-1] + ys[1:]) / 2.0, (xs[:-1] + xs[1:]) / 2.0
        gy = np.interp(np.arange(h) + 0.5, cy, np.arange(ty))
        gx = np.interp(np.arange(w) + 0.5, cx, np.arange(tx))
        j0 = np.clip(np.floor(gy).astype(int), 0, max(ty - 2, 0))
        i0 = np.clip(np.floor(gx).astype(int), 0, max(tx - 2, 0))
        j1, i1 = np.minimum(j0 + 1, ty - 1), np.minimum(i0 + 1, tx - 1)
        fy, fx = np.clip(gy - j0, 0, 1)[:, None], np.clip(gx - i0, 0, 1)[None, :]
        J0, J1, I0, I1 = j0[:, None], j1[:, None], i0[None, :], i1[None, :]
        out = (maps[J0, I0, idx] * (1 - fy) * (1 - fx) + maps[J0, I1, idx] * (1 - fy) * fx
               + maps[J1, I0, idx] * fy * (1 - fx) + maps[J1, I1, idx] * fy * fx)
    s = float(strength)
    return (y2 * (1 - s) + out * s)[..., None].astype(np.float32)


def op_equalize(img, p, used):
    s, t = float(p.get("strength", 1.0)), int(p.get("tiles", 0))
    p2 = dict(p, on=p.get("on", "luminance"))
    kind = f"tiled {t}x{t}" if t else "global"
    r, tool = tone(img, p2, lambda v: np.concatenate([equalize(v[..., i:i + 1], s, t) for i in range(v.shape[2])],
                                                      axis=2), f"NumPy histogram equalisation ({kind})")
    used.add("adjust.equalize", 1, tool)
    return img.with_color(r)


def op_exposure(img, p, used):
    used.add("adjust.exposure", 1, "NumPy linear light")
    return img.with_color(to_enc(to_lin(img.color()) * 2.0 ** p["stops"]))


def op_white_balance(img, p, used):
    m = np.array(p["multipliers"], np.float32)
    used.add("adjust.white_balance", 1, "NumPy linear light")
    if img.nc < 3:
        img.notes.append("white balance skipped: greyscale image")
        return img
    return img.with_color(to_enc(to_lin(img.color()) * m))


def op_hue_sat(img, p, used):
    used.add("adjust.hue_sat", 1, "NumPy HSV")
    if img.nc < 3:
        img.notes.append("hue/saturation skipped: greyscale image")
        return img
    h, s, v = rgb_to_hsv(img.color())
    c = hsv_to_rgb(h + p.get("hue", 0.0) / 360.0, np.clip(s * p.get("saturation", 1.0), 0, 1), v)
    L = p.get("lightness", 0.0)
    c = c + (1 - c) * L if L > 0 else c * (1 + L)
    return img.with_color(c)


def op_lut(img, p, used):
    used.add("adjust.lut", 1, "NumPy trilinear .cube")
    if img.nc < 3:
        img.notes.append("LUT skipped: greyscale image")
        return img
    return img.with_color(apply_cube(img.color(), read_cube(p["file"])))


def op_bw(img, p, used):
    w = np.array(p.get("weights", [0.2126, 0.7152, 0.0722]), np.float32)
    used.add("adjust.bw", 1, "NumPy channel mix")
    if img.nc < 3:
        return img
    g = np.clip((img.color() * w).sum(axis=2, keepdims=True), 0, 1)
    out = img.copy(px=np.concatenate([g, img.px[..., -1:]], axis=2) if img.alpha else g)
    if out.icc:
        out.notes.append("RGB ICC profile dropped from the greyscale result (an RGB profile cannot tag grey pixels)")
        out.icc = None
    return out


def op_crop(img, p, used):
    l, t, r, b = p["box"]
    h, w = img.px.shape[:2]
    if not (0 <= l < r <= w and 0 <= t < b <= h):
        raise ValueError(f"crop box {p['box']} outside image {w}x{h}")
    used.add("crop", 1, "NumPy slice")
    return img.copy(px=img.px[t:b, l:r].copy())


def resize_target(w, h, p):
    """Target size from a resize step: scale, width and/or height (one side keeps the aspect)."""
    if p.get("scale"):
        return max(1, round(w * float(p["scale"]))), max(1, round(h * float(p["scale"])))
    pw, ph = p.get("width"), p.get("height")
    if pw and ph:
        return int(pw), int(ph)
    if pw:
        return int(pw), max(1, round(h * int(pw) / w))
    if ph:
        return max(1, round(w * int(ph) / h)), int(ph)
    raise ValueError("resize: give scale, width or height")


def op_resize(img, p, used):
    h0, w0 = img.px.shape[:2]
    w, h = resize_target(w0, h0, p)
    filt = {"lanczos": Image.LANCZOS, "bicubic": Image.BICUBIC, "bilinear": Image.BILINEAR,
            "nearest": Image.NEAREST, "box": Image.BOX}[p.get("filter", "lanczos")]
    used.add("resize", 1, f"Pillow F-mode {p.get('filter', 'lanczos')} in linear light")
    px = per_channel_linear(img, lambda ch: np.asarray(Image.fromarray(ch, "F").resize((w, h), filt)))
    return img.copy(px=px)


def inscribed(w, h, ang):
    """Largest axis-aligned rectangle inside a w x h rectangle rotated by ang radians."""
    longer = w >= h
    sl, ss = (w, h) if longer else (h, w)
    sa, ca = abs(math.sin(ang)), abs(math.cos(ang))
    if ss <= 2 * sa * ca * sl or abs(sa - ca) < 1e-10:
        x = 0.5 * ss
        return (x / sa, x / ca) if longer else (x / ca, x / sa)
    c2 = ca * ca - sa * sa
    return (w * ca - h * sa) / c2, (h * ca - w * sa) / c2


def op_rotate(img, p, used):
    out = img
    ang = float(p.get("angle", 0)) % 360
    if p.get("flip") in ("h", "horizontal"):
        out = out.copy(px=out.px[:, ::-1].copy())
    elif p.get("flip") in ("v", "vertical"):
        out = out.copy(px=out.px[::-1].copy())
    if ang % 90 == 0:
        if ang:
            out = out.copy(px=np.ascontiguousarray(np.rot90(out.px, int(ang // 90))))
        used.add("rotate", 1, "NumPy exact (multiple of 90 / flip)")
        return out
    h, w = out.px.shape[:2]
    had_alpha = out.alpha
    work = out if had_alpha else out.copy(px=np.concatenate([out.px, np.ones((h, w, 1), np.float32)], 2), alpha=True)
    expand = bool(p.get("expand", True)) and not p.get("crop")
    px = per_channel_linear(work, lambda ch: np.asarray(
        Image.fromarray(ch, "F").rotate(ang, resample=Image.BICUBIC, expand=expand, fillcolor=0.0)))
    used.add("rotate", 1, "Pillow F-mode bicubic in linear light")
    if p.get("crop"):
        wr, hr = inscribed(w, h, math.radians(ang))
        wr, hr = int(math.floor(wr)) - 2, int(math.floor(hr)) - 2
        H, W = px.shape[:2]
        l, t = (W - wr) // 2, (H - hr) // 2
        px = px[t:t + hr, l:l + wr]
    if not had_alpha:
        fill = np.array(p.get("fill", [0, 0, 0])[:out.nc], np.float32)
        a = px[..., -1:]
        px = to_enc(to_lin(px[..., :-1]) * a + to_lin(fill) * (1 - a))
    return out.copy(px=np.ascontiguousarray(px), alpha=had_alpha)


def op_sharpen(img, p, used):
    amount, sigma, thr = p.get("amount", 1.0), p.get("radius", 1.0), p.get("threshold", 0.0)
    linear = p.get("space", "linear") == "linear"
    c = img.color()
    base = to_lin(c) if linear else c
    blur = np.stack([gaussian_blur(base[..., i], sigma, used) for i in range(base.shape[2])], axis=2)
    diff = base - blur
    res = base + amount * np.where(np.abs(diff) > thr, diff, 0)
    used.add("sharpen", used.items[-1]["rung"], "unsharp mask")
    return img.with_color(np.clip(to_enc(res) if linear else res, 0, 1))


def median_filter(ch, r):
    p = np.pad(ch, r, mode="symmetric")
    h, w = ch.shape
    stack = [p[dy:dy + h, dx:dx + w] for dy in range(2 * r + 1) for dx in range(2 * r + 1)]
    return np.median(np.stack(stack), axis=0)


def bilateral_lab(c, ss, sc, used):
    """Bilateral filter that weighs neighbours by whole-colour distance in CIE Lab (Delta E), so all
    channels share one weight per neighbour (per-channel weights fringe colour at edges). Averages in
    linear light."""
    from .masks import rgb_to_lab
    rgb = np.repeat(c, 3, axis=2) if c.shape[2] == 1 else c[..., :3]
    lab = rgb_to_lab(rgb).astype(np.float32)
    lin = to_lin(c)
    r = max(1, int(np.ceil(2 * ss)))
    pl = np.pad(lab, ((r, r), (r, r), (0, 0)), mode="reflect")
    pc = np.pad(lin, ((r, r), (r, r), (0, 0)), mode="reflect")
    h, w = c.shape[:2]
    acc = np.zeros_like(lin)
    wsum = np.zeros((h, w, 1), np.float32)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            ws = np.exp(-(dx * dx + dy * dy) / (2 * ss * ss))
            if ws < 1e-3:
                continue
            nl = pl[r + dy:r + dy + h, r + dx:r + dx + w]
            d2 = ((nl - lab) ** 2).sum(axis=2, keepdims=True)
            wt = (ws * np.exp(-d2 / (2 * sc * sc))).astype(np.float32)
            acc += wt * pc[r + dy:r + dy + h, r + dx:r + dx + w]
            wsum += wt
    used.add("denoise", 1, f"NumPy bilateral, Lab Delta E (sigma space {ss:g}, colour {sc:g})")
    return to_enc(acc / np.maximum(wsum, 1e-8))


def op_denoise(img, p, used):
    c = img.color()
    cv2 = probe("cv2") if p.get("method", "auto") in ("auto", "nlmeans") else None
    if cv2 is not None:
        hs = float(p.get("strength", 10))
        u8 = np.round(np.clip(c, 0, 1) * 255).astype(np.uint8)
        if c.shape[2] == 3:
            r = cv2.fastNlMeansDenoisingColored(np.ascontiguousarray(u8[..., ::-1]), None, hs, hs, 7, 21)[..., ::-1]
        else:
            r = cv2.fastNlMeansDenoising(np.ascontiguousarray(u8[..., 0]), None, hs, 7, 21)[..., None]
        if img.bits > 8:
            img.notes.append("NL-means ran on 8-bit data (OpenCV colour NL-means is 8-bit only)")
        used.add("denoise", 2, "OpenCV fastNlMeansDenoising")
        return img.with_color(r.astype(np.float32) / 255.0)
    if p.get("method") == "bilateral":
        return img.with_color(bilateral_lab(c, float(p.get("sigma_space", 2.0)), float(p.get("sigma_color", 8.0)), used))
    r = int(p.get("radius", 1))
    used.add("denoise", 1, f"NumPy median {2 * r + 1}x{2 * r + 1}")
    return img.with_color(np.stack([median_filter(c[..., i], r) for i in range(c.shape[2])], axis=2))


OPS = {"adjust.levels": op_levels, "adjust.curves": op_curves, "adjust.exposure": op_exposure,
       "adjust.white_balance": op_white_balance, "adjust.hue_sat": op_hue_sat, "adjust.lut": op_lut,
       "adjust.bw": op_bw, "adjust.equalize": op_equalize, "crop": op_crop, "resize": op_resize, "rotate": op_rotate,
       "sharpen": op_sharpen, "denoise": op_denoise,
       "convert": None}  # filled below (op_convert is defined after OPS)


def load_mask(path, shape):
    m = np.asarray(Image.open(path).convert("L"), np.float32) / 255.0
    if m.shape != shape:
        raise ValueError(f"mask {path} is {m.shape[::-1]}, image is {shape[::-1]}")
    return m[..., None]


def apply_steps(img, steps, used, base_dir=None):
    for st in steps:
        fn = OPS.get(st["op"])
        if fn is None:
            raise ValueError(f"unknown op {st['op']}")
        prm = dict(st.get("params") or {})
        if base_dir and isinstance(prm.get("others"), list):
            prm["others"] = [f if Path(f).is_absolute() else str(Path(base_dir) / f) for f in prm["others"]]
        res = fn(img, prm, used)
        if st.get("mask"):
            mp = Path(st["mask"])
            if base_dir and not mp.is_absolute():
                mp = Path(base_dir) / mp
            if res.px.shape != img.px.shape:
                raise ValueError(f"{st['op']} changes the size: a mask cannot apply")
            m = load_mask(mp, img.px.shape[:2])
            res = res.copy(px=img.px * (1 - m) + res.px * m)
        img = res
    return img


# ---------------------------------------------------------------- recipe log
def rel_to(f, base):
    """Path of f relative to base with forward slashes; absolute when on another drive."""
    try:
        return os.path.relpath(Path(f).resolve(), Path(base).resolve()).replace("\\", "/")
    except ValueError:
        return str(Path(f).resolve())


def others_changed(steps, base_dir):
    """Stack/stitch inputs that are missing or whose sha256 no longer matches the recipe."""
    bad = []
    for st in steps:
        prm = st.get("params") or {}
        for f, h in zip(prm.get("others") or [], prm.get("others_sha256") or []):
            fp = Path(f) if Path(f).is_absolute() else Path(base_dir) / f
            if not fp.exists() or sha256(fp) != h:
                bad.append(f)
    return bad


def record(recipe, src, steps, out, used, seconds):
    recipe = Path(recipe)
    if recipe.exists():
        r = json.loads(recipe.read_text(encoding="utf-8"))
    else:
        recipe.parent.mkdir(parents=True, exist_ok=True)
        try:
            rel = os.path.relpath(src, recipe.parent)
        except ValueError:
            rel = str(Path(src).resolve())
        r = {"version": 1, "source": {"file": rel.replace("\\", "/"), "sha256": sha256(src)}, "steps": []}
    r["steps"] += [{"op": s["op"], "params": s.get("params", {}), "mask": s.get("mask"),
                    "layer": s.get("layer"), "seed": s.get("seed")} for s in steps]
    recipe.write_text(json.dumps(r, indent=1), encoding="utf-8")
    log_line(recipe.parent / "log.jsonl", [s["op"] for s in steps], out, used, seconds)


def log_line(path, ops, out, used, seconds, extra=None):
    line = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "ops": ops, "rung": used.rung(), "tool": used.tool(),
            "phw": VERSION, "seconds": round(seconds, 3), "output": str(out), "output_sha256": sha256(out)}
    line.update(extra or {})
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


# ---------------------------------------------------------------- commands
def edit_command(a, tag, steps, ext=None):
    t0 = time.time()
    used = Used()
    img = load(a.input, used)
    img = apply_steps(img, steps, used)
    out = out_for(a.input, a.output, tag, ext)
    save(img, out, getattr(a, "bits", None), used)
    if a.recipe:
        record(a.recipe, a.input, steps, out, used, time.time() - t0)
    return {"command": tag, "input": str(a.input), "output": str(out), "rung": used.rung(), "tool": used.tool(),
            "used": used.items, "steps": steps, "notes": img.notes}


def floats(s, n=None):
    v = [float(x) for x in str(s).replace(";", ",").split(",") if x.strip()]
    if n and len(v) not in (n if isinstance(n, tuple) else (n,)):
        raise ValueError(f"expected {n} numbers, got {s!r}")
    return v


def cmd_adjust(a):
    steps = []
    if a.wb_gray:
        x, y = (int(v) for v in floats(a.wb_gray, 2))
        img = load(a.input)
        c = to_lin(img.color()[max(0, y - 2):y + 3, max(0, x - 2):x + 3]).reshape(-1, img.nc).mean(axis=0)
        steps.append({"op": "adjust.white_balance",
                      "params": {"multipliers": [float(c[1] / max(v, 1e-6)) for v in c], "picked": [x, y]}})
    if a.wb:
        steps.append({"op": "adjust.white_balance", "params": {"multipliers": floats(a.wb, 3)}})
    if a.exposure is not None:
        steps.append({"op": "adjust.exposure", "params": {"stops": a.exposure}})
    if a.levels:
        v = floats(a.levels, (2, 3, 5))
        keys = ["in_black", "in_white", "gamma", "out_black", "out_white"]
        steps.append({"op": "adjust.levels", "params": dict(zip(keys, v), on=a.on)})
    if a.curves:
        pts = [floats(p, 2) for p in a.curves.split()]
        steps.append({"op": "adjust.curves", "params": {"points": pts, "channel": a.channel, "on": a.on}})
    if a.equalize is not None:
        steps.append({"op": "adjust.equalize", "params": {"strength": a.equalize, "tiles": a.tiles, "on": a.on}})
    if a.hue or a.saturation is not None or a.lightness:
        steps.append({"op": "adjust.hue_sat", "params": {"hue": a.hue or 0.0, "saturation": 1.0 if a.saturation is None else a.saturation, "lightness": a.lightness or 0.0}})
    if a.lut:
        steps.append({"op": "adjust.lut", "params": {"file": str(Path(a.lut).resolve())}})
    if a.bw is not None:
        steps.append({"op": "adjust.bw", "params": {"weights": floats(a.bw, 3) if a.bw else [0.2126, 0.7152, 0.0722]}})
    if not steps:
        raise SystemExit("adjust: give at least one of --exposure --levels --curves --equalize --wb --wb-gray --hue --saturation --lightness --lut --bw")
    if a.mask:
        for s in steps:
            s["mask"] = str(Path(a.mask).resolve())
    return edit_command(a, "adjust", steps)


def cmd_crop(a):
    with Image.open(a.input) as im:
        im2 = ImageOps.exif_transpose(im)
        w, h = im2.size
    if a.box:
        box = [int(v) for v in floats(a.box, 4)]
    elif a.rect:
        x, y, cw, ch = (int(v) for v in floats(a.rect, 4))
        box = [x, y, x + cw, y + ch]
    elif a.aspect:
        n, d = (float(v) for v in a.aspect.split(":"))
        cw, ch = (w, int(round(w * d / n))) if w * d / n <= h else (int(round(h * n / d)), h)
        box = [(w - cw) // 2, (h - ch) // 2, (w - cw) // 2 + cw, (h - ch) // 2 + ch]
    else:
        raise SystemExit("crop: give --box l,t,r,b or --rect x,y,w,h or --aspect W:H")
    return edit_command(a, "crop", [{"op": "crop", "params": {"box": box}}])


def cmd_resize(a):
    # record the intent (scale, or one side), not the pixel size, so a recipe replays on other files (batch)
    if a.scale:
        p = {"scale": a.scale}
    elif a.width or a.height:
        p = {k: v for k, v in (("width", a.width), ("height", a.height)) if v}
    else:
        raise SystemExit("resize: give --scale or --width/--height")
    p["filter"] = a.filter
    return edit_command(a, "resize", [{"op": "resize", "params": p}])


def cmd_rotate(a):
    p = {"angle": a.angle, "expand": not a.no_expand, "crop": a.straighten}
    if a.flip:
        p["flip"] = a.flip
    if a.fill:
        p["fill"] = floats(a.fill)
    return edit_command(a, "rotate", [{"op": "rotate", "params": p}])


def cmd_sharpen(a):
    return edit_command(a, "sharpen", [{"op": "sharpen", "params": {
        "amount": a.amount, "radius": a.radius, "threshold": a.threshold, "space": a.space}}])


def cmd_denoise(a):
    return edit_command(a, "denoise", [{"op": "denoise", "params": {
        "method": a.method, "strength": a.strength, "radius": a.radius,
        "sigma_space": a.sigma_space, "sigma_color": a.sigma_color}}])


def op_convert(img, p, used):
    """Profile and metadata handling as a recipe step (format and quality are save options)."""
    prof, intent = p.get("profile", "keep"), int(p.get("intent", 0))
    if prof == "strip":
        img.icc = None
    elif prof == "srgb" and img.icc and "srgb" not in (icc_name(img.icc) or "").lower():
        if ImageCms is None:
            raise SystemExit("convert to sRGB needs Pillow's ImageCms")
        if img.nc != 3:
            img.notes.append("profile conversion skipped: only RGB is converted")
        else:
            src = ImageCms.ImageCmsProfile(io.BytesIO(img.icc))
            dst = ImageCms.createProfile("sRGB")
            if img.bits > 8:
                img.notes.append("profile conversion ran at 8 bits per channel (LittleCMS via Pillow)")
            u8 = Image.fromarray(np.round(np.clip(img.color(), 0, 1) * 255).astype(np.uint8), "RGB")
            conv = ImageCms.profileToProfile(u8, src, dst, renderingIntent=intent, outputMode="RGB")
            img = img.with_color(np.asarray(conv, np.float32) / 255.0)
            img.notes.append(f"pixels converted from '{icc_name(img.icc)}' to sRGB")
            img.icc = srgb_icc()
            used.add("profile", 1, "Pillow ImageCms (LittleCMS)")
    elif prof == "srgb" and not img.icc:
        img.icc = srgb_icc()
        img.notes.append("sRGB profile embedded (source had none)")
    if p.get("metadata", "keep") == "strip":
        img.exif, img.xmp = None, None
    elif p.get("strip_gps") and img.exif:
        ex = Image.Exif()
        ex.load(img.exif)
        if 0x8825 in ex:
            del ex[0x8825]
            img.notes.append("GPS stripped")
        img.exif = _exif_bytes(ex)
    used.add("convert", 1, "Pillow")
    return img


def cmd_convert(a):
    t0 = time.time()
    used = Used()
    img = load(a.input, used)
    ext = ("." + a.format.lower().lstrip(".")) if a.format else None
    out = out_for(a.input, a.output, "convert", ext)
    steps = [{"op": "convert", "params": {"profile": a.profile, "intent": a.intent, "metadata": a.metadata,
                                          "strip_gps": bool(a.strip_gps)}}]
    img = apply_steps(img, steps, used)
    bits = a.bits or img.bits
    save(img, out, bits, used, quality=a.quality)
    if a.recipe:
        record(a.recipe, a.input, steps, out, used, time.time() - t0)
        if a.quality is not None or a.format:
            img.notes.append("recipe: format and quality are save options and are not recorded; pass --ext to run/batch")
    return {"command": "convert", "input": str(a.input), "output": str(out), "bits": bits,
            "profile": icc_name(img.icc), "rung": used.rung(), "tool": used.tool(), "used": used.items,
            "notes": img.notes}


def cmd_inspect(a):
    path = Path(a.input)
    r = {"command": "inspect", "file": str(path), "bytes": path.stat().st_size, "rung": 1, "tool": ["Pillow"]}
    with Image.open(path) as im:
        exif = im.getexif()
        r.update(format=im.format, mode=im.mode, stored_size=list(im.size))
        o = exif.get(274, 1)
        r["exif_orientation"] = o
        r["size"] = list(im.size[::-1]) if o in (5, 6, 7, 8) else list(im.size)
        bits = 8
        if im.format == "PNG":
            bits = png_bitdepth(path)[0]
        elif im.format == "TIFF":
            bits = int(im.tag_v2.get(258, (8,))[0])
        elif im.mode.startswith("I;16"):
            bits = 16
        elif im.mode in ("I", "F"):
            bits = 32
        elif im.mode == "1":
            bits = 1
        r["bit_depth"] = bits
        r["alpha"] = "A" in im.mode or "transparency" in im.info
        icc = im.info.get("icc_profile")
        r["icc_profile"] = icc_name(icc)
        if not icc:
            r["icc_note"] = "none embedded: treated as sRGB"
        r["metadata_keys"] = sorted(k for k in im.info if k not in ("icc_profile",))
        r["exif_tags"] = sorted(str(ExifTags.TAGS.get(k, k)) for k in exif)
        r["gps"] = 0x8825 in exif
        r["xmp"] = bool(im.info.get("xmp") or im.info.get("XML:com.adobe.xmp"))
        layers = None
        if im.format == "PSD":
            layers = len(getattr(im, "layers", []) or [])
        elif getattr(im, "n_frames", 1) > 1:
            layers = im.n_frames
            r["frames"] = im.n_frames
        r["layers"] = layers
    if path.suffix.lower() == ".ora":
        with zipfile.ZipFile(path) as z:
            r["layers"] = z.read("stack.xml").decode("utf-8", "replace").count("<layer")
    return r


TOOLS_ON_PATH = ["vtracer", "potrace", "inkscape", "gimp", "gimp-console", "gimp-3.0", "gimp-console-3.0",
                 "gimp-2.10", "gimp-console-2.10", "magick", "exiftool", "krita"]


def gimp_console():
    """GIMP 3 batch binary: PATH first, then the usual per-user and machine installs."""
    for t in ("gimp-console-3", "gimp-console-3.0", "gimp-console"):
        w = shutil.which(t)
        if w:
            return w
    roots = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs", Path(os.environ.get("ProgramFiles", "C:/Program Files"))]
    for r in roots:
        for d in sorted(r.glob("GIMP*/bin"), reverse=True) if r.exists() else []:
            for n in ("gimp-console-3.exe", "gimp-console.exe"):
                if (d / n).exists():
                    return str(d / n)
    return None


def cmd_doctor(a):
    def ver(m):
        mod = probe(m)
        return getattr(mod, "__version__", "present") if mod is not None else None
    mods = {"python": sys.version.split()[0], "Pillow": Image.__version__, "numpy": np.__version__,
            "ImageCms": ImageCms is not None, "cv2": ver("cv2"), "scipy": ver("scipy"),
            "skimage": ver("skimage"), "vtracer (pip)": ver("vtracer") or (importlib.util.find_spec("vtracer") and "present")}
    try:
        fmts = {f: bool(features.check(f)) for f in ("webp", "avif", "jpg", "zlib", "libtiff", "littlecms2")}
    except Exception:
        fmts = {}
    path = {t: shutil.which(t) for t in TOOLS_ON_PATH}
    path["gimp-console (installed)"] = gimp_console()
    from . import vector  # noqa: PLC0415  (Inkscape is often installed but not on PATH)
    if not path.get("inkscape"):
        path["inkscape"] = vector.inkscape()
    cv2, nd = probe("cv2"), probe("scipy.ndimage")
    groups = {
        "load/save 8-bit, ICC, EXIF": (1, "Pillow"),
        "16-bit PNG": (1, "own PNG16 codec"),
        "16-bit RGB TIFF": (2, "OpenCV") if cv2 else (1, "Pillow (falls back to 8-bit)"),
        "adjust (levels, curves, exposure, wb, hue/sat, LUT, b&w)": (1, "NumPy"),
        "crop, resize, rotate": (1, "Pillow F-mode in linear light"),
        "blur/sharpen": (2, "scipy.ndimage") if nd else (1, "NumPy separable Gaussian"),
        "denoise": (2, "OpenCV NL-means") if cv2 else (1, "NumPy median"),
        "profile conversion": (1, "ImageCms") if ImageCms else (0, "missing: Pillow without LittleCMS"),
    }
    for fn in DOCTOR_GROUPS:
        groups.update(fn())
    missing = [k for k, v in mods.items() if v in (None, False)] + [t for t, p in path.items() if not p and t in (
        "potrace", "inkscape", "gimp", "magick", "exiftool")]
    return {"command": "doctor", "version": VERSION, "rung_max": rung_max(), "modules": mods, "pillow_features": fmts,
            "on_path": path, "groups": {k: {"rung": v[0], "tool": v[1]} for k, v in groups.items()},
            "missing": missing, "rung": 1, "tool": ["stdlib"]}


GLOSSARY = {
    "linear light": "Pixel values proportional to light. sRGB files store gamma-encoded values; resize, blur and exposure must convert to linear first (R6), or averages come out too dark.",
    "srgb": "The default RGB space of the web and most cameras. Encoded with a curve close to gamma 2.2: linear = v/12.92 below 0.04045, else ((v+0.055)/1.055)^2.4.",
    "icc profile": "A file that maps an image's numbers to real colours. 'Convert' changes pixels to a new profile; 'assign' only relabels them. photowright keeps the profile unless you strip or convert on purpose.",
    "bit depth": "Bits per channel: 8 gives 256 levels, 16 gives 65536. Stacked edits band in 8 bits; photowright works in float32 and quantises once at save.",
    "alpha": "Opacity channel. Stored straight (colour not multiplied by alpha); neighbour filters premultiply first to avoid dark fringes (R13).",
    "premultiplied alpha": "Colour already multiplied by alpha. Needed for correct resizing and blurring of transparent edges; PNG stores straight alpha.",
    "exif orientation": "EXIF tag 274 (1-8) telling viewers how to rotate the sensor pixels. photowright applies it on load and saves orientation 1.",
    "levels": "Remap input black/white points with a gamma in the middle, then output black/white. Applied on encoded values like Photoshop (R8).",
    "curves": "A tone curve through control points; photowright uses a monotone cubic so the curve never overshoots between points.",
    "exposure": "Multiply linear light by 2^stops. +1 stop doubles the light; done in linear light.",
    "white balance": "Per-channel gains in linear light that make a neutral grey come out neutral.",
    "hue/saturation": "Rotate hue (degrees), scale saturation, push lightness towards white or black, in HSV on encoded values.",
    "lut": "Look-up table (.cube): maps every input colour to an output colour; 3D LUTs are interpolated trilinearly.",
    "unsharp mask": "Sharpen = image + amount x (image - blurred image), only where the difference beats a threshold.",
    "nl-means": "Non-local means denoising: averages patches that look alike anywhere in a window; OpenCV's fastNlMeans (rung 2).",
    "lanczos": "A windowed sinc resampling filter: sharp with mild ringing. photowright runs it in linear light.",
    "chroma subsampling": "JPEG storing colour at lower resolution (4:2:0). Use 4:4:4 for graphics and text (R20).",
    "rung": "photowright's tool ladder: 1 own code (Pillow, NumPy), 2 free tools (OpenCV, SciPy, vtracer), 3 local models, 4 closed apps (optional).",
    "recipe": "recipe.json: the source file and its sha256 plus a list of steps {op, params, mask, layer, seed}; phw.py run replays it.",
}
BLEND = {
    "normal": "B(cb, cs) = cs",
    "multiply": "B = cb x cs (always darker)",
    "screen": "B = cb + cs - cb x cs (always lighter)",
    "overlay": "B = hard-light(cs, cb): multiply or screen depending on the backdrop",
    "darken": "B = min(cb, cs)",
    "lighten": "B = max(cb, cs)",
    "color-dodge": "B = 0 if cb = 0; 1 if cs = 1; else min(1, cb / (1 - cs))",
    "color-burn": "B = 1 if cb = 1; 0 if cs = 0; else 1 - min(1, (1 - cb) / cs)",
    "hard-light": "cs <= 0.5: multiply(cb, 2cs); else screen(cb, 2cs - 1)",
    "soft-light": "cs <= 0.5: cb - (1 - 2cs) cb (1 - cb); else cb + (2cs - 1)(D(cb) - cb), D = W3C piecewise",
    "difference": "B = |cb - cs|",
    "exclusion": "B = cb + cs - 2 cb cs",
    "hue": "SetLum(SetSat(cs, Sat(cb)), Lum(cb))",
    "saturation": "SetLum(SetSat(cb, Sat(cs)), Lum(cb))",
    "color": "SetLum(cs, Lum(cb))",
    "luminosity": "SetLum(cb, Lum(cs))",
}


def cmd_explain(a):
    term = " ".join(a.term).strip()
    key = term.lower().replace("_", " ")
    r = {"command": "explain", "term": term, "rung": 1, "tool": ["built-in glossary"]}
    bk = key.replace(" ", "-")
    if key in GLOSSARY:  # a glossary term wins over a same-named blend mode ("linear light")
        r.update(kind="term", text=GLOSSARY[key])
        if bk in BLEND:
            r["blend_mode"] = BLEND[bk]
        return r
    if bk in BLEND:
        r.update(kind="blend mode", formula=BLEND[bk],
                 text="W3C Compositing Level 1 formula on encoded straight colour (R7, R14); cb backdrop, cs source.",
                 source="https://www.w3.org/TR/compositing-1/")
        return r
    if key in GLOSSARY:
        r.update(kind="term", text=GLOSSARY[key])
        return r
    kb = ROOT / "kb" / "tools.json"
    rows = json.loads(kb.read_text(encoding="utf-8")) if kb.exists() else []
    hits = [t for t in rows if key in t["name"].lower()]
    if hits:
        r.update(kind="tool", tool=["kb/tools.json"], matches=hits[:5])
        return r
    names = list(GLOSSARY) + list(BLEND) + [t["name"].lower() for t in rows]
    r.update(kind="unknown", suggestions=difflib.get_close_matches(key, names, n=5, cutoff=0.5))
    return r


def cmd_run(a):
    t0 = time.time()
    recipe = Path(a.recipe_file)
    r = json.loads(recipe.read_text(encoding="utf-8"))
    if r.get("kind") in RUN_KINDS:
        return RUN_KINDS[r["kind"]](a, recipe, r)
    src = Path(r["source"]["file"])
    if not src.is_absolute():
        src = recipe.parent / src
    notes = []
    if sha256(src) != r["source"].get("sha256"):
        notes.append("source sha256 differs from the recipe: the source changed")
    bad = others_changed(r["steps"], recipe.parent)
    if bad:
        notes.append("other inputs missing or changed since the recipe: " + ", ".join(bad))
    used = Used()
    img = load(src, used)
    img = apply_steps(img, r["steps"], used, recipe.parent)
    out = Path(a.output) if a.output else recipe.parent / "out" / f"{src.stem}{a.ext or src.suffix}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out = free_path(out)
    if out.resolve() == src.resolve():
        raise RuntimeError("refusing to write over the source")
    save(img, out, a.bits, used)
    logp = recipe.parent / "log.jsonl"
    prev = None
    if logp.exists():
        for line in logp.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("run"):
                prev = d
    h = sha256(out)
    if prev is None:
        replay = "first run"
    elif prev["output_sha256"] == h:
        replay = "same"
    elif prev.get("rung") != used.rung() or prev.get("tool") != used.tool():
        replay = "drift (different rung or tool)"
    else:
        replay = "differs on the same rung"
    log_line(logp, [s["op"] for s in r["steps"]], out, used, time.time() - t0, {"run": True})
    return {"command": "run", "recipe": str(recipe), "output": str(out), "steps": len(r["steps"]),
            "replay": replay, "rung": used.rung(), "tool": used.tool(), "notes": img.notes + notes}


# ---------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(prog="phw.py", description="photowright: image edits as replayable steps")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--rung-max", type=int, help="hide tools above this rung (same as PHW_RUNG_MAX)")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def edit(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("input")
        p.add_argument("-o", "--output", help="output path (never overwritten: name-NNN)")
        p.add_argument("--recipe", help="append the step(s) to this recipe.json and log the run")
        p.add_argument("--bits", type=int, choices=(8, 16), help="output bit depth (default: as source)")
        p.set_defaults(fn=fn)
        return p

    p = sub.add_parser("doctor", help="what is installed and which rung each feature uses")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("explain", help="explain a term, blend mode or tool")
    p.add_argument("term", nargs="+")
    p.set_defaults(fn=cmd_explain)
    p = sub.add_parser("inspect", help="size, mode, profile, bit depth, alpha, orientation, metadata, layers")
    p.add_argument("input")
    p.set_defaults(fn=cmd_inspect)
    p = edit("convert", cmd_convert, "format, bit depth, profile and metadata")
    p.add_argument("--format", help="png, jpg, webp, tif ... (default: from -o or source)")
    p.add_argument("--profile", choices=("keep", "strip", "srgb"), default="keep")
    p.add_argument("--intent", type=int, default=0, help="rendering intent 0-3 (default perceptual)")
    p.add_argument("--metadata", choices=("keep", "strip"), default="keep")
    p.add_argument("--strip-gps", action="store_true")
    p.add_argument("--quality", type=int, default=95)
    p = edit("adjust", cmd_adjust, "levels, curves, exposure, white balance, hue/sat, LUT, b&w")
    p.add_argument("--exposure", type=float, help="stops, in linear light")
    p.add_argument("--levels", help="in_black,in_white[,gamma[,out_black,out_white]] (0..1)")
    p.add_argument("--curves", help="points 'x,y x,y ...' in 0..1")
    p.add_argument("--channel", choices=("rgb", "r", "g", "b"), default="rgb")
    p.add_argument("--on", choices=("luminance", "channels"), default="luminance",
                   help="levels, curves and equalize act on luma (keeps colour, default) or on each channel")
    p.add_argument("--equalize", type=float, nargs="?", const=1.0, help="histogram equalisation, strength 0..1 (default 1)")
    p.add_argument("--tiles", type=int, default=0, help="equalize per tile on an N x N grid, curves interpolated (0 = global)")
    p.add_argument("--wb", help="linear gains r,g,b")
    p.add_argument("--wb-gray", help="x,y of a pixel that should be neutral")
    p.add_argument("--hue", type=float, help="degrees")
    p.add_argument("--saturation", type=float, help="factor (1 = unchanged)")
    p.add_argument("--lightness", type=float, help="-1..1")
    p.add_argument("--lut", help=".cube file")
    p.add_argument("--bw", nargs="?", const="", help="black and white channel mix r,g,b (default luminance)")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("crop", cmd_crop, "crop by box, rect or aspect")
    p.add_argument("--box", help="left,top,right,bottom")
    p.add_argument("--rect", help="x,y,width,height")
    p.add_argument("--aspect", help="W:H, centred, largest")
    p = edit("resize", cmd_resize, "resize in linear light (Lanczos)")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--scale", type=float)
    p.add_argument("--filter", default="lanczos", choices=("lanczos", "bicubic", "bilinear", "box", "nearest"))
    p = edit("rotate", cmd_rotate, "rotate (degrees counter-clockwise), straighten, flip")
    p.add_argument("--angle", type=float, default=0.0)
    p.add_argument("--straighten", action="store_true", help="crop to the largest rectangle with no empty corners")
    p.add_argument("--no-expand", action="store_true")
    p.add_argument("--flip", choices=("h", "v"))
    p.add_argument("--fill", help="corner fill r,g,b 0..1 for images without alpha")
    p = edit("sharpen", cmd_sharpen, "unsharp mask")
    p.add_argument("--amount", type=float, default=1.0)
    p.add_argument("--radius", type=float, default=1.0, help="Gaussian sigma in pixels")
    p.add_argument("--threshold", type=float, default=0.0)
    p.add_argument("--space", choices=("linear", "encoded"), default="linear")
    p = edit("denoise", cmd_denoise, "denoise: OpenCV NL-means (rung 2), Lab bilateral or median (rung 1)")
    p.add_argument("--method", choices=("auto", "nlmeans", "bilateral", "median"), default="auto")
    p.add_argument("--sigma-space", type=float, default=2.0, help="bilateral spatial sigma in px")
    p.add_argument("--sigma-color", type=float, default=8.0, help="bilateral colour sigma in Lab Delta E")
    p.add_argument("--strength", type=float, default=10.0, help="NL-means h")
    p.add_argument("--radius", type=int, default=1, help="median radius")
    for fn in EXTRA_COMMANDS:
        fn(sub, edit)
    p = sub.add_parser("run", help="replay a recipe.json (image, mask or layers kind)")
    p.add_argument("recipe_file")
    p.add_argument("-o", "--output")
    p.add_argument("--ext", help="output extension when -o is not given")
    p.add_argument("--bits", type=int, choices=(8, 16))
    p.set_defaults(fn=cmd_run)
    return ap


def human(d, indent=""):
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"{indent}{k}:")
            human(v, indent + "  ")
        else:
            print(f"{indent}{k}: {v}")


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.rung_max is not None:
        os.environ["PHW_RUNG_MAX"] = str(a.rung_max)
    return a, a.fn(a)


def cli(argv=None):
    a, r = main(argv)
    if a.json:
        print(json.dumps(r, indent=1, default=str))
    else:
        human(r)

OPS["convert"] = op_convert
