"""Batch 15 (0.16.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

gradient:     Gradient tool: linear, radial, angle, reflected, diamond between two points, colour
              stops (#rrggbb or #rrggbbaa), blend mode and opacity. `layers` recipes also take
              {"type": "gradient"} and {"type": "pattern"} fill layers (built here).
pattern:      Pattern fill: a tile repeated over the canvas (scale, offset), blend and opacity.
layerstyle:   Layer styles on the image's alpha: colour and gradient overlay, inner shadow,
              inner glow, outer glow, bevel and emboss (inner bevel).
blendif:      Blend If: put a top layer over the image with This Layer / Underlying Layer ranges
              (split sliders give a ramp), on grey or one channel.
replacecolor: Replace Color: pick a colour (point or hex), fuzziness, hue / saturation / lightness.
focusarea:    Focus Area select: a mask of the in-focus parts (local high-frequency energy, Otsu).
erase:        Eraser along a stroke, Magic Eraser (flood by tolerance, contiguous or global).
bucket:       Paint Bucket: flood fill a colour by tolerance, contiguous or global.
Own NumPy and Pillow only; edit ops keep alpha, take --mask/--recipe and replay through `phw run`.
"""
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import compose, core, masks
from .core import OPS, floats
from .grading import with_mask
from .toolbox import stroke_weight


# ---------------------------------------------------------------- helpers
def hexcol4(s):
    """'#rrggbb' or '#rrggbbaa' (or 'r,g,b[,a]' in 0..255) to 4 floats 0..1."""
    s = str(s).strip()
    if "," in s:
        v = [x / 255.0 for x in floats(s)]
    else:
        h = s.lstrip("#")
        if len(h) not in (6, 8):
            raise ValueError(f"colour {s!r}: use #rrggbb or #rrggbbaa")
        v = [int(h[i:i + 2], 16) / 255.0 for i in range(0, len(h), 2)]
    return v + [1.0] * (4 - len(v))


def colours(s):
    return [hexcol4(t) for t in str(s).replace(";", " ").split()]


def rgba_of(img):
    """Straight RGB (3 channels) and alpha (HxWx1) of any image."""
    c = img.color()
    c = np.repeat(c, 3, 2) if c.shape[2] == 1 else c[..., :3]
    a = img.px[..., -1:] if img.alpha else np.ones(c.shape[:2] + (1,), np.float32)
    return c.astype(np.float64), a.astype(np.float64)


def with_rgba(img, c, a, force_alpha=False):
    """Back to an Img: keep 3 colour channels; alpha kept if the source had one or force_alpha."""
    c = np.clip(c, 0, 1).astype(np.float32)
    if img.alpha or force_alpha:
        return img.copy(px=np.concatenate([c, np.clip(a, 0, 1).astype(np.float32)], 2), alpha=True)
    return img.copy(px=c, alpha=False)


def put_over(img, cs, as_, mode="normal"):
    """Composite (cs, as_) over the image; pixels with as_ == 0 are bit-exact."""
    c, a = rgba_of(img)
    oc, oa = compose.composite_over(c.astype(np.float32), a.astype(np.float32), cs.astype(np.float32),
                                    as_.astype(np.float32), mode)
    return with_rgba(img, oc, oa)


# ---------------------------------------------------------------- gradient
def gradient_t(h, w, kind, p0, p1):
    """Gradient position t (0 at p0, 1 at p1) per pixel centre."""
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L2 = max(dx * dx + dy * dy, 1e-12)
    L = math.sqrt(L2)
    u = ((X - p0[0]) * dx + (Y - p0[1]) * dy) / L2  # along, in units of L
    v = (-(X - p0[0]) * dy + (Y - p0[1]) * dx) / L2  # across
    if kind == "linear":
        t = u
    elif kind == "radial":
        t = np.hypot(X - p0[0], Y - p0[1]) / L
    elif kind == "angle":
        t = (np.arctan2(v, u) % (2 * math.pi)) / (2 * math.pi)
    elif kind == "reflected":
        t = np.abs(u)
    elif kind == "diamond":
        t = np.abs(u) + np.abs(v)
    else:
        raise ValueError(f"gradient: unknown kind {kind}")
    return np.clip(t, 0, 1)


