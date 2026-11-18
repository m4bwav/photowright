"""Batch 11 (0.12.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

warpfx:   Wave / Ripple (sine, triangle, square), Spherize, ZigZag (pond ripples), Lens Correction
          (radial k1, k2 about the centre).
stylize:  Crystallize (seeded Voronoi cell means), Color Halftone (rotated dot screens per channel),
          Trace Contour, Diffuse, Wind, Oil Paint (Kuwahara), Clouds (seeded fBm, fg to bg).
blurfx:   Radial blur (spin and zoom), Surface Blur (box mean of neighbours within a threshold).
tonebrush: Dodge, Burn (shadows/midtones/highlights, exposure) and Sponge (saturate/desaturate, luma kept).
Own NumPy only; ops keep alpha, take --mask and --recipe and replay through `phw run`.
"""
import math

import numpy as np

from . import core, transform
from .core import OPS, floats
from .grading import grid, luma, keep_luma, with_mask


def per_ch(c, fn):
    return np.stack([fn(c[..., i]) for i in range(c.shape[2])], axis=2)


# ---------------------------------------------------------------- warpfx
def wave_fn(t, kind):
    """t in cycles -> -1..1."""
    f = t - np.floor(t)
    if kind == "triangle":
        return 4 * np.abs(f - 0.5) - 1
    if kind == "square":
        return np.where(f < 0.5, 1.0, -1.0)
    return np.sin(2 * math.pi * t)


def op_wave(img, p, used):
    """x' samples x + amp * wave(y / wavelength), y' samples y + amp * wave(x / wavelength)
    (axis 'x' or 'y' limits it to one direction)."""
    amp, wl, kind, axis = float(p["amp"]), float(p["wavelength"]), p.get("kind", "sine"), p.get("axis", "both")
    h, w, X, Y, cx, cy = grid(img)
    SX = X + (amp * wave_fn(Y / wl, kind) if axis in ("both", "x") else 0)
    SY = Y + (amp * wave_fn(X / wl, kind) if axis in ("both", "y") else 0)
    return transform.remap(img, np.clip(SX, 0, w - 1).astype(np.float32),
                           np.clip(SY, 0, h - 1).astype(np.float32), used, "warpfx.wave")


def op_spherize(img, p, used):
    """amount -1..1 inside the inscribed circle: source radius = (1-a) rn + a (2/pi) asin(rn) for a > 0
    (magnifies the centre), the inverse curve for a < 0; edge and outside fixed."""
    a = float(p["amount"])
    h, w, X, Y, cx, cy = grid(img)
    R = min(cx, cy) + 0.5
    dx, dy = X - cx, Y - cy
    rn = np.clip(np.hypot(dx, dy) / R, 0, None)
    inside = rn < 1
    r1 = np.minimum(rn, 1)
    if a >= 0:
        src = (1 - a) * r1 + a * (2 / math.pi) * np.arcsin(r1)
    else:
        src = (1 + a) * r1 + (-a) * np.sin(r1 * math.pi / 2)
    s = np.where(inside & (rn > 0), src / np.maximum(rn, 1e-9), 1.0)
    return transform.remap(img, (cx + dx * s).astype(np.float32), (cy + dy * s).astype(np.float32), used,
                           "warpfx.spherize")


def op_zigzag(img, p, used):
    """Pond ripples: rotate each pixel about the centre by amount degrees * sin(2 pi ridges rn) * (1 - rn)
    inside the inscribed circle. Radius never changes, so concentric rings stay put."""
    amt, ridges = math.radians(float(p["amount"])), float(p.get("ridges", 5))
    h, w, X, Y, cx, cy = grid(img)
    R = min(cx, cy) + 0.5
    dx, dy = X - cx, Y - cy
    rn = np.hypot(dx, dy) / R
    th = np.where(rn < 1, -amt * np.sin(2 * math.pi * ridges * rn) * (1 - rn), 0)
    cs, sn = np.cos(th), np.sin(th)
    return transform.remap(img, (cx + dx * cs + dy * sn).astype(np.float32),
                           (cy - dx * sn + dy * cs).astype(np.float32), used, "warpfx.zigzag")


