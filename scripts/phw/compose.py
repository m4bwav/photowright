"""Blend modes, the layer model and the compositor (`layers`).

Blend modes follow W3C Compositing and Blending Level 1 (which follows the PDF / Adobe
definitions) for the 16 standard modes; the Photoshop-only modes use the community formulas
in references/rung1-own-code.md (unverified against Photoshop). Blending runs on straight
colour, then Porter-Duff source-over:
    Cs' = (1 - ab) Cs + ab B(Cb, Cs);  ao = as + ab (1 - as);  co = (as Cs' + ab Cb (1 - as)) / ao
Space: gamma-encoded values by default, as Photoshop (8/16-bit documents) and browsers do (R7);
a layer recipe may set "space": "linear" to blend linear light instead.

Layer order everywhere is bottom first (as PSD stores it). Groups default to pass-through.
Clipping uses the base layer's alpha times its mask (base opacity is not applied to the clip).
"""
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import core
from .core import Used, free_path, gaussian_blur, load, log_line, probe, save, to_enc, to_lin

__all__ = ["BLEND_MODES", "blend", "composite_over", "Layer", "Doc", "composite_doc", "doc_from_recipe",
           "flatten_layers"]


# ---------------------------------------------------------------- separable modes
def _dodge(cb, cs):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.minimum(1, cb / (1 - cs))
    return np.where(cb <= 0, 0, np.where(cs >= 1, 1, r))


def _burn(cb, cs):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 1 - np.minimum(1, (1 - cb) / cs)
    return np.where(cb >= 1, 1, np.where(cs <= 0, 0, r))


def _hard(cb, cs):
    return np.where(cs <= 0.5, cb * 2 * cs, cb + (2 * cs - 1) - cb * (2 * cs - 1))


def _soft(cb, cs):
    d = np.where(cb <= 0.25, ((16 * cb - 12) * cb + 4) * cb, np.sqrt(np.clip(cb, 0, None)))
    return np.where(cs <= 0.5, cb - (1 - 2 * cs) * cb * (1 - cb), cb + (2 * cs - 1) * (d - cb))


def _divide(cb, cs):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.minimum(1, cb / cs)
    return np.where(cs <= 0, np.where(cb <= 0, 0, 1), r)


SEPARABLE = {
    "normal": lambda cb, cs: cs,
    "multiply": lambda cb, cs: cb * cs,
    "screen": lambda cb, cs: cb + cs - cb * cs,
    "overlay": lambda cb, cs: _hard(cs, cb),
    "darken": np.minimum,
    "lighten": np.maximum,
    "color-dodge": _dodge,
    "color-burn": _burn,
    "hard-light": _hard,
    "soft-light": _soft,
    "difference": lambda cb, cs: np.abs(cb - cs),
    "exclusion": lambda cb, cs: cb + cs - 2 * cb * cs,
    # Photoshop-only (community formulas)
    "linear-burn": lambda cb, cs: np.maximum(0, cb + cs - 1),
    "linear-dodge": lambda cb, cs: np.minimum(1, cb + cs),
    "subtract": lambda cb, cs: np.maximum(0, cb - cs),
    "divide": _divide,
    "linear-light": lambda cb, cs: np.clip(cb + 2 * cs - 1, 0, 1),
    "vivid-light": lambda cb, cs: np.where(cs <= 0.5, _burn(cb, 2 * cs), _dodge(cb, 2 * (cs - 0.5))),
    "pin-light": lambda cb, cs: np.where(cs <= 0.5, np.minimum(cb, 2 * cs), np.maximum(cb, 2 * cs - 1)),
    "hard-mix": lambda cb, cs: (cb + cs >= 1).astype(np.float32),
}


# ---------------------------------------------------------------- non-separable modes (W3C)
def lum(c):
    return (0.3 * c[..., 0] + 0.59 * c[..., 1] + 0.11 * c[..., 2])[..., None]