def ramp(t, stops, positions=None):
    """RGBA at t from colour stops (evenly spaced unless positions given), straight colour lerp."""
    st = np.asarray(stops, np.float64)
    pos = np.asarray(positions if positions else np.linspace(0, 1, len(st)), np.float64)
    if len(st) < 2 or len(pos) != len(st):
        raise ValueError("gradient: give at least two colours (and one position per colour)")
    return np.stack([np.interp(t, pos, st[:, k]) for k in range(4)], -1)


def gradient_rgba(h, w, p):
    t = gradient_t(h, w, p.get("kind", "linear"), p["start"], p["end"])
    if p.get("reverse"):
        t = 1 - t
    return ramp(t, p["colors"], p.get("positions"))


def op_gradient(img, p, used):
    h, w = img.px.shape[:2]
    g = gradient_rgba(h, w, p)
    used.add("gradient." + p.get("kind", "linear"), 1, "own NumPy gradient")
    return put_over(img, g[..., :3], g[..., 3:] * float(p.get("opacity", 1.0)), p.get("blend", "normal"))


def pattern_rgba(h, w, p):
    tile = Image.open(p["tile"]).convert("RGBA")
    s = float(p.get("scale", 1.0))
    if s != 1.0:
        tile = tile.resize((max(1, round(tile.width * s)), max(1, round(tile.height * s))),
                           Image.NEAREST if s >= 1 else Image.LANCZOS)
    t = np.asarray(tile, np.float64) / 255.0
    ox, oy = (int(round(v)) for v in p.get("offset", [0, 0]))
    th, tw = t.shape[:2]
    Y, X = np.mgrid[0:h, 0:w]
    return t[(Y - oy) % th, (X - ox) % tw]


def op_pattern(img, p, used):
    h, w = img.px.shape[:2]
    g = pattern_rgba(h, w, p)
    used.add("pattern", 1, "own NumPy tiling")
    return put_over(img, g[..., :3], g[..., 3:] * float(p.get("opacity", 1.0)), p.get("blend", "normal"))


def fill_layer_px(L, base, w, h):
    """compose hook: RGBA canvas of a {"type": "gradient"|"pattern"} fill layer."""
    if L["type"] == "gradient":
        p = {"kind": L.get("kind", "linear"), "start": L.get("start", [0, 0]), "end": L.get("end", [w, 0]),
             "colors": [hexcol4(c) if isinstance(c, str) else list(compose.colour4(c)) for c in L["colors"]],
             "positions": L.get("positions"), "reverse": L.get("reverse", False)}
        return gradient_rgba(h, w, p).astype(np.float32)
    p = {"tile": str(compose.resolve(base, L["file"])), "scale": L.get("scale", 1.0), "offset": L.get("offset", [0, 0])}
    return pattern_rgba(h, w, p).astype(np.float32)


# ---------------------------------------------------------------- layer styles
def blur1(m, s):
    return core.gaussian_blur(m.astype(np.float32), float(s)).astype(np.float64) if s > 0 else m


def shift(m, dx, dy, fill):
    h, w = m.shape
    out = np.full_like(m, fill)
    xs0, xs1 = max(0, -dx), min(w, w - dx)
    ys0, ys1 = max(0, -dy), min(h, h - dy)
    if xs1 > xs0 and ys1 > ys0:
        out[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx] = m[ys0:ys1, xs0:xs1]
    return out


def screen(a, b):
    return 1 - (1 - a) * (1 - b)


