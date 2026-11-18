"""Batch 9 (0.10.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

tone:   Auto Tone / Auto Contrast / Auto Color, Vibrance, Shadows/Highlights, Match Color (Reinhard in Lab).
effect: Add Noise, Emboss, Find Edges.
canvas: Canvas Size (anchor, fill or transparent), Trim (transparent or corner colour).
Own NumPy only. Ops work on encoded values like the batch 8 filters, keep alpha, take --mask
(not canvas: it changes the size) and --recipe, and replay through `phw run`.
"""
import numpy as np

from . import core
from .core import OPS, floats
from .masks import rgb_to_lab

LUMA = core.LUMA


# ---------------------------------------------------------------- helpers
def lab_to_rgb(lab):
    """CIE Lab (D65) to encoded sRGB 0..1 (unclipped), inverse of masks.rgb_to_lab."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    e, k = 216 / 24389, 24389 / 27
    xr = np.where(fx ** 3 > e, fx ** 3, (116 * fx - 16) / k)
    yr = np.where(L > k * e, fy ** 3, L / k)
    zr = np.where(fz ** 3 > e, fz ** 3, (116 * fz - 16) / k)
    xyz = np.stack([xr * 0.95047, yr, zr * 1.08883], -1)
    m = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560],
                  [0.0556434, -0.2040259, 1.0572252]])
    lin = xyz @ m.T
    return core.to_enc(np.clip(lin, 0, None)).astype(np.float32)


def luma(c):
    return (c[..., :3] * LUMA).sum(axis=2) if c.shape[2] >= 3 else c[..., 0]


def pct(v, clip):
    """Low and high percentiles of v with `clip` percent cut at each end."""
    lo, hi = np.percentile(v, [clip, 100 - clip])
    return float(lo), float(hi)


def stretch(v, lo, hi):
    return np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1)


def stats_lab(c):
    lab = rgb_to_lab(np.repeat(c, 3, axis=2) if c.shape[2] == 1 else c[..., :3]).reshape(-1, 3)
    return [float(x) for x in lab.mean(0)], [float(x) for x in lab.std(0)]


# ---------------------------------------------------------------- tone ops
def op_auto(img, p, used):
    """tone: per-channel black/white points; contrast: one pair for all channels (hue kept);
    color: per-channel points, then a per-channel gamma so each channel's mean meets the luma mean."""
    kind, clip = p.get("kind", "tone"), float(p.get("clip", 0.1))
    c = img.color()
    if kind == "contrast":
        lo, hi = pct(c, clip)
        out = stretch(c, lo, hi)
    else:
        out = np.stack([stretch(c[..., i], *pct(c[..., i], clip)) for i in range(c.shape[2])], axis=2)
        if kind == "color" and out.shape[2] >= 3:
            target = float(np.clip(luma(out).mean(), 0.02, 0.98))
            for i in range(3):
                m = float(np.clip(out[..., i].mean(), 0.02, 0.98))
                out[..., i] = out[..., i] ** (np.log(target) / np.log(m))
        elif kind not in ("tone", "color"):
            raise ValueError(f"unknown auto kind {kind}")
    used.add("tone.auto", 1, f"NumPy auto {kind} ({clip}% clip)")
    return img.with_color(out.astype(np.float32))


def op_vibrance(img, p, used):
    """Chroma gain (1 + v * (1 - s)) around luma, s = max - min: dull colours move most, greys stay."""
    v = float(p["amount"])
    used.add("tone.vibrance", 1, "NumPy chroma gain weighted by 1 - saturation")
    c = img.color()
    if c.shape[2] < 3:
        img.notes.append("vibrance skipped: greyscale image")
        return img
    rgb = c[..., :3]
    y = luma(rgb)[..., None]
    s = (rgb.max(axis=2) - rgb.min(axis=2))[..., None]
    out = y + (rgb - y) * (1 + v * (1 - s))
    return img.with_color(np.clip(np.concatenate([out, c[..., 3:]], axis=2), 0, 1).astype(np.float32))


