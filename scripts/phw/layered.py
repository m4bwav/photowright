"""Layered files: OpenRaster read/write and PSD write (own code, rung 1); PSD read with
psd-tools when installed (rung 2) or phw's own minimal reader (8-bit RGB raster layers,
masks, groups: enough for files phw wrote and plain Photoshop files). Commands: open, save.

PSD layout from Adobe's File Formats Specification (Nov 2019); notes in
references/layered-formats.md. What is written: 8-bit RGB, raster layers trimmed to their
alpha bounds, names (Pascal + 'luni' Unicode), opacity, blend keys, visibility, clipping,
user masks (rect + default colour), groups as 'lsct' section dividers, a PackBits (RLE)
merged image. Not written: text, effects, adjustment layers, 16/32-bit, PSB.

ORA layout from the OpenRaster baseline spec: 'mimetype' stored first, stack.xml (top layer
first), PNG per layer, mergedimage.png, Thumbnails/thumbnail.png. ORA has no masks or
clipping, so phw bakes masks into the layer PNG other apps read and keeps the unmasked
pixels and the mask under phw: attributes for its own round trip.
"""
import io
import json
import re
import struct
import subprocess
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image

from . import core
from .compose import Doc, Layer, composite_doc, doc_from_recipe, norm_mode, write_doc
from .core import Used, free_path, log_line, probe

__all__ = ["read_layered", "write_psd", "write_ora", "read_psd_own", "read_ora", "gimp_layers",
           "PSD_KEYS", "packbits", "unpackbits"]

PSD_KEYS = {"normal": b"norm", "dissolve": b"diss", "darken": b"dark", "multiply": b"mul ",
            "color-burn": b"idiv", "linear-burn": b"lbrn", "darker-color": b"dkCl", "lighten": b"lite",
            "screen": b"scrn", "color-dodge": b"div ", "linear-dodge": b"lddg", "lighter-color": b"lgCl",
            "overlay": b"over", "soft-light": b"sLit", "hard-light": b"hLit", "vivid-light": b"vLit",
            "linear-light": b"lLit", "pin-light": b"pLit", "hard-mix": b"hMix", "difference": b"diff",
            "exclusion": b"smud", "subtract": b"fsub", "divide": b"fdiv", "hue": b"hue ",
            "saturation": b"sat ", "color": b"colr", "luminosity": b"lum ", "pass": b"pass"}
PSD_MODES = {v: k for k, v in PSD_KEYS.items()}
ORA_OPS = {"normal": "svg:src-over", "multiply": "svg:multiply", "screen": "svg:screen", "overlay": "svg:overlay",
           "darken": "svg:darken", "lighten": "svg:lighten", "color-dodge": "svg:color-dodge",
           "color-burn": "svg:color-burn", "hard-light": "svg:hard-light", "soft-light": "svg:soft-light",
           "difference": "svg:difference", "exclusion": "svg:exclusion", "hue": "svg:hue",
           "saturation": "svg:saturation", "color": "svg:color", "luminosity": "svg:luminosity",
           "linear-dodge": "svg:plus"}
ORA_MODES = {v: k for k, v in ORA_OPS.items()}
NS = "https://github.com/m4bwav/photowright/ns/ora"
ET.register_namespace("phw", NS)


def u8(a):
    return np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)


# ---------------------------------------------------------------- PackBits
def packbits(row):
    """PackBits (Apple / TIFF / PSD RLE) of one row of bytes."""
    row = np.asarray(row, np.uint8)
    n = len(row)
    if n == 0:
        return b""
    starts = np.flatnonzero(np.r_[True, row[1:] != row[:-1]])
    lens = np.diff(np.r_[starts, n])
    out = bytearray()
    lit = bytearray()

    def flush():
        for i in range(0, len(lit), 128):
            chunk = lit[i:i + 128]
            out.append(len(chunk) - 1)
            out.extend(chunk)
        lit.clear()
    for s, ln in zip(starts.tolist(), lens.tolist()):
        v = int(row[s])
        if ln >= 3:
            flush()
            while ln > 0:
                k = min(ln, 128)
                if k >= 2:
                    out.append(257 - k)
                    out.append(v)
                else:
                    lit.append(v)
                ln -= k
        else:
            lit.extend([v] * ln)
    flush()
    return bytes(out)