def op_layerstyle(img, p, used):
    """Photoshop order: outer glow under the layer; on the layer (clipped to its alpha) inner
    shadow (multiply), inner glow (screen), bevel highlight (screen) and shadow (multiply),
    gradient overlay, then colour overlay. Each style is {"color", "opacity", "size", ...}."""
    c, a = rgba_of(img)
    A = a[..., 0]
    names = []
    if p.get("inner_shadow"):
        s = p["inner_shadow"]
        ang = math.radians(float(s.get("angle", 120)))
        d = float(s.get("distance", 4))
        dx, dy = int(round(-d * math.cos(ang))), int(round(d * math.sin(ang)))
        k = np.clip(blur1(1 - shift(A, dx, dy, 1.0), float(s.get("size", 4)) / 2), 0, 1) * A
        k = (k * float(s.get("opacity", 0.75)))[..., None]
        col = np.asarray(hexcol4(s.get("color", "#000000"))[:3])
        c = c * (1 - k) + c * col * k
        names.append("inner shadow")
    if p.get("inner_glow"):
        s = p["inner_glow"]
        k = np.clip(1 - blur1(A, float(s.get("size", 5)) / 2), 0, 1) * A
        k = np.clip(2 * k, 0, 1) * float(s.get("opacity", 0.75))
        col = np.asarray(hexcol4(s.get("color", "#ffffbe"))[:3])
        c = c * (1 - k[..., None]) + screen(c, col) * k[..., None]
        names.append("inner glow")
    if p.get("bevel"):
        s = p["bevel"]
        size, depth = float(s.get("size", 5)), float(s.get("depth", 1.0))
        H = blur1(A, size / 2) * size * depth
        gy, gx = np.gradient(H)
        ang, alt = math.radians(float(s.get("angle", 120))), math.radians(float(s.get("altitude", 30)))
        Lx, Ly, Lz = math.cos(ang) * math.cos(alt), -math.sin(ang) * math.cos(alt), math.sin(alt)
        n = np.sqrt(gx * gx + gy * gy + 1)
        shade = (-gx * Lx - gy * Ly + Lz) / n - Lz  # 0 on flat ground
        hi = np.clip(shade, 0, 1) / max(1 - Lz, 1e-6) * float(s.get("highlight", 0.75)) * A
        lo = np.clip(-shade, 0, 1) / max(Lz, 1e-6) * float(s.get("shadow", 0.75)) * A
        hi, lo = np.clip(hi, 0, 1)[..., None], np.clip(lo, 0, 1)[..., None]
        c = c * (1 - hi) + screen(c, 1.0) * hi
        c = c * (1 - lo)
        names.append("bevel")
    if p.get("gradient_overlay"):
        s = p["gradient_overlay"]
        h, w = A.shape
        g = gradient_rgba(h, w, {"kind": s.get("kind", "linear"), "start": s.get("start", [0, 0]),
                                 "end": s.get("end", [0, h]), "colors": s["colors"]})
        k = g[..., 3:] * float(s.get("opacity", 1.0))
        c = c * (1 - k) + g[..., :3] * k
        names.append("gradient overlay")
    if p.get("color_overlay"):
        s = p["color_overlay"]
        col = np.asarray(hexcol4(s.get("color", "#ff0000")))
        k = col[3] * float(s.get("opacity", 1.0))
        c = c * (1 - k) + col[:3] * k
        names.append("colour overlay")
    c0, _ = rgba_of(img)
    c = np.where(a > 0, c, c0)  # nothing outside the layer's pixels changes
    if p.get("outer_glow"):
        s = p["outer_glow"]
        g = np.clip(blur1(masks.morph(A.astype(np.float32), float(s.get("spread", 0)), True), float(s.get("size", 5)) / 2)
                    * 2, 0, 1) * float(s.get("opacity", 0.75))
        col = np.asarray(hexcol4(s.get("color", "#ffffbe"))[:3])
        oc, oa = compose.composite_over(np.broadcast_to(col, c.shape).astype(np.float32), g[..., None].astype(np.float32),
                                        c.astype(np.float32), a.astype(np.float32))
        used.add("layerstyle", 1, "own NumPy styles: " + ", ".join(names + ["outer glow"]))
        return with_rgba(img, oc, oa, force_alpha=True)
    used.add("layerstyle", 1, "own NumPy styles: " + ", ".join(names))
    return with_rgba(img, c, a)


