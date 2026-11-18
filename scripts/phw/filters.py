"""Batch 8 (0.9.0): rung 1 filters and colour maps from the coverage table (references/photoshop-feature-map.md).

filter: Gaussian, Box and Motion Blur, High Pass, Maximum/Minimum, Offset.
color:  Invert, Posterize, Threshold, Solarize, Channel Mixer, Gradient Map.
All work on encoded values (as Photoshop filters do by default), keep alpha, take --mask and --recipe,
and replay through `phw run` like every other op.
"""
import math

import numpy as np

from . import core
from .core import OPS, floats

REC601 = np.array([0.299, 0.587, 0.114], np.float32)


# ---------------------------------------------------------------- spatial helpers (NumPy only)
def box_blur(ch, r):
    """Mean over a (2r+1)^2 window via a summed-area table, edges reflected."""
    p = np.pad(ch.astype(np.float64), r, mode="symmetric")
    s = np.pad(p.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    k = 2 * r + 1
    h, w = ch.shape
    tot = s[k:k + h, k:k + w] - s[:h, k:k + w] - s[k:k + h, :w] + s[:h, :w]
    return (tot / (k * k)).astype(np.float32)


def motion_kernel(length, angle):
    """Line kernel: `length` px long at `angle` degrees counter-clockwise, sampled with
    bilinear weights at unit steps, normalised to sum 1."""
    n = max(1, int(round(length)))
    t = np.linspace(-(n - 1) / 2, (n - 1) / 2, n)
    a = math.radians(angle)
    xs, ys = t * math.cos(a), -t * math.sin(a)
    r = int(math.ceil(max(np.abs(xs).max(), np.abs(ys).max()))) + 1
    k = np.zeros((2 * r + 1, 2 * r + 1), np.float64)
    for x, y in zip(xs + r, ys + r):
        x0, y0 = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - x0, y - y0
        for dy, wy in ((0, 1 - fy), (1, fy)):
            for dx, wx in ((0, 1 - fx), (1, fx)):
                if wx * wy > 0:
                    k[y0 + dy, x0 + dx] += wx * wy
    return (k / k.sum()).astype(np.float32)


def convolve(ch, k):
    r = k.shape[0] // 2
    p = np.pad(ch, r, mode="symmetric")
    h, w = ch.shape
    out = np.zeros_like(ch, np.float32)
    for (y, x), v in np.ndenumerate(k):
        if v:
            out += v * p[y:y + h, x:x + w]
    return out


def rank(ch, r, fn):
    """Grey dilation (np.maximum) or erosion (np.minimum) over a (2r+1)^2 square, separable."""
    out = ch
    for axis in (0, 1):
        pad = [(r, r) if a == axis else (0, 0) for a in (0, 1)]
        p = np.pad(out, pad, mode="edge")
        n = out.shape[axis]
        acc = p[:n] if axis == 0 else p[:, :n]
        for i in range(1, 2 * r + 1):
            acc = fn(acc, p[i:i + n] if axis == 0 else p[:, i:i + n])
        out = acc
    return out


def per_channel(img, fn):
    c = img.color()
    return img.with_color(np.stack([fn(c[..., i]) for i in range(c.shape[2])], axis=2))


# ---------------------------------------------------------------- ops
def op_blur(img, p, used):
    kind, r = p.get("kind", "gaussian"), float(p.get("radius", 2.0))
    if kind == "gaussian":
        res = per_channel(img, lambda ch: core.gaussian_blur(ch, r, used))
        used.add("filter.blur", used.items[-1]["rung"], "Gaussian blur")
    elif kind == "box":
        res = per_channel(img, lambda ch: box_blur(ch, int(round(r))))
        used.add("filter.blur", 1, "NumPy box blur (summed-area table)")
    elif kind == "motion":
        k = motion_kernel(r, p.get("angle", 0.0))
        res = per_channel(img, lambda ch: convolve(ch, k))
        used.add("filter.blur", 1, "NumPy motion blur (line kernel)")
    else:
        raise ValueError(f"unknown blur kind {kind}")
    return res.with_color(np.clip(res.color(), 0, 1))


def op_high_pass(img, p, used):
    s = float(p.get("radius", 10.0))
    res = per_channel(img, lambda ch: ch - core.gaussian_blur(ch, s, used) + 0.5)
    used.add("filter.high_pass", used.items[-1]["rung"], "x - Gaussian(x) + 0.5")
    return res.with_color(np.clip(res.color(), 0, 1))


def op_rank(img, p, used):
    r, which = int(p.get("radius", 1)), p.get("kind", "maximum")
    used.add("filter." + which, 1, "NumPy separable grey " + ("dilation" if which == "maximum" else "erosion"))
    return per_channel(img, lambda ch: rank(ch, r, np.maximum if which == "maximum" else np.minimum))


def op_offset(img, p, used):
    dx, dy = (int(v) for v in p.get("shift", [0, 0]))
    used.add("filter.offset", 1, "NumPy wrap-around roll")
    return img.copy(px=np.roll(img.px, (dy, dx), axis=(0, 1)))


def op_point(img, p, used):
    """Invert, posterize, threshold, solarize on encoded 8-bit-style values."""
    kind = p["kind"]
    c = img.color()
    if kind == "invert":
        out = 1.0 - c
    elif kind == "posterize":
        n = int(p["levels"])     # Photoshop/GIMP: floor(x*N/256) * 255/(N-1) on 0..255
        q = np.floor(np.clip(np.round(c * 255), 0, 255) * n / 256.0)
        out = q * (255.0 / (n - 1)) / 255.0
    elif kind == "threshold":
        y = (c[..., :3] * REC601).sum(axis=2, keepdims=True) if c.shape[2] >= 3 else c
        out = np.repeat((np.round(y * 255) >= p["level"]).astype(np.float32), c.shape[2], axis=2)
    elif kind == "solarize":
        out = np.where(np.round(c * 255) > 127, 1.0 - c, c)
    else:
        raise ValueError(f"unknown colour op {kind}")
    used.add("color." + kind, 1, "NumPy point map")
    return img.with_color(np.asarray(out, np.float32))


def op_mixer(img, p, used):
    used.add("color.mixer", 1, "NumPy 3x3 matrix + offset")
    if img.nc < 3:
        img.notes.append("channel mixer skipped: greyscale image")
        return img
    m = np.array(p["matrix"], np.float32).reshape(3, 3)
    o = np.array(p.get("offset", [0, 0, 0]), np.float32)
    c = img.color()
    out = np.einsum("ij,hwj->hwi", m, c[..., :3]) + o
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_gradient_map(img, p, used):
    used.add("color.gradient_map", 1, "NumPy luma-indexed 1D gradient")
    stops = np.array(p["colors"], np.float32)        # N x 3, evenly spaced from 0 to 1
    c = img.color()
    y = (c[..., :3] * core.LUMA).sum(axis=2) if c.shape[2] >= 3 else c[..., 0]
    xs = np.linspace(0, 1, len(stops))
    out = np.stack([np.interp(y, xs, stops[:, i]) for i in range(3)], axis=2).astype(np.float32)
    if img.nc < 3:
        img = img.copy(px=np.concatenate([np.repeat(img.color(), 3, axis=2), img.px[..., img.nc:]], axis=2))
    return img.with_color(out)


OPS.update({"filter.blur": op_blur, "filter.high_pass": op_high_pass, "filter.rank": op_rank,
            "filter.offset": op_offset, "color.point": op_point, "color.mixer": op_mixer,
            "color.gradient_map": op_gradient_map})


# ---------------------------------------------------------------- commands
def hexes(s):
    out = []
    for h in s.replace(",", " ").split():
        h = h.lstrip("#")
        out.append([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])
    if len(out) < 2:
        raise SystemExit("gradient map: give at least two colours, e.g. '#000000 #ff8800 #ffffff'")
    return out


def with_mask(a, steps):
    if a.mask:
        for s in steps:
            s["mask"] = str(core.Path(a.mask).resolve())
    return steps


def cmd_filter(a):
    steps = []
    if a.blur:
        steps.append({"op": "filter.blur", "params": {"kind": a.blur, "radius": a.radius, "angle": a.angle}})
    if a.high_pass is not None:
        steps.append({"op": "filter.high_pass", "params": {"radius": a.high_pass}})
    if a.maximum:
        steps.append({"op": "filter.rank", "params": {"kind": "maximum", "radius": a.maximum}})
    if a.minimum:
        steps.append({"op": "filter.rank", "params": {"kind": "minimum", "radius": a.minimum}})
    if a.offset:
        steps.append({"op": "filter.offset", "params": {"shift": [int(v) for v in floats(a.offset, 2)]}})
    if not steps:
        raise SystemExit("filter: give --blur, --high-pass, --maximum, --minimum or --offset")
    return core.edit_command(a, "filter", with_mask(a, steps))


def cmd_color(a):
    steps = []
    if a.mixer:
        v = floats(a.mixer, (9, 12))
        steps.append({"op": "color.mixer", "params": {"matrix": v[:9], "offset": v[9:] or [0, 0, 0]}})
    if a.invert:
        steps.append({"op": "color.point", "params": {"kind": "invert"}})
    if a.posterize:
        if a.posterize < 2:
            raise SystemExit("posterize: at least 2 levels")
        steps.append({"op": "color.point", "params": {"kind": "posterize", "levels": a.posterize}})
    if a.solarize:
        steps.append({"op": "color.point", "params": {"kind": "solarize"}})
    if a.threshold is not None:
        steps.append({"op": "color.point", "params": {"kind": "threshold", "level": a.threshold}})
    if a.gradient_map:
        steps.append({"op": "color.gradient_map", "params": {"colors": hexes(a.gradient_map)}})
    if not steps:
        raise SystemExit("color: give --invert, --posterize, --threshold, --solarize, --mixer or --gradient-map")
    return core.edit_command(a, "color", with_mask(a, steps))


def add_commands(sub, edit):
    p = edit("filter", cmd_filter, "blur (gaussian, box, motion), high pass, maximum/minimum, offset (rung 1)")
    p.add_argument("--blur", choices=("gaussian", "box", "motion"))
    p.add_argument("--radius", type=float, default=2.0, help="Gaussian sigma, box radius, or motion length in px")
    p.add_argument("--angle", type=float, default=0.0, help="motion blur angle, degrees counter-clockwise")
    p.add_argument("--high-pass", type=float, help="Gaussian sigma: x - blur(x) + 0.5")
    p.add_argument("--maximum", type=int, help="grey dilation radius (square)")
    p.add_argument("--minimum", type=int, help="grey erosion radius (square)")
    p.add_argument("--offset", help="dx,dy wrap-around shift in px")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("color", cmd_color, "invert, posterize, threshold, solarize, channel mixer, gradient map (rung 1)")
    p.add_argument("--invert", action="store_true")
    p.add_argument("--posterize", type=int, help="levels per channel (2..255)")
    p.add_argument("--threshold", type=int, help="0..255 on Rec. 601 luma: >= level becomes white")
    p.add_argument("--solarize", action="store_true", help="invert values above mid-grey")
    p.add_argument("--mixer", help="3x3 matrix row-major (out r,g,b from in r,g,b), optional 3 offsets")
    p.add_argument("--gradient-map", help="colours from shadows to highlights, '#000000 #ff8800 #ffffff'")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "filter (blur, high pass, max/min, offset)": (1, "own NumPy; Gaussian uses SciPy when present"),
    "color (invert, posterize, threshold, solarize, mixer, gradient map)": (1, "own NumPy"),
})