def unpackbits(data, size):
    out = bytearray()
    i = 0
    while len(out) < size and i < len(data):
        h = data[i]
        i += 1
        if h < 128:
            out += data[i:i + h + 1]
            i += h + 1
        elif h > 128:
            out += bytes([data[i]]) * (257 - h)
            i += 1
    return bytes(out[:size])


# ---------------------------------------------------------------- PSD write
def _enc_channel(a, compression):
    """Channel image data: 2-byte compression then data; a is h x w uint8."""
    h, w = a.shape
    if a.size == 0:
        return struct.pack(">H", 0)
    if compression == "raw":
        return struct.pack(">H", 0) + a.tobytes()
    rows = [packbits(a[y]) for y in range(h)]
    return struct.pack(">H", 1) + struct.pack(f">{h}H", *[len(r) for r in rows]) + b"".join(rows)


def _pascal(name, pad=4):
    b = name.encode("latin-1", "replace")[:255]
    s = bytes([len(b)]) + b
    return s + b"\0" * ((-len(s)) % pad)


def _info(key, data):
    data += b"\0" * ((-len(data)) % 4)
    return b"8BIM" + key + struct.pack(">I", len(data)) + data


def _luni(name):
    e = name.encode("utf-16-be")
    return _info(b"luni", struct.pack(">I", len(e) // 2) + e)


def _mask_block(lay):
    if lay.mask is None:
        return struct.pack(">I", 0)
    h, w = lay.mask.shape
    return struct.pack(">I4iBBxx", 20, lay.mask_y, lay.mask_x, lay.mask_y + h, lay.mask_x + w,
                       255 if lay.mask_default >= 0.5 else 0, 0)


def _record(name, rect, chans, key, opacity, clip, flags, lay, extra_info):
    top, left, bottom, right = rect
    r = struct.pack(">4iH", top, left, bottom, right, len(chans))
    for cid, data in chans:
        r += struct.pack(">hI", cid, len(data))
    r += b"8BIM" + key + struct.pack(">BBBx", int(round(opacity * 255)), 1 if clip else 0, flags)
    extra = _mask_block(lay) + struct.pack(">I", 0) + _pascal(name) + _luni(name) + extra_info
    return r + struct.pack(">I", len(extra)) + extra


def _psd_layers(layers, compression, recs, notes):
    for lay in layers:
        hidden = 0 if lay.visible else 0x02
        if lay.group:
            empty = [(c, struct.pack(">H", 0)) for c in (-1, 0, 1, 2)]
            div = Layer("</Layer group>")
            recs.append((_record("</Layer group>", (0, 0, 0, 0), empty, b"norm", 1.0, False, 0x18, div,
                                 _info(b"lsct", struct.pack(">I", 3))), empty))
            _psd_layers(lay.children, compression, recs, notes)
            key = PSD_KEYS[lay.blend]
            chans = list(empty)
            if lay.mask is not None:
                chans.append((-2, _enc_channel(u8(lay.mask), compression)))
            recs.append((_record(lay.name, (0, 0, 0, 0), chans, b"norm" if lay.blend == "pass" else key,
                                 lay.opacity, lay.clip, 0x18 | hidden, lay,
                                 _info(b"lsct", struct.pack(">I", 1) + b"8BIM" + key)), chans))
            continue
        a8 = u8(lay.px)
        ys, xs = np.nonzero(a8[..., 3])
        if len(ys):
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            a8 = a8[y0:y1, x0:x1]
            rect = (lay.y + int(y0), lay.x + int(x0), lay.y + int(y1), lay.x + int(x1))
        else:
            a8 = a8[:0, :0]
            rect = (0, 0, 0, 0)
        chans = [(cid, _enc_channel(a8[..., ch], compression)) for cid, ch in ((-1, 3), (0, 0), (1, 1), (2, 2))]
        if lay.mask is not None:
            chans.append((-2, _enc_channel(u8(lay.mask), compression)))
        key = PSD_KEYS.get(lay.blend)
        if key is None:
            raise ValueError(f"blend mode {lay.blend} has no PSD key")
        recs.append((_record(lay.name, rect, chans, key, lay.opacity, lay.clip, hidden, lay, b""), chans))


def write_psd(doc, out, used, space="gamma", compression="rle"):
    w, h = doc.width, doc.height
    if space != "gamma":
        doc.notes.append("PSD stores no blend space: Photoshop blends these layers in gamma; the merged image is linear-blended")
    recs = []
    _psd_layers(doc.layers, compression, recs, doc.notes)
    body = struct.pack(">h", len(recs)) + b"".join(r for r, _ in recs) + b"".join(
        d for _, chans in recs for _, d in chans)
    body += b"\0" * (len(body) % 2)
    lm = struct.pack(">I", len(body)) + body + struct.pack(">I", 0)
    flat = composite_doc(doc, space)
    rgb = u8(flat[..., :3] * flat[..., 3:] + (1 - flat[..., 3:]))  # merged image flattened on white
    if compression == "raw":
        merged = struct.pack(">H", 0) + b"".join(rgb[..., c].tobytes() for c in range(3))
    else:
        rows = [packbits(rgb[y, :, c]) for c in range(3) for y in range(h)]
        merged = struct.pack(">H", 1) + struct.pack(f">{len(rows)}H", *[len(r) for r in rows]) + b"".join(rows)
    data = (b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3) + struct.pack(">I", 0) + struct.pack(">I", 0)
            + struct.pack(">I", len(lm)) + lm + merged)
    with open(out, "xb") as f:
        f.write(data)
    used.add("save psd", 1, "own PSD writer")
    return out


# ---------------------------------------------------------------- PSD read (own)
class _R:
    def __init__(self, d, pos=0):
        self.d, self.p = d, pos

    def take(self, n):
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u(self, fmt):
        v = struct.unpack_from(">" + fmt, self.d, self.p)
        self.p += struct.calcsize(">" + fmt)
        return v if len(v) > 1 else v[0]


def _dec_channel(raw, h, w):
    if h <= 0 or w <= 0:
        return np.zeros((max(h, 0), max(w, 0)), np.uint8)
    comp = struct.unpack_from(">H", raw, 0)[0]
    body = raw[2:]
    if comp == 0:
        return np.frombuffer(body[:h * w], np.uint8).reshape(h, w)
    if comp == 1:
        counts = struct.unpack_from(f">{h}H", body, 0)
        pos = 2 * h
        rows = []
        for c in counts:
            rows.append(np.frombuffer(unpackbits(body[pos:pos + c], w), np.uint8))
            pos += c
        return np.stack(rows)
    import zlib
    a = np.frombuffer(zlib.decompress(body), np.uint8)[:h * w].reshape(h, w)
    if comp == 3:  # ZIP with prediction: per-row deltas
        a = np.cumsum(a.astype(np.uint16), axis=1).astype(np.uint8)
    return a


def read_psd_own(path):
    d = Path(path).read_bytes()
    r = _R(d)
    if r.take(4) != b"8BPS":
        raise ValueError("not a PSD file")
    ver = r.u("H")
    r.take(6)
    nch, h, w, depth, mode = r.u("HIIHH")
    if ver != 1 or depth != 8 or mode != 3:
        raise ValueError(f"own PSD reader handles 8-bit RGB PSD only (version {ver}, depth {depth}, mode {mode}); "
                         "install psd-tools for the rest")
    cm = r.u("I")
    r.p += cm  # colour mode data
    n = r.u("I")
    r.p += n  # image resources
    lm_len = r.u("I")
    lm_end = r.p + lm_len
    notes = []
    flat = []
    if lm_len:
        li_len = r.u("I")
        if li_len:
            count = abs(r.u("h"))
            for _ in range(count):
                top, left, bottom, right = r.u("4i")
                chans = [r.u("hI") for _ in range(r.u("H"))]
                r.take(4)
                key = r.take(4)
                opacity, clip, flags = r.u("BBB")
                r.take(1)
                xl = r.u("I")
                xend = r.p + xl
                ml = r.u("I")
                mask = None
                if ml >= 20:
                    mt, mlf, mb, mr = r.u("4i")
                    mdef, mflags = r.u("BB")
                    mask = (mt, mlf, mb, mr, mdef, mflags)
                    r.p += ml - 18
                else:
                    r.p += ml
                br = r.u("I")
                r.p += br  # blending ranges
                nl = r.u("B")
                name = r.take(nl).decode("latin-1")
                r.p += (-(nl + 1)) % 4
                info = {}
                while r.p + 12 <= xend:
                    sig = r.take(4)
                    if sig not in (b"8BIM", b"8B64"):
                        break
                    k = r.take(4)
                    ln = r.u("I")
                    info[k] = r.take(ln)
                r.p = xend
                if b"luni" in info:
                    cnt = struct.unpack_from(">I", info[b"luni"])[0]
                    name = info[b"luni"][4:4 + 2 * cnt].decode("utf-16-be")
                sect = info.get(b"lsct") or info.get(b"lsdk")
                flat.append({"name": name, "rect": (top, left, bottom, right), "chans": chans, "key": key,
                             "opacity": opacity / 255.0, "clip": clip == 1, "visible": not (flags & 2),
                             "mask": mask, "sect": sect})
            for L in flat:
                top, left, bottom, right = L["rect"]
                data = {}
                for cid, ln in L["chans"]:
                    raw = r.take(ln)
                    if cid == -2 and L["mask"]:
                        mt, mlf, mb, mr = L["mask"][:4]
                        data[cid] = _dec_channel(raw, mb - mt, mr - mlf)
                    elif cid >= -1:
                        data[cid] = _dec_channel(raw, bottom - top, right - left)
                L["data"] = data
    r.p = lm_end
    # tree from the flat bottom-first list
    root = []
    stack = [root]
    for L in flat:
        sect = L["sect"]
        stype = struct.unpack_from(">I", sect)[0] if sect else 0
        key = sect[8:12] if sect and len(sect) >= 12 else L["key"]
        if stype == 3:
            stack.append([])
            continue
        lay = Layer(L["name"], opacity=L["opacity"], blend=PSD_MODES.get(key, "normal"), visible=L["visible"],
                    clip=L["clip"])
        if PSD_MODES.get(key) is None:
            notes.append(f"layer {L['name']!r}: blend key {key!r} unknown, read as normal")
        if L["mask"] and -2 in L["data"]:
            mt, mlf, mb, mr, mdef, _ = L["mask"]
            lay.mask, lay.mask_x, lay.mask_y = L["data"][-2].astype(np.float32) / 255.0, mlf, mt
            lay.mask_default = mdef / 255.0
        if stype in (1, 2):
            lay.group = True
            lay.children = stack.pop() if len(stack) > 1 else []
            if lay.blend == "dissolve":
                lay.blend = "normal"
            stack[-1].append(lay)
            continue
        top, left, bottom, right = L["rect"]
        hh, ww = bottom - top, right - left
        px = np.zeros((max(hh, 0), max(ww, 0), 4), np.float32)
        for ch, cid in enumerate((0, 1, 2, -1)):
            if cid in L["data"] and L["data"][cid].shape == px.shape[:2]:
                px[..., ch] = L["data"][cid] / 255.0
            elif cid == -1:
                px[..., 3] = 1.0
        lay.px, lay.x, lay.y = px, left, top
        stack[-1].append(lay)
    if not flat:  # no layer section: the merged image is the only layer
        comp = r.u("H")
        notes.append("no layer records: merged image read as one layer")
        planes = []
        if comp == 0:
            for c in range(nch):
                planes.append(np.frombuffer(r.take(h * w), np.uint8).reshape(h, w))
        else:
            counts = r.u(f"{h * nch}H")
            counts = counts if isinstance(counts, tuple) else (counts,)
            for c in range(nch):
                rows = [np.frombuffer(unpackbits(r.take(counts[c * h + y]), w), np.uint8) for y in range(h)]
                planes.append(np.stack(rows))
        px = np.ones((h, w, 4), np.float32)
        for c in range(min(3, nch)):
            px[..., c] = planes[c] / 255.0
        root.append(Layer("Background", px))
    return Doc(w, h, root, notes)


# ---------------------------------------------------------------- PSD read (psd-tools, rung 2)
def read_psd_tools(path, psd_tools):
    psd = psd_tools.PSDImage.open(path)
    notes = []

    def conv(group):
        out = []
        for L in group:
            key = getattr(L.blend_mode, "value", b"norm")
            mode = PSD_MODES.get(key if isinstance(key, bytes) else str(key).encode(), "normal")
            lay = Layer(L.name, opacity=L.opacity / 255.0, blend=mode, visible=L.visible,
                        clip=bool(getattr(L, "clipping") if hasattr(type(L), "clipping")
                                  else getattr(L, "clipping_layer", False)))
            m = L.mask if L.has_mask() else None
            if m is not None and m.width and m.height:
                mi = m.topil()
                if mi is not None:
                    lay.mask = np.asarray(mi.convert("L"), np.float32) / 255.0
                    lay.mask_x, lay.mask_y = m.left, m.top
                    lay.mask_default = m.background_color / 255.0
            if L.is_group():
                lay.group = True
                lay.children = conv(L)
            else:
                if L.kind not in ("pixel", "shape", "smartobject", "type"):
                    notes.append(f"layer {L.name!r} ({L.kind}) not rendered: kept as empty pixels")
                im = L.topil() if L.width and L.height else None
                if im is None:
                    lay.px = np.zeros((0, 0, 4), np.float32)
                else:
                    lay.px = np.asarray(im.convert("RGBA"), np.float32) / 255.0
                    lay.x, lay.y = L.left, L.top
            out.append(lay)
        return out
    return Doc(psd.width, psd.height, conv(psd), notes)


# ---------------------------------------------------------------- ORA
def _png_bytes(a8, mode):
    b = io.BytesIO()
    Image.fromarray(a8, mode).save(b, "PNG")
    return b.getvalue()


def write_ora(doc, out, used, space="gamma"):
    flat = composite_doc(doc, space)
    files = {}
    counter = [0]

    def lay_el(lay):
        counter[0] += 1
        n = counter[0]
        attrs = {"name": lay.name, "opacity": f"{lay.opacity:.6f}", "visibility": "visible" if lay.visible else "hidden"}
        if lay.clip:
            attrs[f"{{{NS}}}clip"] = "1"
        if lay.mask is not None:
            mh, mw = lay.mask.shape
            files[f"data/{n:03d}-mask.png"] = _png_bytes(u8(lay.mask), "L")
            attrs.update({f"{{{NS}}}mask": f"data/{n:03d}-mask.png", f"{{{NS}}}mask-x": str(lay.mask_x),
                          f"{{{NS}}}mask-y": str(lay.mask_y), f"{{{NS}}}mask-default": f"{lay.mask_default:.6f}"})
        if lay.group:
            attrs["composite-op"] = ORA_OPS.get(lay.blend, "svg:src-over" if lay.blend == "pass" else f"phw:{lay.blend}")
            attrs["isolation"] = "auto" if lay.blend == "pass" else "isolate"
            if lay.blend == "pass":
                attrs[f"{{{NS}}}pass-through"] = "1"
            if lay.mask is not None:
                doc.notes.append(f"group mask on {lay.name!r} kept for phw only (ORA has no masks)")
            el = ET.Element("stack", attrs)
            for c in reversed(lay.children):
                el.append(lay_el(c))
            return el
        attrs["composite-op"] = ORA_OPS.get(lay.blend, f"phw:{lay.blend}")
        if lay.blend not in ORA_OPS:
            doc.notes.append(f"{lay.name!r}: {lay.blend} is not an ORA/SVG op; other apps read it as normal")
        px = lay.px.copy()
        if lay.mask is not None:
            files[f"data/{n:03d}-unmasked.png"] = _png_bytes(u8(px), "RGBA")
            attrs[f"{{{NS}}}unmasked"] = f"data/{n:03d}-unmasked.png"
            from .compose import place
            mh, mw = px.shape[:2]
            m = place(lay.mask, lay.mask_x - lay.x, lay.mask_y - lay.y, mw, mh, lay.mask_default)
            px[..., 3] *= m
        if px.size == 0:
            px = np.zeros((1, 1, 4), np.float32)
        files[f"data/{n:03d}.png"] = _png_bytes(u8(px), "RGBA")
        attrs.update({"src": f"data/{n:03d}.png", "x": str(lay.x), "y": str(lay.y)})
        return ET.Element("layer", attrs)

    image = ET.Element("image", {"version": "0.0.5", "w": str(doc.width), "h": str(doc.height)})
    root = ET.SubElement(image, "stack", {"isolation": "isolate"})
    for lay in reversed(doc.layers):
        root.append(lay_el(lay))
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(image, encoding="utf-8")
    merged = _png_bytes(u8(flat), "RGBA")
    th = Image.fromarray(u8(flat), "RGBA")
    th.thumbnail((256, 256))
    tb = io.BytesIO()
    th.save(tb, "PNG")
    with open(out, "xb") as f, zipfile.ZipFile(f, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), b"image/openraster", compress_type=zipfile.ZIP_STORED)
        z.writestr("stack.xml", xml, compress_type=zipfile.ZIP_DEFLATED)
        for k, v in files.items():
            z.writestr(k, v, compress_type=zipfile.ZIP_STORED)
        z.writestr("mergedimage.png", merged, compress_type=zipfile.ZIP_STORED)
        z.writestr("Thumbnails/thumbnail.png", tb.getvalue(), compress_type=zipfile.ZIP_STORED)
    used.add("save ora", 1, "own OpenRaster writer")
    return out