# ---------------------------------------------------------------- blend if
def band(v, r):
    """Blend If weight of values v (0..255) for sliders b0,b1 (black split) w0,w1 (white split)."""
    b0, b1, w0, w1 = (float(x) for x in r)
    lo = np.clip((v - b0) / (b1 - b0), 0, 1) if b1 > b0 else (v >= b0).astype(np.float64)
    hi = np.clip((w1 - v) / (w1 - w0), 0, 1) if w1 > w0 else (v <= w0).astype(np.float64)
    return lo * hi


def channel_of(c, ch):
    if ch == "gray":
        return (c * core.LUMA.astype(np.float64)).sum(2) * 255
    return c[..., "rgb".index(ch)] * 255


def op_blendif(img, p, used):
    top = core.load(p["layer"], used)
    tc, ta = rgba_of(top)
    if tc.shape[:2] != img.px.shape[:2]:
        raise ValueError(f"blendif: layer is {tc.shape[1]}x{tc.shape[0]}, image is {img.px.shape[1]}x{img.px.shape[0]}")
    bc, _ = rgba_of(img)
    ch = p.get("channel", "gray")
    k = band(channel_of(tc, ch), p.get("this", [0, 0, 255, 255])) * band(channel_of(bc, ch), p.get("under", [0, 0, 255, 255]))
    used.add("blendif", 1, "own Blend If ranges")
    return put_over(img, tc, ta * k[..., None] * float(p.get("opacity", 1.0)), p.get("blend", "normal"))


# ---------------------------------------------------------------- replace color
def op_replacecolor(img, p, used):
    """Selection weight from the Lab distance d to the target: 1 up to fuzziness / 2, falling to 0
    at fuzziness (fuzziness 0: exact colour only). Hue turns by `hue` degrees; saturation and
    lightness move toward 0 or 1 by their percentage, as Photoshop's sliders."""
    c, a = rgba_of(img)
    lab = masks.rgb_to_lab(c.astype(np.float32)).astype(np.float64)
    tgt = masks.rgb_to_lab(np.asarray(p["color"][:3], np.float32).reshape(1, 1, 3)).astype(np.float64)[0, 0]
    d = np.sqrt(((lab - tgt) ** 2).sum(2))
    f = float(p.get("fuzziness", 40))
    wgt = (d <= 1e-3).astype(np.float64) if f <= 0 else np.clip((f - d) / (f / 2), 0, 1)
    hh, ss, vv = core.rgb_to_hsv(c)
    hh = hh + float(p.get("hue", 0)) / 360.0
    sat, lig = float(p.get("saturation", 0)) / 100, float(p.get("lightness", 0)) / 100
    ss = ss * (1 + sat) if sat < 0 else ss + (1 - ss) * sat
    adj = core.hsv_to_rgb(hh, np.clip(ss, 0, 1), vv).astype(np.float64)
    adj = adj * (1 + lig) if lig < 0 else adj + (1 - adj) * lig
    out = np.where(wgt[..., None] > 0, c + wgt[..., None] * (adj - c), c)
    used.add("replacecolor", 1, "own Lab distance selection + HSL shift")
    return with_rgba(img, out, a)


# ---------------------------------------------------------------- focus area
def otsu(v, bins=256):
    hist, edges = np.histogram(v, bins=bins)
    mids = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids)
    mu0 = m0 / np.maximum(w0, 1)
    mu1 = (m0[-1] - m0) / np.maximum(w1, 1)
    return float(mids[np.argmax(w0 * w1 * (mu0 - mu1) ** 2)])


def focus_mask(img, radius=6.0, threshold=None, soft=0.0, used=None):
    c, _ = rgba_of(img)
    y = (c * core.LUMA.astype(np.float64)).sum(2)
    lap = np.abs(4 * y - np.roll(y, 1, 0) - np.roll(y, -1, 0) - np.roll(y, 1, 1) - np.roll(y, -1, 1))
    lap[0], lap[-1], lap[:, 0], lap[:, -1] = lap[1], lap[-2], lap[:, 1], lap[:, -2]
    e = np.log(blur1(lap * lap, radius) + 1e-8)
    t = otsu(e) if threshold is None else math.log(threshold)
    m = (e > t).astype(np.float64) if soft <= 0 else np.clip((e - t) / soft + 0.5, 0, 1)
    # the window spreads sharp energy about 2 sigma into soft areas, never the other way: pull back
    m = masks.morph(m.astype(np.float32), round(2 * radius), False).astype(np.float64)
    if used:
        used.add("focusarea", 1, "own Laplacian energy + Otsu")
    return m, t