def op_lens(img, p, used):
    """Brown radial model about the centre, r normalised to the half diagonal: the output at r samples
    the source at r (1 + k1 r^2 + k2 r^4). k1 > 0 removes barrel distortion, k1 < 0 pincushion."""
    k1, k2 = float(p.get("k1", 0)), float(p.get("k2", 0))
    h, w, X, Y, cx, cy = grid(img)
    D = math.hypot(cx, cy) or 1.0
    dx, dy = X - cx, Y - cy
    r2 = (dx * dx + dy * dy) / (D * D)
    s = 1 + k1 * r2 + k2 * r2 * r2
    return transform.remap(img, (cx + dx * s).astype(np.float32), (cy + dy * s).astype(np.float32), used,
                           "warpfx.lens")


# ---------------------------------------------------------------- stylize
def voronoi_labels(h, w, cell, seed):
    rng = np.random.default_rng(int(seed))
    gy, gx = np.mgrid[0:h:cell, 0:w:cell]
    sy = (gy + rng.uniform(0, cell, gy.shape)).ravel()
    sx = (gx + rng.uniform(0, cell, gx.shape)).ravel()
    Y, X = np.mgrid[0:h, 0:w]
    best = np.full((h, w), np.inf)
    lab = np.zeros((h, w), np.int64)
    for i in range(sy.size):       # local search would be faster; the seed count is small at sane cells
        d = (Y - sy[i]) ** 2 + (X - sx[i]) ** 2
        m = d < best
        best[m] = d[m]
        lab[m] = i
    return lab, sy.size


def op_crystallize(img, p, used):
    """Seeded jittered-grid Voronoi cells; each cell takes the mean of its pixels."""
    h, w = img.px.shape[:2]
    lab, n = voronoi_labels(h, w, int(p["cell"]), p.get("seed", 0))
    px = img.px.astype(np.float64)
    cnt = np.bincount(lab.ravel(), minlength=n)
    out = np.empty_like(px)
    for c in range(px.shape[2]):
        s = np.bincount(lab.ravel(), weights=px[..., c].ravel(), minlength=n)
        out[..., c] = (s / np.maximum(cnt, 1))[lab]
    used.add("stylize.crystallize", 1, "NumPy seeded Voronoi cell mean")
    return img.copy(px=out.astype(np.float32))


HALFTONE_ANGLES = [108.0, 162.0, 90.0, 45.0]


def op_halftone(img, p, used):
    """Per channel a dot screen at Photoshop's default angles: ink (1 - value) covers each cell with a
    round dot of area = coverage (dots merge into holes past 50%), so a flat patch keeps its mean."""
    cell = float(p["cell"])
    angles = p.get("angles") or HALFTONE_ANGLES
    c = img.color()
    h, w = c.shape[:2]
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
    out = np.empty_like(c)
    for i in range(c.shape[2]):
        a = math.radians(angles[i % len(angles)])
        u = X * math.cos(a) + Y * math.sin(a)
        v = -X * math.sin(a) + Y * math.cos(a)
        fu, fv = u / cell - np.floor(u / cell) - 0.5, v / cell - np.floor(v / cell) - 0.5
        # cosine spot function: smooth cell shape whose threshold area tracks the coverage linearly
        spot = (np.cos(2 * math.pi * fu) + np.cos(2 * math.pi * fv)) / 4 + 0.5    # 1 at centre, 0 at corners
        ink = 1 - c[..., i]
        # the area of {spot > t} is not linear in t; use the empirical CDF of spot over a fine cell
        t = np.quantile(SPOT_SAMPLES, np.clip(1 - ink, 0, 1))
        out[..., i] = np.where(spot > t, 0.0, 1.0)
    used.add("stylize.halftone", 1, "NumPy rotated dot screens")
    return img.with_color(out.astype(np.float32))