def read_ora(path):
    notes = []
    with zipfile.ZipFile(path) as z:
        if z.read("mimetype").strip() != b"image/openraster":
            raise ValueError("not an OpenRaster file")
        image = ET.fromstring(z.read("stack.xml"))

        def png(name, mode):
            with Image.open(io.BytesIO(z.read(name))) as im:
                return np.asarray(im.convert(mode), np.float32) / 255.0

        def g(el, k, d=None):
            return el.get(f"{{{NS}}}{k}", d)

        def conv(el):
            name = el.get("name", "")
            op = el.get("composite-op", "svg:src-over")
            mode = ORA_MODES.get(op) or (op[4:] if op.startswith("phw:") else None)
            if mode is None:
                notes.append(f"{name!r}: composite-op {op} unknown, read as normal")
                mode = "normal"
            lay = Layer(name, opacity=float(el.get("opacity", 1)), visible=el.get("visibility", "visible") != "hidden",
                        clip=g(el, "clip") == "1", blend=mode)
            if g(el, "mask"):
                lay.mask = png(g(el, "mask"), "L")
                lay.mask_x, lay.mask_y = int(g(el, "mask-x", 0)), int(g(el, "mask-y", 0))
                lay.mask_default = float(g(el, "mask-default", 0))
            if el.tag == "stack":
                lay.group = True
                if g(el, "pass-through") == "1" or (el.get("isolation", "auto") == "auto" and mode == "normal"):
                    lay.blend = "pass"
                lay.children = [conv(c) for c in reversed(list(el)) if c.tag in ("stack", "layer")]
                return lay
            lay.px = png(g(el, "unmasked") or el.get("src"), "RGBA")
            lay.x, lay.y = int(float(el.get("x", 0))), int(float(el.get("y", 0)))
            return lay
        top = image.find("stack")
        layers = [conv(c) for c in reversed(list(top)) if c.tag in ("stack", "layer")]
    return Doc(int(image.get("w")), int(image.get("h")), layers, notes)