def cmd_focusarea(a):
    t0 = time.time()
    used = core.Used()
    img = core.load(a.input, used)
    m, t = focus_mask(img, a.radius, a.threshold, a.soft, used)
    out = core.out_for(a.input, a.output, "focus", ".png")
    out = masks.save_mask(m, core.free_path(Path(out)), used)
    return {"command": "focusarea", "input": str(a.input), "output": str(out), "threshold_log": round(t, 4),
            "selected": round(float(m.mean()), 4), "seconds": round(time.time() - t0, 3), "rung": used.rung(),
            "tool": used.tool(), "used": used.items}


# ---------------------------------------------------------------- eraser, magic eraser, paint bucket
def region(c, at, tol, contiguous, used):
    """Pixels within `tol` (0..255, max channel distance) of the colour at `at`; contiguous = 4-connected."""
    x, y = (int(round(v)) for v in at)
    d = np.abs(c - c[y, x]).max(2) * 255
    cand = d <= tol + 1e-6
    if not contiguous:
        return cand
    seeds = np.zeros_like(cand)
    seeds[y, x] = True
    return masks.flood_region(cand, seeds, used)


def op_erase(img, p, used):
    c, a = rgba_of(img)
    if p.get("magic"):
        reg = region(c, p["magic"], float(p.get("tolerance", 32)), p.get("contiguous", True), used)
        k = reg.astype(np.float64) * float(p.get("strength", 1.0))
        used.add("erase.magic", 1, "own flood by tolerance -> alpha 0")
    else:
        k = stroke_weight(c.shape[:2], p["points"], float(p.get("radius", 8)), float(p.get("hardness", 0.8)))
        k = k * float(p.get("strength", 1.0))
        used.add("erase.brush", 1, "own soft round eraser")
    na = np.where(k[..., None] > 0, a * (1 - k[..., None]), a)
    return with_rgba(img, c, na, force_alpha=True)


def op_bucket(img, p, used):
    c, a = rgba_of(img)
    reg = region(c, p["at"], float(p.get("tolerance", 32)), p.get("contiguous", True), used)
    col = np.asarray(p["color"], np.float64)
    k = (reg * col[3] * float(p.get("opacity", 1.0)))[..., None]
    used.add("bucket", 1, "own flood fill by tolerance")
    if k.max() <= 0:
        return img.copy()
    return put_over(img, np.broadcast_to(col[:3], c.shape), k, p.get("blend", "normal"))


OPS.update({"gradient": op_gradient, "pattern": op_pattern, "layerstyle": op_layerstyle, "blendif": op_blendif,
            "replacecolor": op_replacecolor, "erase": op_erase, "bucket": op_bucket})


# ---------------------------------------------------------------- commands
def pts(s):
    return [floats(t, 2) for t in s.replace(";", " ").split()]


def cmd_gradient(a):
    p = {"kind": a.kind, "start": floats(a.start, 2), "end": floats(a.end, 2), "colors": colours(a.colors),
         "opacity": a.opacity, "blend": a.blend, "reverse": a.reverse}
    if a.positions:
        p["positions"] = floats(a.positions)
    return core.edit_command(a, "gradient", with_mask(a, [{"op": "gradient", "params": p}]))


def cmd_pattern(a):
    p = {"tile": str(Path(a.tile).resolve()), "scale": a.scale, "offset": floats(a.offset, 2), "opacity": a.opacity,
         "blend": a.blend}
    return core.edit_command(a, "pattern", with_mask(a, [{"op": "pattern", "params": p}]))