def clip_color(c):
    lv = lum(c)
    n = c.min(-1, keepdims=True)
    x = c.max(-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(n < 0, lv + (c - lv) * lv / (lv - n), c)
        c = np.where(x > 1, lv + (c - lv) * (1 - lv) / (x - lv), c)
    return np.nan_to_num(c)


def set_lum(c, lv):
    return clip_color(c + (lv - lum(c)))


def sat(c):
    return c.max(-1, keepdims=True) - c.min(-1, keepdims=True)


def set_sat(c, s):
    mx = c.max(-1, keepdims=True)
    mn = c.min(-1, keepdims=True)
    rng = mx - mn
    with np.errstate(divide="ignore", invalid="ignore"):
        mid = np.where(rng > 0, (c - mn) * s / rng, 0)
    out = np.where(c == mx, s, np.where(c == mn, 0, mid))
    # ties: the W3C algorithm sets exactly one channel to max and one to min
    out = np.where(rng > 0, out, 0)
    return out


NONSEP = {
    "hue": lambda cb, cs: set_lum(set_sat(cs, sat(cb)), lum(cb)),
    "saturation": lambda cb, cs: set_lum(set_sat(cb, sat(cs)), lum(cb)),
    "color": lambda cb, cs: set_lum(cs, lum(cb)),
    "luminosity": lambda cb, cs: set_lum(cb, lum(cs)),
    "darker-color": lambda cb, cs: np.where(lum(cs) < lum(cb), cs, cb),
    "lighter-color": lambda cb, cs: np.where(lum(cs) > lum(cb), cs, cb),
}

BLEND_MODES = list(SEPARABLE) + list(NONSEP)
ALIASES = {"add": "linear-dodge", "plus": "linear-dodge", "colour": "color", "src-over": "normal",
           "colour-dodge": "color-dodge", "colour-burn": "color-burn"}


def norm_mode(m):
    m = str(m or "normal").lower().replace("_", "-").replace(" ", "-")
    m = ALIASES.get(m, m)
    if m != "pass" and m not in SEPARABLE and m not in NONSEP:
        raise ValueError(f"unknown blend mode {m!r} (dissolve is not supported); known: {', '.join(BLEND_MODES)}")
    return m


def blend(mode, cb, cs):
    """B(cb, cs) for straight colour arrays (..., 3)."""
    mode = norm_mode(mode)
    if mode in NONSEP:
        return NONSEP[mode](cb, cs)
    return SEPARABLE[mode](cb, cs)


def composite_over(cb, ab, cs, as_, mode="normal"):
    """Blend source (cs, as_) onto backdrop (cb, ab); colours straight HxWx3, alphas HxWx1."""
    b = np.clip(blend(mode, cb, cs), 0, 1)
    cs2 = (1 - ab) * cs + ab * b
    ao = as_ + ab * (1 - as_)
    with np.errstate(divide="ignore", invalid="ignore"):
        co = np.where(ao > 0, (as_ * cs2 + ab * cb * (1 - as_)) / np.where(ao > 0, ao, 1), 0)
    keep = as_ <= 0  # nothing outside the source's coverage changes, bit for bit
    return np.where(keep, cb, co).astype(np.float32), np.where(keep, ab, ao).astype(np.float32)


# ---------------------------------------------------------------- layer model
class Layer:
    """A pixel layer or a group. px: float32 h x w x 4 straight RGBA at (x, y) on the canvas.
    mask: float32 h x w at (mask_x, mask_y); mask_default is its value outside that rectangle."""

    def __init__(self, name="Layer", px=None, x=0, y=0, opacity=1.0, blend="normal", visible=True,
                 mask=None, mask_x=0, mask_y=0, mask_default=0.0, clip=False, children=None, group=False):
        self.name, self.px, self.x, self.y = name, px, int(x), int(y)
        self.opacity, self.blend, self.visible = float(opacity), blend, bool(visible)
        self.mask, self.mask_x, self.mask_y, self.mask_default = mask, int(mask_x), int(mask_y), float(mask_default)
        self.clip, self.group = bool(clip), bool(group)
        self.children = children if children is not None else []

    def info(self):
        d = {"name": self.name, "kind": "group" if self.group else "pixel", "blend": self.blend,
             "opacity": round(self.opacity, 4), "visible": self.visible, "clip": self.clip,
             "mask": None if self.mask is None else {"rect": [self.mask_x, self.mask_y, int(self.mask.shape[1]),
                                                              int(self.mask.shape[0])],
                                                     "default": self.mask_default}}
        if self.group:
            d["children"] = [c.info() for c in self.children]
        elif self.px is not None:
            d["rect"] = [self.x, self.y, int(self.px.shape[1]), int(self.px.shape[0])]
        return d


class Doc:
    def __init__(self, width, height, layers=None, notes=None, icc=None):
        self.width, self.height = int(width), int(height)
        self.layers = layers if layers is not None else []
        self.notes = notes if notes is not None else []
        self.icc = icc

    def walk(self):
        def rec(ls, depth):
            for lay in ls:
                yield lay, depth
                if lay.group:
                    yield from rec(lay.children, depth + 1)
        yield from rec(self.layers, 0)

    def info(self):
        return {"size": [self.width, self.height], "layers": [l.info() for l in self.layers],
                "count": sum(1 for _ in self.walk())}


def place(arr, x, y, w, h, fill=0.0):
    """Put arr (ah x aw [x c]) at (x, y) on a w x h canvas filled with `fill`."""
    shape = (h, w) + arr.shape[2:]
    out = np.full(shape, fill, np.float32)
    ah, aw = arr.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + aw), min(h, y + ah)
    if x1 > x0 and y1 > y0:
        out[y0:y1, x0:x1] = arr[y0 - y:y1 - y, x0 - x:x1 - x]
    return out