# ---------------------------------------------------------------- dispatch
def read_layered(path, used):
    ext = Path(path).suffix.lower()
    if ext == ".ora":
        used.add("open ora", 1, "own OpenRaster reader")
        return read_ora(path)
    if ext in (".psd", ".psb"):
        pt = probe("psd_tools")
        if pt is not None:
            used.add("open psd", 2, "psd-tools")
            return read_psd_tools(path, pt)
        used.add("open psd", 1, "own PSD reader (8-bit RGB raster, masks, groups)")
        return read_psd_own(path)
    if ext == ".json":
        r = json.loads(Path(path).read_text(encoding="utf-8"))
        if r.get("kind") != "layers":
            raise ValueError(f"{path} is not a layers recipe")
        return doc_from_recipe(r, Path(path).parent, used)
    used.add("open", 1, "Pillow (flat image as one layer)")
    from .compose import rgba
    img = core.load(path)
    return Doc(img.px.shape[1], img.px.shape[0], [Layer(Path(path).stem, rgba(img))], img.notes, img.icc)


WRITERS = {".psd": write_psd, ".ora": write_ora}


def gimp_layers(path, timeout=240):
    """Open a file in GIMP 3 (batch, no UI) and return its layer tree as GIMP reads it, top first."""
    exe = core.gimp_console()
    if not exe:
        return None
    td = Path(tempfile.mkdtemp(prefix="phw-gimp-"))
    out = td / "layers.json"
    script = td / "probe.py"
    script.write_text(
        "import json\nfrom gi.repository import Gimp, Gio\n"
        "def walk(ls, d, out):\n"
        "    for l in ls:\n"
        "        g = l.is_group()\n"
        "        out.append({'name': l.get_name(), 'opacity': l.get_opacity(), 'mode': l.get_mode().value_nick,\n"
        "                    'mask': l.get_mask() is not None, 'group': g, 'depth': d, 'visible': l.get_visible()})\n"
        "        if g:\n"
        "            walk(l.get_children(), d + 1, out)\n"
        f"img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path({str(Path(path).resolve())!r}))\n"
        "out = []\nwalk(img.get_layers(), 0, out)\n"
        f"open({str(out)!r}, 'w', encoding='utf-8').write(json.dumps(out))\n", encoding="utf-8")
    cmd = [exe, "-i", "-d", "-f", "--no-shm", "--batch-interpreter", "python-fu-eval",
           "-b", f"exec(open({str(script)!r}, encoding='utf-8').read())", "--quit"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    if not out.exists():
        raise RuntimeError(f"GIMP wrote no layer list (exit {p.returncode}): {(p.stderr or p.stdout)[-800:]}")
    return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- commands
def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:40] or "layer"


