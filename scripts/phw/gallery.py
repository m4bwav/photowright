"""Batch 13 (0.14.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

blurgallery: Tilt-Shift (sharp band, linear ramp to a full Gaussian) and Field Blur (pins with a sigma
             each, inverse-distance-squared blend of the per-sigma Gaussians).
fibers:      seeded vertical fibres between a foreground and background colour (Render > Fibers).
deinterlace: drop the odd or even field, refill by duplication or interpolation.
ntsc:        limit YIQ chroma so the composite signal Y +- C stays in broadcast range (NTSC Colors).
liquify --mode twirl|pucker|bloat: brush warps around each stroke point (push stays in kernels.py).
Own NumPy only; ops keep alpha, take --mask and --recipe and replay through `phw run`.
"""
import math

import numpy as np

from . import core, transform
from .core import OPS, floats
from .grading import with_mask

YIQ = np.array([[0.299, 0.587, 0.114], [0.596, -0.274, -0.322], [0.211, -0.523, 0.312]])


def blur_all(c, sigma, used):
    if sigma <= 0:
        return c.copy()
    return np.stack([core.gaussian_blur(c[..., i], sigma, used) for i in range(c.shape[2])], axis=2)


def hexcol(s):
    h = s.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


# ---------------------------------------------------------------- blur gallery
def op_tilt(img, p, used):
    """t = clip((d - half) / ramp, 0, 1) with d the distance from the band's centre line (through the
    image centre column at `angle` degrees); out = src (1 - t) + gaussian(sigma) t. Band pixels are
    the source unchanged; beyond the ramp the full blur."""
    c = img.color()
    h, w = c.shape[:2]
    y0, y1 = float(p["y0"]), float(p["y1"])
    ramp, a = max(1e-6, float(p.get("ramp", 20))), math.radians(float(p.get("angle", 0)))
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
    cy, cx, half = (y0 + y1) / 2, (w - 1) / 2, abs(y1 - y0) / 2
    d = np.abs(-(X - cx) * math.sin(a) + (Y - cy) * math.cos(a))
    t = np.clip((d - half) / ramp, 0, 1)[..., None].astype(np.float32)
    b = blur_all(c, float(p["sigma"]), used)
    out = np.where(t > 0, c * (1 - t) + b * t, c)
    used.add("blurgallery.tilt", 1, "own tilt-shift ramp over a Gaussian")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_field(img, p, used):
    """Each pin (x, y, sigma) blurs the image with its sigma; the output mixes those blurs with
    weights 1 / d^2 (normalised), so a pin's own pixel is its blur."""
    pins = np.asarray(p["pins"], np.float64).reshape(-1, 3)
    c = img.color()
    h, w = c.shape[:2]
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
    W = np.stack([1.0 / np.maximum((X - x) ** 2 + (Y - y) ** 2, 1e-12) for x, y, _ in pins])
    W /= W.sum(0)
    out = np.zeros_like(c, dtype=np.float64)
    cache = {}
    for i, (_, _, s) in enumerate(pins):
        if s not in cache:
            cache[s] = blur_all(c, float(s), used)
        out += W[i][..., None] * cache[s]
    used.add("blurgallery.field", 1, "own field blur (inverse-distance mix of Gaussians)")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- fibers
def sep_blur(a, sy, sx):
    for axis, s in ((0, sy), (1, sx)):
        if s <= 0:
            continue
        k, r = core.gaussian_kernel(s)
        pad = [(r, r) if i == axis else (0, 0) for i in (0, 1)]
        pp = np.pad(a, pad, mode="wrap")
        a = sum(k[j] * (pp[j:j + a.shape[0]] if axis == 0 else pp[:, j:j + a.shape[1]]) for j in range(len(k)))
    return a