def mask_canvas(lay, w, h):
    if lay.mask is None:
        return None
    return place(lay.mask, lay.mask_x, lay.mask_y, w, h, lay.mask_default)


def layer_canvas(lay, w, h, space):
    px = place(lay.px, lay.x, lay.y, w, h)
    c, a = px[..., :3], px[..., 3:4]
    if space == "linear":
        c = to_lin(c)
    m = mask_canvas(lay, w, h)
    if m is not None:
        a = a * m[..., None]
    return c, a


def composite_stack(layers, cb, ab, w, h, space):
    base_a = None
    for lay in layers:
        if not lay.visible:
            if not lay.clip:
                base_a = np.zeros((h, w, 1), np.float32)
            continue
        if lay.group:
            m = mask_canvas(lay, w, h)
            f = lay.opacity * (m[..., None] if m is not None else 1.0)
            if lay.blend == "pass":
                cb2, ab2 = composite_stack(lay.children, cb.copy(), ab.copy(), w, h, space)
                if m is None and lay.opacity >= 1:
                    cb, ab = cb2, ab2
                else:
                    f = np.zeros_like(ab) + f
                    p, p2 = cb * ab, cb2 * ab2
                    pr, ar = p + f * (p2 - p), ab + f * (ab2 - ab)
                    with np.errstate(divide="ignore", invalid="ignore"):
                        nc = np.where(ar > 0, pr / np.where(ar > 0, ar, 1), 0)
                    cb = np.where(f <= 0, cb, nc).astype(np.float32)
                    ab = np.where(f <= 0, ab, ar).astype(np.float32)
                base_a = ab2 if m is None else ab2 * m[..., None]
            else:
                z = np.zeros((h, w, 3), np.float32)
                gc, ga = composite_stack(lay.children, z, np.zeros((h, w, 1), np.float32), w, h, space)
                if m is not None:
                    ga = ga * m[..., None]
                base_a = ga
                cb, ab = composite_over(cb, ab, gc, ga * lay.opacity, lay.blend)
            continue
        c, a = layer_canvas(lay, w, h, space)
        if lay.clip and base_a is not None:
            a = a * base_a
        elif not lay.clip:
            base_a = a
        cb, ab = composite_over(cb, ab, c, a * lay.opacity, lay.blend)
    return cb, ab


