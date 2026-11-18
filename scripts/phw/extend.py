"""Batch 16 (0.17.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

caextend: Content-Aware Extend: copy a rectangle to an offset, keep the source where it was, and
          blend the copy into its new place in the gradient domain (Poisson) so no seam shows.
indexed:  Indexed Color / Save for Web palette: palette (own median cut via Pillow, web 216, grey,
          a .hex/.gpl file or a colour list) with a dither choice (none, Floyd-Steinberg, ordered
          Bayer 2/4/8, seeded noise); writes an 8-bit palette PNG (or GIF).
shake:    Shake Reduction for a known straight blur trace (Richardson-Lucy, line PSF).
Satin is in fills.op_layerstyle (`layerstyle --satin`).
Own NumPy and Pillow only.
"""
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import core, retouch
from .core import OPS, floats
from .grading import with_mask


# ---------------------------------------------------------------- content-aware extend
def op_caextend(img, p, used):
    """The source rect stays bit for bit. The destination rect gets the patch: inside it, the
    gradients of the patch; on its border ring, the image as it was (Perez et al. 2003). blend
    'none' pastes the patch bit for bit instead. Pixels outside the destination never change."""
    x, y, rw, rh = (int(round(v)) for v in p["rect"])
    dx, dy = (int(round(v)) for v in p["offset"])
    c = img.color()
    h, w = c.shape[:2]
    if not (0 <= x and 0 <= y and x + rw <= w and y + rh <= h):
        raise ValueError(f"caextend: rect {p['rect']} outside the image {w}x{h}")
    nx0, ny0 = max(0, x + dx), max(0, y + dy)
    nx1, ny1 = min(w, x + dx + rw), min(h, y + dy + rh)
    if nx1 <= nx0 or ny1 <= ny0:
        raise ValueError("caextend: the destination is outside the image")
    patch = c[ny0 - dy:ny1 - dy, nx0 - dx:nx1 - dx].copy()
    guide = c.copy()
    guide[ny0:ny1, nx0:nx1] = patch
    if p.get("blend", "poisson") == "none":
        used.add("caextend", 1, "own copy, no blend")
        return img.with_color(guide)
    hole = np.zeros((h, w), bool)
    hole[ny0 + 1:ny1 - 1, nx0 + 1:nx1 - 1] = True  # the ring keeps the image: the Poisson border
    if not hole.any():
        used.add("caextend", 1, "own copy (rect too small to blend)")
        return img.with_color(guide)
    f, _ = retouch.poisson_solve(c, guide, hole)
    out = np.where(hole[..., None], np.clip(f, 0, 1), c).astype(np.float32)
    used.add("caextend", 1, "own copy + Poisson (gradient-domain) blend")
    return img.with_color(out)


def cmd_caextend(a):
    p = {"rect": floats(a.rect, 4), "offset": floats(a.to, 2), "blend": a.blend}
    return core.edit_command(a, "caextend", with_mask(a, [{"op": "caextend", "params": p}]))


OPS.update({"caextend": op_caextend})


# ---------------------------------------------------------------- shake reduction
def motion_psf(length, angle):
    """Normalised line PSF of `length` px at `angle` degrees (anti-aliased by 4x supersampling)."""
    L = max(1.0, float(length))
    r = int(np.ceil(L / 2)) + 1
    k = np.zeros((2 * r + 1, 2 * r + 1))
    a = np.radians(float(angle))
    for t in np.linspace(-L / 2, L / 2, int(L * 4) + 1):
        x, y = r + t * np.cos(a), r - t * np.sin(a)
        x0, y0 = int(np.floor(x)), int(np.floor(y))
        fx, fy = x - x0, y - y0
        for yy, xx, wgt in ((y0, x0, (1 - fx) * (1 - fy)), (y0, x0 + 1, fx * (1 - fy)),
                            (y0 + 1, x0, (1 - fx) * fy), (y0 + 1, x0 + 1, fx * fy)):
            k[yy, xx] += wgt
    return k / k.sum()


def fft_conv(img, otf):
    return np.real(np.fft.ifft2(np.fft.fft2(img) * otf))