def op_fibers(img, p, used):
    """Seeded noise blurred with sigma `strength` down the columns and 0.6 px across, stretched to
    0..1 by its own 1st-99th percentile (variance sets the contrast), then mixed bg -> fg."""
    h, w = img.px.shape[:2]
    rng = np.random.default_rng(int(p.get("seed", 0)))
    v = sep_blur(rng.standard_normal((h, w)), float(p.get("strength", 8)), 0.6)
    lo, hi = np.percentile(v, [1, 99])
    v = (v - lo) / max(1e-9, hi - lo)
    var = float(p.get("variance", 16)) / 16.0
    v = np.clip(0.5 + (v - 0.5) * var, 0, 1)[..., None]
    fg, bg = np.asarray(p.get("fg", [0, 0, 0])), np.asarray(p.get("bg", [1, 1, 1]))
    out = bg + (fg - bg) * v
    c = img.color().copy()
    c[..., :3] = out
    used.add("fibers", 1, "own seeded anisotropic noise")
    return img.with_color(np.clip(c, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- de-interlace
def op_deinterlace(img, p, used):
    """Drop the odd (rows 1, 3, ...) or even field; refill each dropped row from the kept neighbour
    (dup) or the mean of the two kept neighbours (interp; edge rows duplicate)."""
    c = img.color().copy()
    h = c.shape[0]
    first = 1 if p.get("field", "odd") == "odd" else 0
    for i in range(first, h, 2):
        up, dn = i - 1, i + 1
        nb = [r for r in (up, dn) if 0 <= r < h]
        if p.get("fill", "interp") == "interp" and len(nb) == 2:
            c[i] = (c[up] + c[dn]) / 2
        else:
            c[i] = c[up if up >= 0 else dn]
    used.add("deinterlace", 1, "own field drop and refill")
    return img.with_color(c.astype(np.float32))


# ---------------------------------------------------------------- NTSC colors
def op_ntsc(img, p, used):
    """YIQ: keep Y, scale chroma C = |I, Q| down so Y + C <= hi and Y - C >= lo (composite limits,
    defaults 1.1 and -0.2, about 120 and -20 IRE). Pixels already inside are returned unchanged."""
    hi, lo = float(p.get("hi", 1.1)), float(p.get("lo", -0.2))
    c = img.color()
    rgb = c[..., :3].astype(np.float64)
    yiq = rgb @ YIQ.T
    Y, C = yiq[..., 0], np.hypot(yiq[..., 1], yiq[..., 2])
    lim = np.minimum(hi - Y, Y - lo).clip(0)
    s = np.where(C > lim, lim / np.maximum(C, 1e-12), 1.0)
    yiq[..., 1:] *= s[..., None] * 0.999
    back = np.clip(yiq @ np.linalg.inv(YIQ).T, 0, 1)
    out = c.copy()
    out[..., :3] = np.where((s < 1)[..., None], back, rgb)
    used.add("ntsc", 1, "own YIQ chroma limit")
    return img.with_color(out.astype(np.float32))


# ---------------------------------------------------------------- liquify brushes
def op_liquify_brush(img, p, used):
    """Backward-mapped brush at each point: falloff f = (1 - d^2/r^2)^2 inside r, 0 outside.
    twirl rotates the sample point by strength x f radians (x pi); pucker samples from farther out
    (content pulled in), bloat from nearer the centre (content pushed out)."""
    pts = np.asarray(p["points"], np.float64).reshape(-1, 2)
    r, s, mode = float(p["radius"]), float(p.get("strength", 0.5)), p["mode"]
    h, w = img.px.shape[:2]
    if s == 0:
        used.add("liquify", 1, "identity (strength 0)")
        return img.copy()
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
    SX, SY = X.copy(), Y.copy()
    for cx, cy in pts:
        dx, dy = SX - cx, SY - cy
        f = np.clip(1 - (dx * dx + dy * dy) / (r * r), 0, 1) ** 2
        if mode == "twirl":
            a = -s * math.pi * f
            ca, sa = np.cos(a), np.sin(a)
            SX, SY = cx + dx * ca - dy * sa, cy + dx * sa + dy * ca
        else:
            k = 1 + s * f if mode == "pucker" else 1 - s * f * 0.9
            SX, SY = cx + dx * k, cy + dy * k
    used.add("liquify", 1, f"own {mode} brush + transform.remap")
    return transform.remap(img, np.clip(SX, 0, w - 1).astype(np.float32),
                           np.clip(SY, 0, h - 1).astype(np.float32), used, "liquify")


OPS.update({"blurgallery.tilt": op_tilt, "blurgallery.field": op_field, "fibers": op_fibers,
            "deinterlace": op_deinterlace, "ntsc": op_ntsc, "liquify.brush": op_liquify_brush})


# ---------------------------------------------------------------- commands
def cmd_blurgallery(a):
    steps = []
    if a.tilt:
        y0, y1 = floats(a.tilt, 2)
        steps.append({"op": "blurgallery.tilt", "params": {"y0": y0, "y1": y1, "ramp": a.ramp, "sigma": a.sigma,
                                                           "angle": a.angle}})
    if a.field:
        steps.append({"op": "blurgallery.field",
                      "params": {"pins": [floats(t, 3) for t in a.field.replace(";", " ").split()]}})
    if not steps:
        raise SystemExit("blurgallery: give --tilt or --field")
    return core.edit_command(a, "blurgallery", with_mask(a, steps))


def cmd_fibers(a):
    p = {"variance": a.variance, "strength": a.strength, "seed": a.seed, "fg": hexcol(a.fg), "bg": hexcol(a.bg)}
    return core.edit_command(a, "fibers", with_mask(a, [{"op": "fibers", "params": p}]))


def cmd_deinterlace(a):
    return core.edit_command(a, "deinterlace", with_mask(a, [{"op": "deinterlace",
                                                             "params": {"field": a.field, "fill": a.fill}}]))


def cmd_ntsc(a):
    return core.edit_command(a, "ntsc", with_mask(a, [{"op": "ntsc", "params": {"hi": a.hi, "lo": a.lo}}]))


def add_commands(sub, edit):
    p = edit("blurgallery", cmd_blurgallery, "Blur Gallery: tilt-shift band, field blur pins (rung 1)")
    p.add_argument("--tilt", help="Y0,Y1 sharp band (rows through the centre line)")
    p.add_argument("--ramp", type=float, default=20.0, help="px from the band edge to full blur")
    p.add_argument("--sigma", type=float, default=6.0, help="full blur sigma")
    p.add_argument("--angle", type=float, default=0.0, help="band angle in degrees")
    p.add_argument("--field", help="'x,y,sigma x,y,sigma ...' pins")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("fibers", cmd_fibers, "Render Fibers: seeded vertical fibres between --fg and --bg (rung 1)")
    p.add_argument("--variance", type=float, default=16.0, help="contrast (16 = full range)")
    p.add_argument("--strength", type=float, default=8.0, help="fibre length (vertical sigma, px)")
    p.add_argument("--fg", default="#000000")
    p.add_argument("--bg", default="#ffffff")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("deinterlace", cmd_deinterlace, "De-Interlace: drop a field, refill by dup or interp (rung 1)")
    p.add_argument("--field", choices=("odd", "even"), default="odd", help="field to eliminate")
    p.add_argument("--fill", choices=("dup", "interp"), default="interp")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("ntsc", cmd_ntsc, "NTSC Colors: limit YIQ chroma to broadcast composite range (rung 1)")
    p.add_argument("--hi", type=float, default=1.1, help="max Y + C (about 120 IRE)")
    p.add_argument("--lo", type=float, default=-0.2, help="min Y - C (about -20 IRE)")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "blurgallery (tilt-shift, field), fibers, deinterlace, ntsc, liquify twirl/pucker/bloat": (1, "own NumPy"),
})