def composite_doc(doc, space="gamma", background=None):
    """Return the flattened straight RGBA float32 h x w x 4 (encoded values)."""
    w, h = doc.width, doc.height
    cb = np.zeros((h, w, 3), np.float32)
    ab = np.zeros((h, w, 1), np.float32)
    if background is not None:
        bg = np.asarray(background, np.float32)
        cb[:] = bg[:3]
        ab[:] = bg[3] if len(bg) > 3 else 1.0
    if space == "linear":
        cb = to_lin(cb)
    cb, ab = composite_stack(doc.layers, cb, ab, w, h, space)
    if space == "linear":
        cb = to_enc(cb)
    return np.concatenate([np.clip(cb, 0, 1), np.clip(ab, 0, 1)], axis=2)


# ---------------------------------------------------------------- recipe -> doc
def rgba(img):
    c = img.color()
    if c.shape[2] == 1:
        c = np.repeat(c, 3, axis=2)
    a = img.px[..., -1:] if img.alpha else np.ones(c.shape[:2] + (1,), np.float32)
    return np.concatenate([c[..., :3], a], axis=2).astype(np.float32)


def colour4(v, default=(0, 0, 0, 1)):
    v = list(v) if v is not None else list(default)
    if any(x > 1 for x in v):
        v = [x / 255.0 for x in v]
    return np.asarray(v + [1.0] * (4 - len(v)), np.float32)


def paint(alpha, col):
    col = colour4(col)
    px = np.empty(alpha.shape + (4,), np.float32)
    px[..., :3] = col[:3]
    px[..., 3] = alpha * col[3]
    return px


def draw_alpha(w, h, fn, ss):
    im = Image.new("L", (w * ss, h * ss), 0)
    fn(ImageDraw.Draw(im), ss)
    if ss > 1:
        im = im.resize((w, h), Image.BOX)
    return np.asarray(im, np.float32) / 255.0