def style_arg(s, extra=None):
    """'key=value,key=value' to a style dict (color as #hex; numbers as floats)."""
    d = {}
    for kv in (s or "").split(","):
        if not kv.strip():
            continue
        k, _, v = kv.partition("=")
        k, v = k.strip(), v.strip()
        if k == "colors":
            d[k] = colours(v)
        elif k in ("color", "kind"):
            d[k] = v
        elif k in ("start", "end"):
            d[k] = floats(v.replace(" ", ";").replace(":", ";"), 2)
        else:
            d[k] = float(v)
    return d


def cmd_layerstyle(a):
    p = {}
    for k in ("color_overlay", "gradient_overlay", "inner_shadow", "inner_glow", "outer_glow", "bevel"):
        v = getattr(a, k)
        if v is not None:
            p[k] = style_arg(v)
    if not p:
        raise SystemExit("layerstyle: give one or more of --color-overlay, --gradient-overlay, --inner-shadow, "
                         "--inner-glow, --outer-glow, --bevel (each 'key=value,...' or '' for defaults)")
    if "gradient_overlay" in p and "colors" not in p["gradient_overlay"]:
        p["gradient_overlay"]["colors"] = colours("#000000 #ffffff")
    return core.edit_command(a, "layerstyle", with_mask(a, [{"op": "layerstyle", "params": p}]))


def cmd_blendif(a):
    p = {"layer": str(Path(a.layer).resolve()), "channel": a.channel, "this": floats(a.this, 4),
         "under": floats(a.under, 4), "opacity": a.opacity, "blend": a.blend}
    return core.edit_command(a, "blendif", with_mask(a, [{"op": "blendif", "params": p}]))


def cmd_replacecolor(a):
    if a.pick:
        img = core.load(a.input)
        c, _ = rgba_of(img)
        x, y = (int(round(v)) for v in floats(a.pick, 2))
        col = [float(v) for v in c[y, x]]
    elif a.color:
        col = hexcol4(a.color)[:3]
    else:
        raise SystemExit("replacecolor: give --pick x,y or --color #rrggbb")
    p = {"color": col, "fuzziness": a.fuzziness, "hue": a.hue, "saturation": a.saturation, "lightness": a.lightness}
    return core.edit_command(a, "replacecolor", with_mask(a, [{"op": "replacecolor", "params": p}]))


def cmd_erase(a):
    if a.magic:
        p = {"magic": floats(a.magic, 2), "tolerance": a.tolerance, "contiguous": not a.all, "strength": a.strength}
    elif a.stroke:
        p = {"points": pts(a.stroke), "radius": a.radius, "hardness": a.hardness, "strength": a.strength}
    else:
        raise SystemExit("erase: give --stroke 'x,y x,y' (Eraser) or --magic x,y (Magic Eraser)")
    return core.edit_command(a, "erase", with_mask(a, [{"op": "erase", "params": p}]), ".png")


def cmd_bucket(a):
    p = {"at": floats(a.at, 2), "color": hexcol4(a.color), "tolerance": a.tolerance, "contiguous": not a.all,
         "opacity": a.opacity, "blend": a.blend}
    return core.edit_command(a, "bucket", with_mask(a, [{"op": "bucket", "params": p}]))