def extract(doc, folder):
    """Write each layer (and mask) as PNG plus a layers recipe that rebuilds the document."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    n = [0]

    def spec(lay):
        n[0] += 1
        s = {"name": lay.name, "opacity": lay.opacity, "blend": lay.blend, "visible": lay.visible, "clip": lay.clip}
        stem = f"{n[0]:03d}-{_safe(lay.name)}"
        if lay.mask is not None:
            mp = free_path(folder / f"{stem}-mask.png")
            Image.fromarray(u8(lay.mask), "L").save(mp)
            s["mask"] = {"file": mp.name, "x": lay.mask_x, "y": lay.mask_y, "default": lay.mask_default}
        if lay.group:
            s.update(type="group", layers=[spec(c) for c in lay.children])
            return s
        px = lay.px if lay.px.size else np.zeros((1, 1, 4), np.float32)
        fp = free_path(folder / f"{stem}.png")
        Image.fromarray(u8(px), "RGBA").save(fp)
        s.update(type="image", file=fp.name, x=lay.x, y=lay.y)
        return s
    r = {"version": 1, "kind": "layers", "canvas": {"width": doc.width, "height": doc.height},
         "space": "gamma", "layers": [spec(l) for l in doc.layers]}
    rp = free_path(folder / "layers.json")
    rp.write_text(json.dumps(r, indent=1), encoding="utf-8")
    return rp


def cmd_open(a):
    used = Used()
    doc = read_layered(a.input, used)
    r = {"command": "open", "input": str(a.input), **doc.info(), "rung": used.rung(), "tool": used.tool(),
         "used": used.items, "notes": doc.notes}
    if a.extract:
        r["recipe"] = str(extract(doc, a.extract))
    if a.gimp:
        g = gimp_layers(a.input)
        r["gimp"] = g if g is not None else "GIMP 3 not found (gimp-console)"
    return r


def cmd_save(a):
    t0 = time.time()
    used = Used()
    doc = read_layered(a.input, used)
    out = free_path(Path(a.output))
    if out.resolve() == Path(a.input).resolve():
        raise RuntimeError("refusing to write over the source")
    space = "gamma"
    if Path(a.input).suffix.lower() == ".json":
        space = json.loads(Path(a.input).read_text(encoding="utf-8")).get("space", "gamma")
    if out.suffix.lower() == ".psd":
        write_psd(doc, out, used, space, a.psd_compression)
    else:
        write_doc(doc, out, used, space)
    log_line(out.parent / "log.jsonl", ["save"], out, used, time.time() - t0, {"input": str(a.input)}) if a.log else None
    return {"command": "save", "input": str(a.input), "output": str(out), "layers": doc.info()["count"],
            "rung": used.rung(), "tool": used.tool(), "used": used.items, "notes": doc.notes}


def add_commands(sub, edit):
    p = sub.add_parser("open", help="read a layered file (.psd, .ora, layers recipe): tree, extract, GIMP check")
    p.add_argument("input")
    p.add_argument("--extract", help="folder: write each layer and mask as PNG plus layers.json")
    p.add_argument("--gimp", action="store_true", help="also open it in GIMP 3 (batch) and list what GIMP sees")
    p.set_defaults(fn=cmd_open)
    p = sub.add_parser("save", help="write a layered file: .psd/.ora/.json recipe in, .psd/.ora/.png out")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True, help="output .psd, .ora or flat image (never overwritten)")
    p.add_argument("--psd-compression", choices=("rle", "raw"), default="rle")
    p.add_argument("--log", action="store_true", help="append a line to log.jsonl next to the output")
    p.set_defaults(fn=cmd_save)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "ORA read/write": (1, "own OpenRaster code"),
    "PSD write": (1, "own PSD writer (8-bit RGB, masks, groups)"),
    "PSD read": (2, "psd-tools") if probe("psd_tools") else (1, "own minimal PSD reader"),
    "GIMP check": (2, core.gimp_console() or "GIMP 3 not found"),
})