def op_shadows_highlights(img, p, used):
    """Luma L lifted toward sqrt(L) where the blurred surround is below mid-grey (shadows), pulled
    toward L^2 where it is above (highlights); colour scaled by L'/L so hue and saturation ratios hold."""
    s, h, r = float(p.get("shadows", 0)), float(p.get("highlights", 0)), float(p.get("radius", 30))
    c = img.color()
    L = luma(c)
    base = core.gaussian_blur(L.astype(np.float32), r, used)
    ws = np.clip(1 - base / 0.5, 0, 1) ** 2
    wh = np.clip((base - 0.5) / 0.5, 0, 1) ** 2
    L2 = L + s * ws * (np.sqrt(L) - L) - h * wh * (L - L * L)
    k = np.where(L > 1e-6, L2 / np.maximum(L, 1e-6), 1.0)[..., None]
    used.add("tone.shadows_highlights", used.items[-1]["rung"], "luma remap weighted by blurred surround")
    return img.with_color(np.clip(c * k, 0, 1).astype(np.float32))


def op_match(img, p, used):
    """Reinhard et al. 2001 colour transfer in CIE Lab: per channel (x - mu_s) / sd_s * sd_t + mu_t,
    blended by `amount`. Target statistics are stored in the step, so a replay needs no reference file."""
    mt, st = np.array(p["mean"]), np.array(p["std"])
    amt = float(p.get("amount", 1.0))
    used.add("tone.match", 1, "NumPy Reinhard Lab statistics transfer")
    c = img.color()
    rgb = np.repeat(c, 3, axis=2) if c.shape[2] == 1 else c[..., :3]
    lab = rgb_to_lab(rgb)
    ms, ss = lab.reshape(-1, 3).mean(0), lab.reshape(-1, 3).std(0)
    lab2 = (lab - ms) / np.maximum(ss, 1e-6) * st + mt
    out = lab_to_rgb(lab * (1 - amt) + lab2 * amt)
    if c.shape[2] == 1:
        out = luma(out)[..., None]
    elif c.shape[2] > 3:
        out = np.concatenate([out, c[..., 3:]], axis=2)
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- effect ops
def op_noise(img, p, used):
    amt, dist = float(p["amount"]), p.get("dist", "gaussian")
    rng = np.random.default_rng(int(p.get("seed", 0)))
    c = img.color()
    shape = c.shape[:2] + ((1,) if p.get("mono") else (c.shape[2],))
    if dist == "gaussian":
        n = rng.normal(0, amt, shape)
    elif dist == "uniform":       # same standard deviation as the gaussian setting
        n = rng.uniform(-amt * np.sqrt(3), amt * np.sqrt(3), shape)
    else:
        raise ValueError(f"unknown noise {dist}")
    used.add("effect.noise", 1, f"NumPy seeded {dist} noise")
    return img.with_color(np.clip(c + n, 0, 1).astype(np.float32))


def sobel(ch):
    pd = np.pad(ch, 1, mode="edge")
    h, w = ch.shape
    s = lambda y, x: pd[y:y + h, x:x + w]  # noqa: E731
    gx = (s(0, 2) + 2 * s(1, 2) + s(2, 2)) - (s(0, 0) + 2 * s(1, 0) + s(2, 0))
    gy = (s(2, 0) + 2 * s(2, 1) + s(2, 2)) - (s(0, 0) + 2 * s(0, 1) + s(0, 2))
    return gx / 4, gy / 4     # unit step -> 1


def op_emboss(img, p, used):
    """Grey relief: 0.5 + height * directional derivative of luma (light from `angle`, degrees ccw)."""
    a = np.radians(float(p.get("angle", 135)))
    gx, gy = sobel(luma(img.color()).astype(np.float32))
    v = 0.5 + float(p.get("height", 1.0)) * (gx * np.cos(a) - gy * np.sin(a)) / 2
    used.add("effect.emboss", 1, "NumPy Sobel relief")
    return img.with_color(np.repeat(np.clip(v, 0, 1)[..., None], img.nc, axis=2).astype(np.float32))


