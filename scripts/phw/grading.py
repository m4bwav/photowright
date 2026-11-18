"""Batch 10 (0.11.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

grade:    Brightness/Contrast (endpoint preserving), Color Balance (shadows/midtones/highlights,
          preserve luminosity), Photo Filter, Selective Color (absolute), Desaturate ((max+min)/2).
detail:   Dehaze (dark channel prior), Clarity (midtone local contrast), Smart Sharpen (Wiener
          deconvolution of a Gaussian blur), Frequency separation (low or high part).
distort:  Pinch, Twirl, Polar coordinates (to/from), Skew.
pixelate: Mosaic (cell mean).
Own NumPy only; ops keep alpha, take --mask and --recipe and replay through `phw run`.
Module name note: never name a module after a function in core (`from .core import *` puts the
function on the package and `from . import x` then returns the function; tests/test_phw10.py checks).
"""
import math

import numpy as np

from . import core, transform
from .core import OPS, floats

LUMA = core.LUMA


def luma(c):
    return (c[..., :3] * LUMA).sum(axis=2) if c.shape[2] >= 3 else c[..., 0]


def keep_luma(out, ref):
    """Scale out's colour so its luma equals ref's luma (grey pixels shift additively)."""
    y0, y1 = luma(ref), luma(out)
    return out + (y0 - y1)[..., None]


# ---------------------------------------------------------------- grade
def smooth(v):
    return v * v * (3 - 2 * v)


def smooth_inv(v):
    return 0.5 - np.sin(np.arcsin(np.clip(1 - 2 * v, -1, 1)) / 3)


def op_brightness_contrast(img, p, used):
    """brightness b in -1..1: v ** 2**-b (0 and 1 fixed); contrast c in -1..1: blend toward
    smoothstep (c > 0) or its inverse (c < 0), endpoints fixed, monotone."""
    b, ct = float(p.get("brightness", 0)), float(p.get("contrast", 0))
    c = img.color().astype(np.float64)
    if b:
        c = np.clip(c, 0, 1) ** (2.0 ** -b)
    if ct > 0:
        c = c + ct * (smooth(c) - c)
    elif ct < 0:
        c = c + (-ct) * (smooth_inv(c) - c)
    used.add("grade.brightness_contrast", 1, "NumPy endpoint-preserving gamma and S-curve")
    return img.with_color(np.clip(c, 0, 1).astype(np.float32))


def op_balance(img, p, used):
    """Shifts in cyan-red, magenta-green, yellow-blue (-1..1) per tonal range; weights from luma:
    shadows (1-L)^2, midtones 2L(1-L), highlights L^2. A shift of 1 moves a channel by 0.25 at full weight."""
    c = img.color().astype(np.float64)
    if c.shape[2] < 3:
        raise ValueError("grade --balance needs a colour image")
    L = luma(c)
    w = {"shadows": (1 - L) ** 2, "midtones": 2 * L * (1 - L), "highlights": L ** 2}
    out = c.copy()
    for rng, shift in p["shifts"].items():
        out[..., :3] += 0.25 * w[rng][..., None] * np.asarray(shift, np.float64)
    if p.get("preserve", True):
        out[..., :3] = keep_luma(out[..., :3], c[..., :3])
    used.add("grade.balance", 1, "NumPy tonal-range weighted shifts")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_photo_filter(img, p, used):
    """Multiply by the filter colour, blend by density, then restore luma (preserve luminosity)."""
    col, d = np.asarray(p["color"], np.float64), float(p.get("density", 0.25))
    c = img.color().astype(np.float64)
    if c.shape[2] < 3:
        raise ValueError("grade --photo-filter needs a colour image")
    out = c.copy()
    out[..., :3] = c[..., :3] + d * (c[..., :3] * col - c[..., :3])
    if p.get("preserve", True):
        out[..., :3] = keep_luma(out[..., :3], c[..., :3])
    used.add("grade.photo_filter", 1, "NumPy multiply blend with luma kept")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


HUES = {"reds": 0, "yellows": 1, "greens": 2, "cyans": 3, "blues": 4, "magentas": 5}