_g = (np.arange(256) + 0.5) / 256 - 0.5
_U, _V = np.meshgrid(_g, _g)
SPOT_SAMPLES = ((np.cos(2 * math.pi * _U) + np.cos(2 * math.pi * _V)) / 4 + 0.5).ravel()


def op_trace_contour(img, p, used):
    """Photoshop Trace Contour (upper): a pixel at or above the level whose right or lower neighbour is
    below it turns black in that channel; everything else white."""
    lv = float(p["level"]) / 255.0
    edge = p.get("edge", "upper")
    c = img.color()

    def one(ch):
        hi = ch >= lv if edge == "upper" else ch < lv
        nb_r = np.zeros_like(hi)
        nb_d = np.zeros_like(hi)
        nb_r[:, :-1] = hi[:, :-1] & ~hi[:, 1:]
        nb_d[:-1] = hi[:-1] & ~hi[1:]
        return np.where(nb_r | nb_d, 0.0, 1.0)
    used.add("stylize.trace_contour", 1, "NumPy level crossing")
    return img.with_color(per_ch(c, one).astype(np.float32))


def op_diffuse(img, p, used):
    """Normal: every pixel takes a seeded random neighbour's value within radius r (default 1)."""
    r = int(p.get("radius", 1))
    rng = np.random.default_rng(int(p.get("seed", 0)))
    h, w = img.px.shape[:2]
    Y, X = np.mgrid[0:h, 0:w]
    sy = np.clip(Y + rng.integers(-r, r + 1, (h, w)), 0, h - 1)
    sx = np.clip(X + rng.integers(-r, r + 1, (h, w)), 0, w - 1)
    used.add("stylize.diffuse", 1, "NumPy seeded neighbour swap")
    return img.copy(px=img.px[sy, sx])


def op_wind(img, p, used):
    """Bright streaks blown along the direction: out = max(in, decay * out of the upwind neighbour),
    decay = 1 - 1/length. Dark pixels never spread; a flat image is unchanged."""
    L = float(p.get("length", 12))
    decay = 1 - 1 / max(L, 1.0)
    c = img.color().astype(np.float64)
    if p.get("direction", "right") == "left":
        c = c[:, ::-1]
    out = c.copy()
    for x in range(1, c.shape[1]):
        out[:, x] = np.maximum(c[:, x], decay * out[:, x - 1])
    if p.get("direction", "right") == "left":
        out = out[:, ::-1]
    used.add("stylize.wind", 1, "NumPy decaying max trail")
    return img.with_color(out.astype(np.float32))