def font_for(spec, size):
    if spec:
        return ImageFont.truetype(spec, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def raster_text(L, w, h):
    font = font_for(L.get("font"), int(L.get("size", 32)))
    xy = (float(L.get("x", 0)), float(L.get("y", 0)))
    kw = {k: L[k] for k in ("anchor", "align", "spacing") if k in L}

    def fn(d, ss):
        d.text(xy, str(L["text"]), fill=255, font=font, **kw)
    return paint(draw_alpha(w, h, fn, 1), L.get("color", [0, 0, 0]))


def raster_shape(L, w, h):
    ss = int(L.get("antialias", 4))
    kind = L.get("shape", "rect")
    sw = float((L.get("stroke") or {}).get("width", 0))

    def geom(d, s, fill, width):
        if kind in ("rect", "ellipse", "rounded-rect"):
            x, y, bw, bh = (float(v) * s for v in L["box"])
            box = [x, y, x + bw, y + bh] if s > 1 else [x, y, x + bw - 1, y + bh - 1]
            if kind == "rect":
                d.rectangle(box, fill=fill, outline=255 if width else None, width=int(width * s))
            elif kind == "ellipse":
                d.ellipse(box, fill=fill, outline=255 if width else None, width=int(width * s))
            else:
                d.rounded_rectangle(box, radius=float(L.get("radius", 8)) * s, fill=fill,
                                    outline=255 if width else None, width=int(width * s))
        elif kind == "polygon":
            pts = [(float(a) * s, float(b) * s) for a, b in L["points"]]
            d.polygon(pts, fill=fill, outline=255 if width else None, width=int(width * s) if width else 1)
        else:
            raise ValueError(f"unknown shape {kind}")
    out = np.zeros((h, w, 4), np.float32)
    c, a = out[..., :3], out[..., 3:]
    if L.get("fill") is not None:
        fa = draw_alpha(w, h, lambda d, s: geom(d, s, 255, 0), ss)
        c, a = composite_over(c, a, np.broadcast_to(colour4(L["fill"])[:3], c.shape), (fa * colour4(L["fill"])[3])[..., None])
    if sw > 0:
        sa = draw_alpha(w, h, lambda d, s: geom(d, s, None, sw), ss)
        sc = colour4(L["stroke"].get("color", [0, 0, 0]))
        c, a = composite_over(c, a, np.broadcast_to(sc[:3], c.shape), (sa * sc[3])[..., None])
    return np.concatenate([c, a], axis=2)


def resolve(base, f):
    f = Path(f)
    return f if f.is_absolute() or base is None else Path(base) / f


def mask_from_spec(spec, base, w, h):
    from .masks import read_mask
    if isinstance(spec, str):
        spec = {"file": spec}
    m = read_mask(resolve(base, spec["file"]))
    if spec.get("invert"):
        m = 1 - m
    return m, int(spec.get("x", 0)), int(spec.get("y", 0)), float(spec.get("default", 0.0))


def effects_layers(lay, eff, w, h, used):
    """Drop shadow and outside stroke, rasterised as layers to go below `lay` (Photoshop order)."""
    from .masks import morph
    a = place(lay.px[..., 3], lay.x, lay.y, w, h)
    m = mask_canvas(lay, w, h)
    if m is not None:
        a = a * m
    out = []
    if eff.get("drop_shadow"):
        s = eff["drop_shadow"]
        if s is True:
            s = {}
        sa = place(a, int(s.get("dx", 4)), int(s.get("dy", 4)), w, h)
        if s.get("blur", 4):
            sa = np.clip(gaussian_blur(sa, float(s.get("blur", 4)), used), 0, 1)
        if s.get("spread"):
            sa = morph(sa, s["spread"], True, used)
        out.append(Layer(f"{lay.name} (drop shadow)", paint(sa, s.get("color", [0, 0, 0])),
                         opacity=float(s.get("opacity", 0.6)), blend=norm_mode(s.get("blend", "multiply"))))
    if eff.get("stroke"):
        s = eff["stroke"]
        if s.get("position", "outside") != "outside":
            raise ValueError("stroke: only position 'outside' is built")
        sa = np.clip(morph(a, float(s.get("size", 3)), True, used), 0, 1)
        out.append(Layer(f"{lay.name} (stroke)", paint(sa, s.get("color", [0, 0, 0])),
                         opacity=float(s.get("opacity", 1.0)), blend=norm_mode(s.get("blend", "normal"))))
    return out


def layers_from_specs(specs, base, w, h, used, notes):
    out = []
    for i, L in enumerate(specs):
        t = L.get("type", "image")
        name = L.get("name") or f"{t} {i + 1}"
        common = dict(opacity=float(L.get("opacity", 1.0)), visible=L.get("visible", True), clip=L.get("clip", False))
        if t == "group":
            lay = Layer(name, group=True, blend=norm_mode(L.get("blend", "pass")),
                        children=layers_from_specs(L.get("layers", []), base, w, h, used, notes), **common)
        else:
            if t == "image":
                img = load(resolve(base, L["file"]), used)
                notes += [n for n in img.notes if n not in notes]
                px, x, y = rgba(img), int(L.get("x", 0)), int(L.get("y", 0))
            elif t == "fill":
                px, x, y = paint(np.ones((h, w), np.float32), L.get("color", [1, 1, 1])), 0, 0
            elif t == "text":
                px, x, y = raster_text(L, w, h), 0, 0
                used.add("text", 1, "Pillow ImageFont")
                notes.append(f"text layer {name!r} rasterised (PSD/ORA get pixels, not editable text)")
            elif t == "shape":
                px, x, y = raster_shape(L, w, h), 0, 0
                used.add("shape", 1, "Pillow ImageDraw (supersampled)")
            else:
                raise ValueError(f"unknown layer type {t}")
            lay = Layer(name, px, x, y, blend=norm_mode(L.get("blend", "normal")), **common)
        if L.get("mask"):
            lay.mask, lay.mask_x, lay.mask_y, lay.mask_default = mask_from_spec(L["mask"], base, w, h)
        if L.get("effects") and not lay.group:
            fx = effects_layers(lay, L["effects"], w, h, used)
            notes.append(f"effects of {name!r} rasterised as {len(fx)} layer(s) below it")
            out += fx
        out.append(lay)
    return out


def doc_from_recipe(r, base, used):
    c = r.get("canvas", {})
    w, h = int(c["width"]), int(c["height"])
    notes = []
    doc = Doc(w, h, notes=notes)
    if c.get("background") is not None:
        doc.layers.append(Layer("Background", paint(np.ones((h, w), np.float32), c["background"])))
    doc.layers += layers_from_specs(r.get("layers", []), base, w, h, used, notes)
    used.add("composite", 1, "own compositor (W3C formulas)")
    return doc


def flatten_layers(doc, space="gamma"):
    return composite_doc(doc, space)


# ---------------------------------------------------------------- command
def write_doc(doc, out, used, space="gamma", bits=8):
    """Write a composite (png, jpg, webp, tif ...) or a layered file (.psd, .ora)."""
    from . import layered
    ext = Path(out).suffix.lower()
    if ext in layered.WRITERS:
        layered.WRITERS[ext](doc, out, used, space)
        return out
    flat = composite_doc(doc, space)
    img = core.Img(flat, True, doc.icc, bits=bits)
    if (flat[..., 3] >= 1).all():
        img = core.Img(flat[..., :3], False, doc.icc, bits=bits)
    save(img, out, bits, used)
    return out


def cmd_layers(a):
    t0 = time.time()
    used = Used()
    recipe = Path(a.recipe_file)
    r = json.loads(recipe.read_text(encoding="utf-8"))
    return run_layers(a, recipe, r, used, t0)


def run_layers(a, recipe, r, used=None, t0=None):
    t0 = t0 or time.time()
    used = used or Used()
    doc = doc_from_recipe(r, recipe.parent, used)
    space = r.get("space", "gamma")
    out = Path(a.output) if getattr(a, "output", None) else recipe.parent / "out" / f"{recipe.stem}{getattr(a, 'ext', None) or '.png'}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out = free_path(out)
    write_doc(doc, out, used, space, getattr(a, "bits", None) or 8)
    log_line(recipe.parent / "log.jsonl", ["layers"], out, used, time.time() - t0, {"run": True, "kind": "layers"})
    return {"command": "layers", "recipe": str(recipe), "output": str(out), "space": space,
            "layers": doc.info()["count"], "rung": used.rung(), "tool": used.tool(), "used": used.items,
            "notes": doc.notes}


core.RUN_KINDS["layers"] = run_layers


def add_commands(sub, edit):
    p = sub.add_parser("layers", help="composite a layer recipe (blend modes, masks, clipping, groups, text, "
                                      "shapes, drop shadow, stroke) to an image, .psd or .ora")
    p.add_argument("recipe_file")
    p.add_argument("-o", "--output", help="output .png/.jpg/.tif/.psd/.ora (never overwritten)")
    p.add_argument("--ext", help="output extension when -o is not given (default .png)")
    p.add_argument("--bits", type=int, choices=(8, 16))
    p.set_defaults(fn=cmd_layers)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {"layers (blend modes, masks, groups, text, shapes, effects)":
                                   (1, "own compositor, Pillow ImageFont/ImageDraw")})
core.BLEND.update({
    "linear-burn": "B = max(0, cb + cs - 1) (Photoshop; community formula)",
    "linear-dodge": "B = min(1, cb + cs) (Photoshop 'Add')",
    "subtract": "B = max(0, cb - cs)",
    "divide": "B = min(1, cb / cs); 1 when cs = 0 and cb > 0",
    "linear-light": "B = clip(cb + 2 cs - 1)",
    "vivid-light": "cs <= 0.5: color-burn(cb, 2cs); else color-dodge(cb, 2(cs - 0.5))",
    "pin-light": "cs <= 0.5: min(cb, 2cs); else max(cb, 2cs - 1)",
    "hard-mix": "B = 1 if cb + cs >= 1 else 0",
    "darker-color": "whole pixel with the lower Lum",
    "lighter-color": "whole pixel with the higher Lum",
    "pass": "group mode: children blend straight onto what is below (no isolation)",
})