def op_find_edges(img, p, used):
    """Per channel 1 - Sobel magnitude: flat areas white, edges dark (as Photoshop's Find Edges)."""
    used.add("effect.find_edges", 1, "NumPy inverted Sobel magnitude")
    c = img.color()
    out = np.stack([1 - np.hypot(*sobel(c[..., i])) for i in range(c.shape[2])], axis=2)
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- canvas ops
ANCHORS = {"tl": (0, 0), "t": (0.5, 0), "tr": (1, 0), "l": (0, 0.5), "c": (0.5, 0.5), "r": (1, 0.5),
           "bl": (0, 1), "b": (0.5, 1), "br": (1, 1)}


def op_canvas(img, p, used):
    W, H = (int(v) for v in p["size"])
    ax, ay = ANCHORS[p.get("anchor", "c")]
    h, w = img.px.shape[:2]
    ox, oy = int(round((W - w) * ax)), int(round((H - h) * ay))
    fill = p.get("fill")
    if fill is None and not img.alpha:          # transparent fill: add an alpha channel
        img = img.copy(px=np.concatenate([img.px, np.ones(img.px.shape[:2] + (1,), np.float32)], axis=2),
                       alpha=True)
    bg = np.zeros(img.px.shape[2], np.float32)
    if fill is not None:
        col = list(fill)[:img.nc] if img.nc >= 3 else [float(np.dot(fill, LUMA))]
        bg[:img.nc] = col
        if img.alpha:
            bg[-1] = 1.0
    out = np.tile(bg, (H, W, 1)).astype(np.float32)
    sy0, sx0 = max(0, -oy), max(0, -ox)
    dy0, dx0 = max(0, oy), max(0, ox)
    ch, cw = min(h - sy0, H - dy0), min(w - sx0, W - dx0)
    if ch > 0 and cw > 0:
        out[dy0:dy0 + ch, dx0:dx0 + cw] = img.px[sy0:sy0 + ch, sx0:sx0 + cw]
    used.add("canvas.size", 1, "NumPy pad/crop around an anchor")
    return img.copy(px=out)