def op_oil(img, p, used):
    """Kuwahara: each pixel takes the mean of whichever of its four (r+1)^2 quadrants has the lowest
    luma variance. Smooths texture, keeps edges hard."""
    r = int(p.get("radius", 3))
    c = img.color().astype(np.float64)
    h, w = c.shape[:2]
    y = luma(c)
    pad = lambda a: np.pad(a, r, mode="symmetric")  # noqa: E731

    def sat(a):
        return np.pad(pad(a).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    k = r + 1

    def quad_sum(S, oy, ox):
        # window rows [y+oy, y+oy+k), cols [x+ox, x+ox+k) in original coords; padded index = +r
        y0, x0 = r + oy, r + ox
        return (S[y0 + k:y0 + k + h, x0 + k:x0 + k + w] - S[y0:y0 + h, x0 + k:x0 + k + w]
                - S[y0 + k:y0 + k + h, x0:x0 + w] + S[y0:y0 + h, x0:x0 + w])
    Sy, Syy = sat(y), sat(y * y)
    Sc = [sat(c[..., i]) for i in range(c.shape[2])]
    offs = [(-r, -r), (-r, 0), (0, -r), (0, 0)]
    best_v = np.full((h, w), np.inf)
    out = np.zeros_like(c)
    n = k * k
    for oy, ox in offs:
        m = quad_sum(Sy, oy, ox) / n
        v = quad_sum(Syy, oy, ox) / n - m * m
        sel = v < best_v - 1e-12
        best_v = np.where(sel, v, best_v)
        for i in range(c.shape[2]):
            out[..., i] = np.where(sel, quad_sum(Sc[i], oy, ox) / n, out[..., i])
    used.add("stylize.oil", 1, "NumPy Kuwahara filter")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_clouds(img, p, used):
    """Seeded fBm (value noise, octaves halve in size and amplitude) mapped from fg to bg colour;
    replaces the colour, keeps alpha."""
    rng = np.random.default_rng(int(p.get("seed", 0)))
    h, w = img.px.shape[:2]
    acc = np.zeros((h, w))
    amp, tot, size = 1.0, 0.0, float(p.get("scale", 128))
    while size >= 1:
        gh, gw = int(math.ceil(h / size)) + 2, int(math.ceil(w / size)) + 2
        g = rng.random((gh, gw))
        yy, xx = np.arange(h) / size, np.arange(w) / size
        y0, x0 = np.floor(yy).astype(int), np.floor(xx).astype(int)
        fy, fx = yy - y0, xx - x0
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
        a = g[y0][:, x0] * (1 - fx) + g[y0][:, x0 + 1] * fx
        b = g[y0 + 1][:, x0] * (1 - fx) + g[y0 + 1][:, x0 + 1] * fx
        acc += amp * (a * (1 - fy[:, None]) + b * fy[:, None])
        tot += amp
        amp /= 2
        size /= 2
    t = acc / tot
    t = (t - t.min()) / max(t.max() - t.min(), 1e-9)
    fg, bg = np.asarray(p.get("fg", [0, 0, 0]), float), np.asarray(p.get("bg", [1, 1, 1]), float)
    nc = img.nc
    col = fg[:nc][None, None] * (1 - t[..., None]) + bg[:nc][None, None] * t[..., None] if nc >= 3 else t[..., None]
    used.add("stylize.clouds", 1, "NumPy seeded fBm value noise")
    return img.with_color(col.astype(np.float32))


# ---------------------------------------------------------------- blurfx
def op_radial_blur(img, p, used):
    """spin: average n samples along an arc of +-angle/2 about the centre; zoom: along the ray from
    the centre, scales 1 - amount .. 1. Linear light, alpha premultiplied by remap."""
    mode, amt = p.get("mode", "spin"), float(p["amount"])
    n = int(p.get("samples", 16))
    h, w, X, Y, cx, cy = grid(img)
    dx, dy = X - cx, Y - cy
    acc = None
    for i in range(n):
        t = (i + 0.5) / n - 0.5
        if mode == "spin":
            th = math.radians(amt) * t
            SX, SY = cx + dx * math.cos(th) - dy * math.sin(th), cy + dx * math.sin(th) + dy * math.cos(th)
        else:
            s = 1 - amt * (t + 0.5)
            SX, SY = cx + dx * s, cy + dy * s
        r = transform.remap(img, np.clip(SX, 0, w - 1).astype(np.float32),
                            np.clip(SY, 0, h - 1).astype(np.float32), core.Used(), "blurfx.radial")
        acc = r.px.astype(np.float64) if acc is None else acc + r.px
    used.add("blurfx.radial", 1, f"own {n}-sample {mode} blur")
    return img.copy(px=(acc / n).astype(np.float32))


def op_surface_blur(img, p, used):
    """Mean of the neighbours within radius r whose value differs by at most threshold (per channel)."""
    r, th = int(p["radius"]), float(p["threshold"]) / 255.0
    c = img.color().astype(np.float64)
    h, w = c.shape[:2]
    out = np.empty_like(c)
    for i in range(c.shape[2]):
        ch = c[..., i]
        pd = np.pad(ch, r, mode="symmetric")
        s = np.zeros((h, w))
        n = np.zeros((h, w))
        for oy in range(-r, r + 1):
            for ox in range(-r, r + 1):
                v = pd[r + oy:r + oy + h, r + ox:r + ox + w]
                m = np.abs(v - ch) <= th + 1e-9
                s += np.where(m, v, 0)
                n += m
        out[..., i] = s / n
    used.add("blurfx.surface", 1, "NumPy thresholded box mean")
    return img.with_color(out.astype(np.float32))


# ---------------------------------------------------------------- tonebrush
def range_weight(y, rng):
    if rng == "shadows":
        return np.clip(1 - y / 0.5, 0, 1) ** 1.5
    if rng == "highlights":
        return np.clip((y - 0.5) / 0.5, 0, 1) ** 1.5
    return 1 - (2 * y - 1) ** 2


def op_tonebrush(img, p, used):
    """dodge/burn: v -> v ** (1 -/+ exposure * weight(luma, range)) per channel (0 and 1 fixed);
    sponge: chroma about the luma scaled by 1 + flow (saturate) or 1 - flow (desaturate), luma kept."""
    mode, amt = p["mode"], float(p.get("exposure", 0.5))
    c = img.color().astype(np.float64)
    y = luma(c)
    if mode in ("dodge", "burn"):
        wgt = range_weight(y, p.get("range", "midtones"))[..., None]
        g = 1 - amt * wgt if mode == "dodge" else 1 + amt * wgt
        out = np.power(np.clip(c, 0, 1), np.maximum(g, 0.05))
    else:
        k = 1 + amt if p.get("sponge", "desaturate") == "saturate" else 1 - amt
        out = y[..., None] + (c - y[..., None]) * k
        out = keep_luma(np.clip(out, 0, 1), c)
    used.add("tonebrush." + mode, 1, "NumPy range-weighted tone")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


OPS.update({"warpfx.wave": op_wave, "warpfx.spherize": op_spherize, "warpfx.zigzag": op_zigzag,
            "warpfx.lens": op_lens, "stylize.crystallize": op_crystallize, "stylize.halftone": op_halftone,
            "stylize.trace_contour": op_trace_contour, "stylize.diffuse": op_diffuse, "stylize.wind": op_wind,
            "stylize.oil": op_oil, "stylize.clouds": op_clouds, "blurfx.radial": op_radial_blur,
            "blurfx.surface": op_surface_blur, "tonebrush": op_tonebrush})


# ---------------------------------------------------------------- commands
def hexcol(s):
    h = s.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def cmd_warpfx(a):
    steps = []
    if a.wave:
        amp, wl = floats(a.wave, 2)
        steps.append({"op": "warpfx.wave", "params": {"amp": amp, "wavelength": wl, "kind": a.wave_type,
                                                      "axis": a.axis}})
    if a.spherize is not None:
        steps.append({"op": "warpfx.spherize", "params": {"amount": a.spherize}})
    if a.zigzag is not None:
        steps.append({"op": "warpfx.zigzag", "params": {"amount": a.zigzag, "ridges": a.ridges}})
    if a.lens:
        k = floats(a.lens)
        steps.append({"op": "warpfx.lens", "params": {"k1": k[0], "k2": k[1] if len(k) > 1 else 0.0}})
    if not steps:
        raise SystemExit("warpfx: give --wave, --spherize, --zigzag or --lens")
    return core.edit_command(a, "warpfx", with_mask(a, steps))


def cmd_stylize(a):
    steps = []
    if a.crystallize:
        steps.append({"op": "stylize.crystallize", "params": {"cell": a.crystallize, "seed": a.seed}})
    if a.halftone:
        steps.append({"op": "stylize.halftone", "params": {"cell": a.halftone}})
    if a.trace_contour is not None:
        steps.append({"op": "stylize.trace_contour", "params": {"level": a.trace_contour, "edge": a.edge}})
    if a.diffuse:
        steps.append({"op": "stylize.diffuse", "params": {"radius": a.diffuse, "seed": a.seed}})
    if a.wind:
        steps.append({"op": "stylize.wind", "params": {"length": a.wind, "direction": a.direction}})
    if a.oil_paint:
        steps.append({"op": "stylize.oil", "params": {"radius": a.oil_paint}})
    if a.clouds:
        steps.append({"op": "stylize.clouds", "params": {"seed": a.seed, "scale": a.clouds,
                                                         "fg": hexcol(a.fg), "bg": hexcol(a.bg)}})
    if not steps:
        raise SystemExit("stylize: give --crystallize, --halftone, --trace-contour, --diffuse, --wind, "
                         "--oil-paint or --clouds")
    return core.edit_command(a, "stylize", with_mask(a, steps))


def cmd_blurfx(a):
    steps = []
    if a.spin is not None:
        steps.append({"op": "blurfx.radial", "params": {"mode": "spin", "amount": a.spin, "samples": a.samples}})
    if a.zoom is not None:
        steps.append({"op": "blurfx.radial", "params": {"mode": "zoom", "amount": a.zoom, "samples": a.samples}})
    if a.surface:
        r, t = floats(a.surface, 2)
        steps.append({"op": "blurfx.surface", "params": {"radius": int(r), "threshold": t}})
    if not steps:
        raise SystemExit("blurfx: give --spin, --zoom or --surface")
    return core.edit_command(a, "blurfx", with_mask(a, steps))


def cmd_tonebrush(a):
    p = {"mode": a.mode, "exposure": a.exposure, "range": a.range, "sponge": a.sponge}
    return core.edit_command(a, "tonebrush", with_mask(a, [{"op": "tonebrush", "params": p}]))


def add_commands(sub, edit):
    p = edit("warpfx", cmd_warpfx, "wave/ripple, spherize, zigzag, lens correction (rung 1)")
    p.add_argument("--wave", help="AMP,WAVELENGTH in px (Ripple = small amp, sine)")
    p.add_argument("--wave-type", choices=("sine", "triangle", "square"), default="sine")
    p.add_argument("--axis", choices=("both", "x", "y"), default="both")
    p.add_argument("--spherize", type=float, help="-1..1 (positive bulges out)")
    p.add_argument("--zigzag", type=float, help="degrees of pond-ripple rotation")
    p.add_argument("--ridges", type=float, default=5.0)
    p.add_argument("--lens", help="k1[,k2] radial terms (k1 > 0 removes barrel)")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("stylize", cmd_stylize, "crystallize, color halftone, trace contour, diffuse, wind, oil paint, "
             "clouds (rung 1)")
    p.add_argument("--crystallize", type=int, help="cell size in px")
    p.add_argument("--halftone", type=float, help="dot cell size in px")
    p.add_argument("--trace-contour", type=float, help="level 0..255")
    p.add_argument("--edge", choices=("upper", "lower"), default="upper")
    p.add_argument("--diffuse", type=int, help="radius in px")
    p.add_argument("--wind", type=float, help="streak length in px")
    p.add_argument("--direction", choices=("right", "left"), default="right")
    p.add_argument("--oil-paint", type=int, help="Kuwahara radius in px")
    p.add_argument("--clouds", type=float, help="largest cloud size in px (replaces the colour)")
    p.add_argument("--fg", default="#000000")
    p.add_argument("--bg", default="#ffffff")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("blurfx", cmd_blurfx, "radial (spin, zoom) and surface blur (rung 1)")
    p.add_argument("--spin", type=float, help="arc in degrees")
    p.add_argument("--zoom", type=float, help="0..1 ray length fraction")
    p.add_argument("--samples", type=int, default=16)
    p.add_argument("--surface", help="RADIUS,THRESHOLD (threshold in 0..255 levels)")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("tonebrush", cmd_tonebrush, "dodge, burn, sponge over a mask (rung 1)")
    p.add_argument("--mode", choices=("dodge", "burn", "sponge"), required=True)
    p.add_argument("--range", choices=("shadows", "midtones", "highlights"), default="midtones")
    p.add_argument("--exposure", type=float, default=0.5, help="0..1 (sponge: flow)")
    p.add_argument("--sponge", choices=("saturate", "desaturate"), default="desaturate")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white (the brush stroke)")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "warpfx (wave, spherize, zigzag, lens correction)": (1, "own NumPy"),
    "stylize (crystallize, halftone, trace contour, diffuse, wind, oil paint, clouds)": (1, "own NumPy"),
    "blurfx (spin, zoom, surface), tonebrush (dodge, burn, sponge)": (1, "own NumPy"),
})