def add_commands(sub, edit):
    def common(p, blend=True):
        p.add_argument("--opacity", type=float, default=1.0)
        if blend:
            p.add_argument("--blend", default="normal", help="blend mode (phw explain blend modes)")
        p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("gradient", cmd_gradient, "Gradient tool: linear/radial/angle/reflected/diamond (rung 1)")
    p.add_argument("--kind", choices=("linear", "radial", "angle", "reflected", "diamond"), default="linear")
    p.add_argument("--start", required=True, help="x,y where the first colour sits")
    p.add_argument("--end", required=True, help="x,y where the last colour sits")
    p.add_argument("--colors", default="#000000 #ffffff", help="'#rrggbb[aa] ...' stops, first to last")
    p.add_argument("--positions", help="stop positions 0..1, e.g. 0,0.3,1 (default even)")
    p.add_argument("--reverse", action="store_true")
    common(p)
    p = edit("pattern", cmd_pattern, "Pattern fill: repeat a tile over the image (rung 1)")
    p.add_argument("--tile", required=True, help="tile image")
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--offset", default="0,0", help="dx,dy of the tile origin")
    common(p)
    p = edit("layerstyle", cmd_layerstyle, "Layer styles: overlays, inner shadow/glow, outer glow, bevel (rung 1)")
    for k, h in (("color-overlay", "color=#rrggbb,opacity=1"),
                 ("gradient-overlay", "colors=#000 #fff,start=x:y,end=x:y,kind=linear,opacity=1"),
                 ("inner-shadow", "color,opacity=0.75,angle=120,distance=4,size=4"),
                 ("inner-glow", "color=#ffffbe,opacity=0.75,size=5"),
                 ("outer-glow", "color=#ffffbe,opacity=0.75,size=5,spread=0"),
                 ("bevel", "size=5,depth=1,angle=120,altitude=30,highlight=0.75,shadow=0.75")):
        p.add_argument("--" + k, nargs="?", const="", help=f"'{h}' ('' for defaults)")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("blendif", cmd_blendif, "Blend If: top layer over the image by tone ranges (rung 1)")
    p.add_argument("--layer", required=True, help="the top layer image (same size)")
    p.add_argument("--channel", choices=("gray", "r", "g", "b"), default="gray")
    p.add_argument("--this", default="0,0,255,255", help="This Layer sliders b0,b1,w0,w1 (split = ramp)")
    p.add_argument("--under", default="0,0,255,255", help="Underlying Layer sliders b0,b1,w0,w1")
    common(p)
    p = edit("replacecolor", cmd_replacecolor, "Replace Color: select by colour, shift hue/sat/lightness (rung 1)")
    p.add_argument("--pick", help="x,y to sample the colour")
    p.add_argument("--color", help="#rrggbb target")
    p.add_argument("--fuzziness", type=float, default=40.0, help="Lab distance where selection reaches 0 (0 = exact)")
    p.add_argument("--hue", type=float, default=0.0, help="degrees")
    p.add_argument("--saturation", type=float, default=0.0, help="-100..100")
    p.add_argument("--lightness", type=float, default=0.0, help="-100..100")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("erase", cmd_erase, "Eraser along a stroke or Magic Eraser by tolerance (rung 1)")
    p.add_argument("--stroke", help="'x,y x,y ...' eraser path")
    p.add_argument("--radius", type=float, default=8.0)
    p.add_argument("--hardness", type=float, default=0.8)
    p.add_argument("--strength", type=float, default=1.0, help="0..1 (eraser opacity)")
    p.add_argument("--magic", help="x,y: Magic Eraser seed")
    p.add_argument("--tolerance", type=float, default=32.0, help="0..255 max channel distance")
    p.add_argument("--all", action="store_true", help="not contiguous: every matching pixel")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("bucket", cmd_bucket, "Paint Bucket: flood fill by tolerance (rung 1)")
    p.add_argument("--at", required=True, help="x,y seed")
    p.add_argument("--color", required=True, help="#rrggbb[aa]")
    p.add_argument("--tolerance", type=float, default=32.0, help="0..255 max channel distance")
    p.add_argument("--all", action="store_true", help="not contiguous: every matching pixel")
    common(p)
    p = sub.add_parser("focusarea", help="Focus Area select: mask of the in-focus parts (rung 1)")
    p.add_argument("input")
    p.add_argument("-o", "--output", help="mask PNG (never overwritten)")
    p.add_argument("--radius", type=float, default=6.0, help="energy window sigma in px")
    p.add_argument("--threshold", type=float, help="energy threshold (default Otsu)")
    p.add_argument("--soft", type=float, default=0.0, help="soft edge width in log energy (0 = hard)")
    p.set_defaults(fn=cmd_focusarea)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "gradient, pattern, fill layers, layerstyle, blendif, replacecolor, focusarea, erase, bucket": (1, "own NumPy + Pillow"),
})