def op_trim(img, p, used):
    """Cut the border: transparent pixels (alpha <= tol) or pixels within tol of the top-left colour."""
    tol = float(p.get("tolerance", 0)) / 255.0
    by = p.get("by", "auto")
    if by == "auto":
        by = "alpha" if img.alpha else "corner"
    if by == "alpha":
        if not img.alpha:
            raise ValueError("trim --by alpha: image has no alpha")
        keep = img.px[..., -1] > tol
    else:
        c = img.color()
        keep = np.abs(c - c[0, 0]).max(axis=2) > tol + 1e-7
    used.add("canvas.trim", 1, f"NumPy bounding box ({by})")
    if not keep.any():
        img.notes.append("trim: nothing but border; image unchanged")
        return img
    ys, xs = np.nonzero(keep)
    return img.copy(px=img.px[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy())


OPS.update({"tone.auto": op_auto, "tone.vibrance": op_vibrance, "tone.shadows_highlights": op_shadows_highlights,
            "tone.match": op_match, "effect.noise": op_noise, "effect.emboss": op_emboss,
            "effect.find_edges": op_find_edges, "canvas.size": op_canvas, "canvas.trim": op_trim})


# ---------------------------------------------------------------- commands
def with_mask(a, steps):
    if getattr(a, "mask", None):
        for s in steps:
            s["mask"] = str(core.Path(a.mask).resolve())
    return steps


def cmd_tone(a):
    steps = []
    if a.auto:
        steps.append({"op": "tone.auto", "params": {"kind": a.auto, "clip": a.clip}})
    if a.match:
        ref = core.load(a.match)
        mean, std = stats_lab(ref.color())
        steps.append({"op": "tone.match", "params": {"mean": mean, "std": std, "amount": a.amount,
                                                     "reference": str(a.match)}})
    if a.shadows or a.highlights:
        steps.append({"op": "tone.shadows_highlights",
                      "params": {"shadows": a.shadows, "highlights": a.highlights, "radius": a.sh_radius}})
    if a.vibrance:
        steps.append({"op": "tone.vibrance", "params": {"amount": a.vibrance}})
    if not steps:
        raise SystemExit("tone: give --auto, --match, --shadows/--highlights or --vibrance")
    return core.edit_command(a, "tone", with_mask(a, steps))


def cmd_effect(a):
    steps = []
    if a.noise:
        steps.append({"op": "effect.noise", "params": {"amount": a.noise / 255.0, "dist": a.dist,
                                                       "mono": a.mono, "seed": a.seed}})
    if a.emboss is not None:
        steps.append({"op": "effect.emboss", "params": {"angle": a.emboss, "height": a.height}})
    if a.find_edges:
        steps.append({"op": "effect.find_edges", "params": {}})
    if not steps:
        raise SystemExit("effect: give --noise, --emboss or --find-edges")
    return core.edit_command(a, "effect", with_mask(a, steps))


def hexcol(s):
    h = s.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def cmd_canvas(a):
    steps = []
    if a.trim:
        steps.append({"op": "canvas.trim", "params": {"by": a.by, "tolerance": a.tolerance}})
    if a.size:
        size = [int(v) for v in floats(a.size, 2)]
        if a.relative:
            im = core.load(a.input)
            h, w = im.px.shape[:2]
            size = [w + size[0], h + size[1]]
        steps.append({"op": "canvas.size", "params": {"size": size, "anchor": a.anchor,
                                                      "fill": hexcol(a.fill) if a.fill else None}})
    if not steps:
        raise SystemExit("canvas: give --size and/or --trim")
    return core.edit_command(a, "canvas", steps)


def add_commands(sub, edit):
    p = edit("tone", cmd_tone, "auto tone/contrast/color, vibrance, shadows/highlights, match color (rung 1)")
    p.add_argument("--auto", choices=("tone", "contrast", "color"))
    p.add_argument("--clip", type=float, default=0.1, help="percent clipped at each end for --auto")
    p.add_argument("--vibrance", type=float, help="-1..1: chroma gain weighted toward dull colours")
    p.add_argument("--shadows", type=float, default=0.0, help="0..1 lift of dark surroundings")
    p.add_argument("--highlights", type=float, default=0.0, help="0..1 pull-down of bright surroundings")
    p.add_argument("--sh-radius", type=float, default=30.0, help="surround blur sigma in px")
    p.add_argument("--match", help="reference image: transfer its Lab mean and spread (Reinhard)")
    p.add_argument("--amount", type=float, default=1.0, help="0..1 strength of --match")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("effect", cmd_effect, "add noise, emboss, find edges (rung 1)")
    p.add_argument("--noise", type=float, help="standard deviation in 0..255 units")
    p.add_argument("--dist", choices=("gaussian", "uniform"), default="gaussian")
    p.add_argument("--mono", action="store_true", help="same noise on every channel")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--emboss", type=float, help="light angle in degrees counter-clockwise (135 = top left)")
    p.add_argument("--height", type=float, default=1.0, help="emboss relief gain")
    p.add_argument("--find-edges", action="store_true")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("canvas", cmd_canvas, "canvas size around an anchor, trim borders (rung 1)")
    p.add_argument("--size", help="W,H in px (or dW,dH with --relative); smaller crops")
    p.add_argument("--relative", action="store_true")
    p.add_argument("--anchor", choices=tuple(ANCHORS), default="c")
    p.add_argument("--fill", help="'#rrggbb'; default transparent")
    p.add_argument("--trim", action="store_true", help="cut transparent or corner-coloured border (before --size)")
    p.add_argument("--by", choices=("auto", "alpha", "corner"), default="auto")
    p.add_argument("--tolerance", type=float, default=0.0, help="0..255 for --trim")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "tone (auto, vibrance, shadows/highlights, match color)": (1, "own NumPy"),
    "effect (add noise, emboss, find edges)": (1, "own NumPy"),
    "canvas (size, trim)": (1, "own NumPy"),
})