def selective_weights(c, name):
    mx, mn = c.max(axis=2), c.min(axis=2)
    if name == "whites":
        return np.clip(2 * mn - 1, 0, 1)
    if name == "blacks":
        return np.clip(1 - 2 * mx, 0, 1)
    if name == "neutrals":
        return np.clip(1 - (mx - mn) - np.abs(mx + mn - 1), 0, 1)
    srt = np.sort(c, axis=2)
    mid = srt[..., 1]
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    i = HUES[name]
    if i % 2 == 0:      # primaries: the channel is the strict max; weight = max - mid
        ch = c[..., i // 2]
        others = np.delete(c, i // 2, axis=2).max(axis=2)
        return np.where(ch > others, mx - mid, 0)
    # secondaries (yellow = r+g, cyan = g+b, magenta = r+b): the missing channel is the strict min
    miss = {1: b, 3: r, 5: g}[i]
    rest = {1: np.minimum(r, g), 3: np.minimum(g, b), 5: np.minimum(r, b)}[i]
    return np.where(miss < rest, mid - mn, 0)


def op_selective(img, p, used):
    """Absolute Selective Color: per range, cyan/magenta/yellow/black (-1..1) subtract from R/G/B
    (black from all) in proportion to the range weight."""
    c = img.color().astype(np.float64)
    if c.shape[2] < 3:
        raise ValueError("grade --selective needs a colour image")
    rgb = c[..., :3]
    out = c.copy()
    for name, (cy, mg, ye, k) in p["ranges"].items():
        w = selective_weights(rgb, name)[..., None]
        out[..., :3] -= w * (np.array([cy, mg, ye]) + k)
    used.add("grade.selective", 1, "NumPy selective colour (absolute)")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_desaturate(img, p, used):
    c = img.color()
    if c.shape[2] < 3:
        return img
    v = (c[..., :3].max(axis=2) + c[..., :3].min(axis=2)) / 2
    out = c.copy()
    out[..., :3] = v[..., None]
    used.add("grade.desaturate", 1, "NumPy (max+min)/2 lightness")
    return img.with_color(out.astype(np.float32))


# ---------------------------------------------------------------- detail
def min_filter(ch, r):
    p = np.pad(ch, r, mode="edge")
    h, w = ch.shape
    rows = np.min(np.stack([p[:, dx:dx + w] for dx in range(2 * r + 1)]), axis=0)
    return np.min(np.stack([rows[dy:dy + h] for dy in range(2 * r + 1)]), axis=0)


def op_dehaze(img, p, used):
    """He, Sun, Tang dark channel prior: airlight from the brightest 0.1% of the dark channel,
    transmission 1 - omega * dark(I / A), smoothed by a Gaussian, floored at t0."""
    c = img.color().astype(np.float64)
    if c.shape[2] < 3:
        raise ValueError("detail --dehaze needs a colour image")
    rgb = c[..., :3]
    r, omega, t0 = int(p.get("radius", 7)), float(p.get("amount", 0.95)), float(p.get("t0", 0.1))
    dark = min_filter(rgb.min(axis=2), r)
    n = max(1, int(dark.size * 0.001))
    idx = np.argsort(dark.ravel())[-n:]
    A = np.maximum(rgb.reshape(-1, 3)[idx].mean(axis=0), 1e-3)
    t = 1 - omega * min_filter((rgb / A).min(axis=2), r)
    t = core.gaussian_blur(t.astype(np.float32), max(1.0, r / 2.0)).astype(np.float64)
    t = np.maximum(t, t0)[..., None]
    out = c.copy()
    out[..., :3] = (rgb - A) / t + A
    used.add("detail.dehaze", 1, f"NumPy dark channel prior (A={[round(float(x), 3) for x in A]})")
    img.notes.append(f"dehaze airlight {[round(float(x), 4) for x in A]}")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_clarity(img, p, used):
    """Local contrast on luma, weighted to midtones 4L(1-L), colour scaled with the luma change."""
    amt, sigma = float(p["amount"]), float(p.get("radius", 20))
    c = img.color().astype(np.float64)
    L = luma(c)
    base = core.gaussian_blur(L.astype(np.float32), sigma).astype(np.float64)
    L2 = np.clip(L + amt * (L - base) * 4 * L * (1 - L), 0, 1)
    if c.shape[2] >= 3:
        out = c.copy()
        out[..., :3] = c[..., :3] + (L2 - L)[..., None]
    else:
        out = L2[..., None]
    used.add("detail.clarity", 1, "NumPy midtone-weighted local contrast")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def wiener(ch, sigma, k):
    h, w = ch.shape
    pad = int(math.ceil(3 * sigma)) + 2
    P = np.pad(ch, pad, mode="symmetric")
    H, W = P.shape
    fy, fx = np.fft.fftfreq(H)[:, None], np.fft.rfftfreq(W)[None, :]
    G = np.exp(-2 * (math.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))   # Gaussian transfer function
    F = np.fft.rfft2(P) * G / (G * G + k)
    return np.fft.irfft2(F, s=P.shape)[pad:pad + h, pad:pad + w]


def op_smart_sharpen(img, p, used):
    """Remove Gaussian Blur: Wiener deconvolution with a Gaussian PSF of `radius` sigma per channel;
    `noise` is the regulariser k (larger = less ringing and noise), `amount` blends."""
    sigma, k, amt = float(p.get("radius", 1.0)), float(p.get("noise", 0.002)), float(p.get("amount", 1.0))
    c = img.color().astype(np.float64)
    d = np.stack([wiener(c[..., i], sigma, k) for i in range(c.shape[2])], axis=2)
    used.add("detail.smart_sharpen", 1, "NumPy FFT Wiener deconvolution (Gaussian PSF)")
    return img.with_color(np.clip(c + amt * (d - c), 0, 1).astype(np.float32))


def op_freqsep(img, p, used):
    """Frequency separation: low = Gaussian blur; high = image - low + 0.5 (Linear Light ready)."""
    sigma = float(p["radius"])
    c = img.color()
    low = np.stack([core.gaussian_blur(c[..., i], sigma) for i in range(c.shape[2])], axis=2)
    out = low if p.get("part", "low") == "low" else c - low + 0.5
    used.add("detail.freqsep", 1, f"NumPy Gaussian split ({p.get('part', 'low')})")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- distort
def grid(img):
    h, w = img.px.shape[:2]
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
    return h, w, X, Y, (w - 1) / 2.0, (h - 1) / 2.0


def op_pinch(img, p, used):
    """amount -1..1: inside the inscribed circle, destination radius rn samples source rn ** (1 - amount/2)
    (amount > 0 pulls content in); the circle edge and everything outside stay put."""
    amt = float(p["amount"])
    h, w, X, Y, cx, cy = grid(img)
    R = min(cx, cy) + 0.5
    dx, dy = X - cx, Y - cy
    rn = np.hypot(dx, dy) / R
    s = np.where((rn < 1) & (rn > 0), np.power(np.maximum(rn, 1e-9), -amt / 2), 1.0)
    return transform.remap(img, (cx + dx * s).astype(np.float32), (cy + dy * s).astype(np.float32), used,
                           "distort.pinch")


def op_twirl(img, p, used):
    """Rotate by angle * (1 - r/R) inside the inscribed circle (degrees, positive counter-clockwise)."""
    a = math.radians(float(p["angle"]))
    h, w, X, Y, cx, cy = grid(img)
    R = min(cx, cy) + 0.5
    dx, dy = X - cx, Y - cy
    th = np.where(np.hypot(dx, dy) < R, -a * (1 - np.hypot(dx, dy) / R), 0)   # inverse map
    cs, sn = np.cos(th), np.sin(th)
    return transform.remap(img, (cx + dx * cs + dy * sn).astype(np.float32),
                           (cy - dx * sn + dy * cs).astype(np.float32), used, "distort.twirl")


def op_polar(img, p, used):
    """to: rows become rings (top row at the centre), columns go round from 12 o'clock clockwise;
    from: the inverse."""
    h, w, X, Y, cx, cy = grid(img)
    R = min(cx, cy) + 0.5
    if p.get("mode", "to") == "to":
        dx, dy = X - cx, Y - cy
        ang = (np.arctan2(dx, -dy) % (2 * math.pi)) / (2 * math.pi)
        # clamp: at 12 o'clock and the centre the sample sits half a pixel outside and would blend the border
        SX = np.clip(ang * w - 0.5, 0, w - 1)
        SY = np.clip(np.hypot(dx, dy) / R * h - 0.5, 0, None)
    else:
        ang = (X + 0.5) / w * 2 * math.pi
        rr = (Y + 0.5) / h * R
        SX, SY = cx + rr * np.sin(ang), cy - rr * np.cos(ang)
    return transform.remap(img, SX.astype(np.float32), SY.astype(np.float32), used, "distort.polar")


def op_skew(img, p, used):
    """Shear about the centre: x' = x + tan(ax) * (y - cy), y' = y + tan(ay) * (x - cx); same canvas."""
    tx, ty = math.tan(math.radians(float(p.get("x", 0)))), math.tan(math.radians(float(p.get("y", 0))))
    h, w, X, Y, cx, cy = grid(img)
    det = 1 - tx * ty
    dx, dy = X - cx, Y - cy
    SX = cx + (dx - tx * dy) / det
    SY = cy + (dy - ty * dx) / det
    return transform.remap(img, SX.astype(np.float32), SY.astype(np.float32), used, "distort.skew")


def op_mosaic(img, p, used):
    """Each cell (from the top left) takes the mean of its pixels; alpha cells averaged premultiplied."""
    n = int(p["cell"])
    h, w = img.px.shape[:2]
    px = img.px.astype(np.float64)
    if img.alpha:
        px = np.concatenate([px[..., :-1] * px[..., -1:], px[..., -1:]], axis=2)
    out = np.empty_like(px)
    for y in range(0, h, n):
        for x in range(0, w, n):
            out[y:y + n, x:x + n] = px[y:y + n, x:x + n].reshape(-1, px.shape[2]).mean(axis=0)
    if img.alpha:
        a = out[..., -1:]
        out[..., :-1] = np.where(a > 1e-9, out[..., :-1] / np.maximum(a, 1e-9), 0)
    used.add("pixelate.mosaic", 1, "NumPy cell mean")
    return img.copy(px=np.clip(out, 0, 1).astype(np.float32))


OPS.update({"grade.brightness_contrast": op_brightness_contrast, "grade.balance": op_balance,
            "grade.photo_filter": op_photo_filter, "grade.selective": op_selective,
            "grade.desaturate": op_desaturate, "detail.dehaze": op_dehaze, "detail.clarity": op_clarity,
            "detail.smart_sharpen": op_smart_sharpen, "detail.freqsep": op_freqsep,
            "distort.pinch": op_pinch, "distort.twirl": op_twirl, "distort.polar": op_polar,
            "distort.skew": op_skew, "pixelate.mosaic": op_mosaic})

FILTERS = {"warming": [1.0, 0.75, 0.45], "cooling": [0.45, 0.75, 1.0], "sepia": [0.9, 0.7, 0.45]}


# ---------------------------------------------------------------- commands
def with_mask(a, steps):
    if getattr(a, "mask", None):
        for s in steps:
            s["mask"] = str(core.Path(a.mask).resolve())
    return steps


def hexcol(s):
    h = s.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def cmd_grade(a):
    steps = []
    if a.brightness or a.contrast:
        steps.append({"op": "grade.brightness_contrast", "params": {"brightness": a.brightness, "contrast": a.contrast}})
    shifts = {k: floats(v, 3) for k, v in (("shadows", a.balance_shadows), ("midtones", a.balance_midtones),
                                           ("highlights", a.balance_highlights)) if v}
    if shifts:
        steps.append({"op": "grade.balance", "params": {"shifts": shifts, "preserve": not a.no_preserve}})
    if a.photo_filter:
        col = FILTERS.get(a.photo_filter) or hexcol(a.photo_filter)
        steps.append({"op": "grade.photo_filter", "params": {"color": col, "density": a.density,
                                                             "preserve": not a.no_preserve}})
    if a.selective:
        ranges = {}
        for item in a.selective:
            name, vals = item.split("=", 1)
            if name not in list(HUES) + ["whites", "neutrals", "blacks"]:
                raise SystemExit(f"grade --selective: unknown range {name}")
            ranges[name] = floats(vals, 4)
        steps.append({"op": "grade.selective", "params": {"ranges": ranges}})
    if a.desaturate:
        steps.append({"op": "grade.desaturate", "params": {}})
    if not steps:
        raise SystemExit("grade: give --brightness/--contrast, --balance-*, --photo-filter, --selective or --desaturate")
    return core.edit_command(a, "grade", with_mask(a, steps))


def cmd_detail(a):
    steps = []
    if a.dehaze is not None:
        steps.append({"op": "detail.dehaze", "params": {"amount": a.dehaze, "radius": a.dark_radius}})
    if a.clarity:
        steps.append({"op": "detail.clarity", "params": {"amount": a.clarity, "radius": a.clarity_radius}})
    if a.smart_sharpen is not None:
        steps.append({"op": "detail.smart_sharpen", "params": {"radius": a.smart_sharpen, "noise": a.noise,
                                                               "amount": a.amount}})
    if a.freq_sep is not None:
        steps.append({"op": "detail.freqsep", "params": {"radius": a.freq_sep, "part": a.part}})
    if not steps:
        raise SystemExit("detail: give --dehaze, --clarity, --smart-sharpen or --freq-sep")
    return core.edit_command(a, "detail", with_mask(a, steps))


def cmd_distort(a):
    steps = []
    if a.pinch is not None:
        steps.append({"op": "distort.pinch", "params": {"amount": a.pinch}})
    if a.twirl is not None:
        steps.append({"op": "distort.twirl", "params": {"angle": a.twirl}})
    if a.polar:
        steps.append({"op": "distort.polar", "params": {"mode": a.polar}})
    if a.skew:
        sx, sy = floats(a.skew, 2)
        steps.append({"op": "distort.skew", "params": {"x": sx, "y": sy}})
    if not steps:
        raise SystemExit("distort: give --pinch, --twirl, --polar or --skew")
    return core.edit_command(a, "distort", with_mask(a, steps))


def cmd_pixelate(a):
    return core.edit_command(a, "pixelate", with_mask(a, [{"op": "pixelate.mosaic", "params": {"cell": a.cell}}]))


def add_commands(sub, edit):
    p = edit("grade", cmd_grade, "brightness/contrast, color balance, photo filter, selective color, desaturate (rung 1)")
    p.add_argument("--brightness", type=float, default=0.0, help="-1..1 (endpoints fixed)")
    p.add_argument("--contrast", type=float, default=0.0, help="-1..1 S-curve (endpoints fixed)")
    p.add_argument("--balance-shadows", help="cyan-red,magenta-green,yellow-blue in -1..1")
    p.add_argument("--balance-midtones")
    p.add_argument("--balance-highlights")
    p.add_argument("--photo-filter", help="warming, cooling, sepia or '#rrggbb'")
    p.add_argument("--density", type=float, default=0.25)
    p.add_argument("--no-preserve", action="store_true", help="do not keep luminosity (balance, photo filter)")
    p.add_argument("--selective", action="append", help="range=c,m,y,k (-1..1); ranges: reds yellows greens "
                   "cyans blues magentas whites neutrals blacks; repeatable")
    p.add_argument("--desaturate", action="store_true", help="(max+min)/2 as Photoshop's Desaturate")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("detail", cmd_detail, "dehaze, clarity, smart sharpen, frequency separation (rung 1)")
    p.add_argument("--dehaze", type=float, help="0..1 haze removed (omega of the dark channel prior)")
    p.add_argument("--dark-radius", type=int, default=7)
    p.add_argument("--clarity", type=float, help="-2..2 midtone local contrast")
    p.add_argument("--clarity-radius", type=float, default=20.0)
    p.add_argument("--smart-sharpen", type=float, help="sigma of the Gaussian blur to remove")
    p.add_argument("--noise", type=float, default=0.002, help="Wiener regulariser (more = less ringing)")
    p.add_argument("--amount", type=float, default=1.0)
    p.add_argument("--freq-sep", type=float, help="blur sigma that splits low and high frequencies")
    p.add_argument("--part", choices=("low", "high"), default="low")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("distort", cmd_distort, "pinch, twirl, polar coordinates, skew (rung 1)")
    p.add_argument("--pinch", type=float, help="-1..1 (positive pulls in)")
    p.add_argument("--twirl", type=float, help="degrees at the centre, counter-clockwise")
    p.add_argument("--polar", choices=("to", "from"))
    p.add_argument("--skew", help="X,Y shear angles in degrees")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("pixelate", cmd_pixelate, "mosaic (rung 1)")
    p.add_argument("--cell", type=int, required=True, help="cell size in px")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "grade (brightness/contrast, balance, photo filter, selective, desaturate)": (1, "own NumPy"),
    "detail (dehaze, clarity, smart sharpen, frequency separation)": (1, "own NumPy"),
    "distort (pinch, twirl, polar, skew), pixelate (mosaic)": (1, "own NumPy"),
})