def op_shake(img, p, used):
    """Shake Reduction with a known straight blur trace: Richardson-Lucy deconvolution (FFT,
    edge-padded by reflection so the frame does not ring), `iterations` steps."""
    c = img.color().astype(np.float64)
    h, w = c.shape[:2]
    k = motion_psf(p["length"], p.get("angle", 0))
    pad = k.shape[0]
    out = np.empty_like(c)
    for ch in range(c.shape[2]):
        f = np.pad(c[..., ch], pad, mode="reflect")
        H, W = f.shape
        kp = np.zeros((H, W))
        kp[:k.shape[0], :k.shape[1]] = k
        kp = np.roll(kp, (-(k.shape[0] // 2), -(k.shape[1] // 2)), axis=(0, 1))
        otf = np.fft.fft2(kp)
        est = np.full_like(f, max(f.mean(), 1e-6))
        obs = np.maximum(f, 1e-6)
        for _ in range(int(p.get("iterations", 30))):
            ratio = obs / np.maximum(fft_conv(est, otf), 1e-6)
            est *= fft_conv(ratio, np.conj(otf))
        out[..., ch] = est[pad:pad + h, pad:pad + w]
    used.add("shake", 1, f"own Richardson-Lucy, {int(p.get('iterations', 30))} iterations, line PSF")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def cmd_shake(a):
    p = {"length": a.length, "angle": a.angle, "iterations": a.iterations}
    return core.edit_command(a, "shake", with_mask(a, [{"op": "shake", "params": p}]))


OPS.update({"shake": op_shake})


# ---------------------------------------------------------------- indexed colour
BAYER2 = np.array([[0, 2], [3, 1]], float)


def bayer(n):
    m = BAYER2
    while m.shape[0] < n:
        k = m.shape[0]
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return (m + 0.5) / m.size  # thresholds in (0, 1), mean 0.5


def web_palette():
    v = np.arange(0, 256, 51)
    return np.array([[r, g, b] for r in v for g in v for b in v], float)


def read_palette(spec, rgb, n):
    """spec: None/'auto' (median cut to n), 'web', 'gray', a .hex/.gpl file or '#rrggbb #rrggbb ...'."""
    if spec in (None, "", "auto"):
        im = Image.fromarray(rgb).quantize(colors=int(n), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        used_idx = sorted({i for _, i in im.getcolors(256 * 256)})
        return np.array(im.getpalette(), float).reshape(-1, 3)[used_idx], "median cut (Pillow)"
    if spec == "web":
        return web_palette(), "web 216"
    if spec == "gray":
        return np.linspace(0, 255, int(n))[:, None].repeat(3, 1).round(), f"grey {int(n)}"
    path = Path(spec)
    if path.suffix.lower() in (".hex", ".gpl", ".txt") and path.exists():
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            t = line.strip()
            if path.suffix.lower() == ".gpl":
                parts = t.split()
                if len(parts) >= 3 and all(s.isdigit() for s in parts[:3]):
                    rows.append([int(s) for s in parts[:3]])
            elif t and not t.startswith(";"):
                t = t.lstrip("#")
                if len(t) >= 6:
                    rows.append([int(t[i:i + 2], 16) for i in (0, 2, 4)])
        return np.array(rows, float), f"file {path.name}"
    cols = [s.lstrip("#") for s in spec.replace(",", " ").split()]
    return np.array([[int(t[i:i + 2], 16) for i in (0, 2, 4)] for t in cols], float), "list"


def nearest(rgb, pal):
    """Index of the nearest palette colour (squared RGB distance), chunked to bound memory."""
    flat = rgb.reshape(-1, 3)
    out = np.empty(len(flat), np.int32)
    for s in range(0, len(flat), 65536):
        d = ((flat[s:s + 65536, None, :] - pal[None]) ** 2).sum(-1)
        out[s:s + 65536] = d.argmin(1)
    return out.reshape(rgb.shape[:2])


def spread(pal):
    """Mean distance from each palette colour to its nearest neighbour (per channel scale)."""
    if len(pal) < 2:
        return 0.0
    d = np.sqrt(((pal[:, None] - pal[None]) ** 2).sum(-1))
    d[d == 0] = np.inf
    return float(np.median(d.min(1)) / np.sqrt(3))


def floyd(rgb, pal):
    """Serpentine Floyd-Steinberg error diffusion, row-vectorised where the order allows it."""
    h, w = rgb.shape[:2]
    work = rgb.astype(np.float64).copy()
    idx = np.zeros((h, w), np.int32)
    for yy in range(h):
        xs = range(w) if yy % 2 == 0 else range(w - 1, -1, -1)
        s = 1 if yy % 2 == 0 else -1
        row, nxt = work[yy], work[yy + 1] if yy + 1 < h else None
        for xx in xs:
            v = row[xx]
            k = int(((pal - v) ** 2).sum(1).argmin())
            idx[yy, xx] = k
            e = v - pal[k]
            if 0 <= xx + s < w:
                row[xx + s] += e * 7 / 16
            if nxt is not None:
                if 0 <= xx - s < w:
                    nxt[xx - s] += e * 3 / 16
                nxt[xx] += e * 5 / 16
                if 0 <= xx + s < w:
                    nxt[xx + s] += e * 1 / 16
    return idx


def to_indexed(rgb, alpha, pal, dither="none", size=8, seed=0, strength=1.0):
    rgb = rgb.astype(np.float64)
    h, w = rgb.shape[:2]
    if dither == "none":
        idx = nearest(rgb, pal)
    elif dither == "floyd":
        idx = floyd(rgb, pal)
    elif dither in ("ordered", "noise"):
        if dither == "ordered":
            m = bayer(int(size))
            t = np.tile(m, (h // m.shape[0] + 1, w // m.shape[1] + 1))[:h, :w]
        else:
            t = np.random.default_rng(int(seed)).random((h, w))
        idx = nearest(rgb + ((t - 0.5) * spread(pal) * float(strength))[..., None], pal)
    else:
        raise ValueError(f"indexed: unknown dither {dither}")
    trans = None
    if alpha is not None and (alpha < 0.5).any():
        idx = idx + 1  # index 0 is the transparent entry
        idx[alpha < 0.5] = 0
        pal = np.vstack([[0, 0, 0], pal])
        trans = 0
    return idx, pal, trans


def cmd_indexed(a):
    t0 = time.time()
    used = core.Used()
    img = core.load(a.input, used)
    c = img.color()
    rgb = np.repeat(c, 3, axis=2) if c.shape[2] == 1 else c[..., :3]
    rgb8 = np.clip(np.round(rgb * 255), 0, 255).astype(np.uint8)
    alpha = img.px[..., -1] if img.alpha else None
    pal, how = read_palette(a.palette, rgb8, a.colors)
    if len(pal) == 0 or len(pal) > 256 - (1 if alpha is not None else 0):
        raise SystemExit(f"indexed: palette has {len(pal)} colours; 1..255 (256 when opaque) allowed")
    idx, pal_out, trans = to_indexed(rgb8, alpha, pal, a.dither, a.size, a.seed, a.strength)
    out = core.out_for(a.input, a.output, "indexed", ".gif" if a.gif else ".png")
    im = Image.fromarray(idx.astype(np.uint8), "P")
    im.putpalette([int(v) for v in pal_out.astype(int).ravel()])
    kw = {"transparency": trans} if trans is not None else {}
    im.save(out, optimize=False, **kw)
    used.add("indexed", 1, f"own NumPy palette map ({how}), dither {a.dither}")
    return {"command": "indexed", "input": str(a.input), "output": str(out), "palette": how,
            "colors": int(len(pal)), "colors_used": int(len(np.unique(idx))), "dither": a.dither,
            "transparent_index": trans, "seconds": round(time.time() - t0, 3), "rung": used.rung(),
            "tool": used.tool(), "used": used.items}


def add_commands(sub, edit):
    p = edit("caextend", cmd_caextend, "Content-Aware Extend: copy a rect, blend it in at an offset (rung 1)")
    p.add_argument("--rect", required=True, help="x,y,width,height to copy")
    p.add_argument("--to", required=True, help="dx,dy offset")
    p.add_argument("--blend", choices=("poisson", "none"), default="poisson")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("shake", cmd_shake, "Shake Reduction: undo a straight camera-shake blur (rung 1)")
    p.add_argument("--length", type=float, required=True, help="blur trace length in px")
    p.add_argument("--angle", type=float, default=0.0, help="trace angle in degrees")
    p.add_argument("--iterations", type=int, default=30)
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = sub.add_parser("indexed", help="Indexed Color: palette PNG/GIF with a dither choice (rung 1)")
    p.add_argument("input")
    p.add_argument("-o", "--output")
    p.add_argument("--palette", default="auto", help="auto (median cut), web, gray, a .hex/.gpl file, or '#rrggbb ...'")
    p.add_argument("--colors", type=int, default=256, help="palette size for auto and gray")
    p.add_argument("--dither", choices=("none", "floyd", "ordered", "noise"), default="none")
    p.add_argument("--size", type=int, choices=(2, 4, 8), default=8, help="Bayer matrix size for ordered")
    p.add_argument("--strength", type=float, default=1.0, help="ordered/noise amplitude, x palette spacing")
    p.add_argument("--seed", type=int, default=0, help="noise dither seed")
    p.add_argument("--gif", action="store_true", help="write .gif instead of .png")
    p.set_defaults(fn=cmd_indexed)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {"caextend, shake, indexed, layerstyle --satin": (1, "own NumPy + Pillow")})
