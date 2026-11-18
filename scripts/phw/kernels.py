"""Batch 12 (0.13.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

filter --kernel:  Custom (odd square kernel, correlation, scale and offset as in Photoshop's Custom).
canvas --reveal-all: grow a layered doc's canvas to every layer's bounds (Reveal All).
apply-image:      Apply Image / Calculations: one channel (or RGB) of a source image blended onto the input.
fx:               Texture (fine-scale clarity), Pointillize, Extrude (blocks), Tiles, Lens Flare,
                  Lighting Effects (point or spot light, optional luma bump).
lensblur:         Lens Blur (disc or hexagon bokeh, highlight boost in linear light) and Shape Blur.
liquify:          forward-warp push along a stroke (backward-mapped through transform.remap).
Own NumPy only; ops keep alpha, take --mask and --recipe and replay through `phw run`.
"""
import math
from pathlib import Path

import numpy as np

from . import core, transform
from .core import OPS, floats
from .filters import convolve
from .grading import grid, luma, with_mask


def per_ch(c, fn):
    return np.stack([fn(c[..., i]) for i in range(c.shape[2])], axis=2)


def hexcol(s):
    h = s.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


# ---------------------------------------------------------------- custom kernel
def op_kernel(img, p, used):
    """Correlate each colour channel with an odd square kernel, divide by scale, add offset/255
    (Photoshop Custom). Scale defaults to the kernel sum, or 1 when the sum is 0."""
    k = np.asarray(p["kernel"], np.float64)
    n = int(round(math.sqrt(k.size)))
    if n * n != k.size or n % 2 == 0:
        raise ValueError("kernel: give an odd square count of numbers (9, 25, 49 ...)")
    k = k.reshape(n, n)
    scale = float(p.get("scale") or (k.sum() if abs(k.sum()) > 1e-12 else 1.0))
    off = float(p.get("offset", 0)) / 255.0
    kk = (k / scale).astype(np.float32)
    out = per_ch(img.color().astype(np.float32), lambda ch: convolve(ch, kk)) + off
    used.add("filter.kernel", 1, "NumPy custom kernel")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- reveal all
def reveal_all(doc):
    """Grow the canvas to the union of the canvas and every pixel layer's and mask's rectangle; shift
    every layer so nothing moves relative to the others. Returns (dx, dy) applied."""
    x0, y0, x1, y1 = 0, 0, doc.width, doc.height
    for lay, _ in doc.walk():
        if lay.group or lay.px is None:
            continue
        x0, y0 = min(x0, lay.x), min(y0, lay.y)
        x1, y1 = max(x1, lay.x + lay.px.shape[1]), max(y1, lay.y + lay.px.shape[0])
    dx, dy = -x0, -y0
    for lay, _ in doc.walk():
        lay.x += dx
        lay.y += dy
        lay.mask_x += dx
        lay.mask_y += dy
    doc.width, doc.height = x1 - x0, y1 - y0
    return dx, dy


def cmd_reveal_all(a):
    from . import compose, layered
    used = core.Used()
    doc = layered.read_layered(a.input, used)
    before = [doc.width, doc.height]
    dx, dy = reveal_all(doc)
    used.add("canvas.reveal_all", 1, "own layer bounds")
    out = core.free_path(Path(a.output)) if a.output else core.out_for(a.input, None, "canvas",
                                                                        Path(a.input).suffix if Path(a.input).suffix.lower() in layered.WRITERS else ".png")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    compose.write_doc(doc, out, used)
    return {"command": "canvas", "input": str(a.input), "output": str(out), "before": before,
            "after": [doc.width, doc.height], "shift": [dx, dy], "rung": used.rung(), "tool": used.tool(),
            "used": used.items, "notes": doc.notes}


# ---------------------------------------------------------------- apply image / calculations
def channel_of(c, ch):
    if ch == "rgb":
        return c
    if ch == "luma":
        g = luma(c)
    else:
        g = c[..., "rgb".index(ch)]
    return np.repeat(g[..., None], 3, axis=2)


def op_apply_image(img, p, used):
    """result = base (1 - opacity) + blend(mode, base, source channel) * opacity, where the source channel
    is RGB or one of r, g, b, luma replicated to grey (optionally inverted). calc=True (Calculations)
    reduces the base to the same channel first, so the result is grey."""
    from .compose import blend
    src = core.load(p["source"])
    c = img.color()[..., :3]
    if src.px.shape[:2] != c.shape[:2]:
        raise ValueError("apply-image: the source must be the same size as the input")
    s = src.color()[..., :3] if src.nc >= 3 else np.repeat(src.color()[..., :1], 3, axis=2)
    cs = channel_of(s, p.get("channel", "rgb"))
    if p.get("invert"):
        cs = 1 - cs
    cb = channel_of(c, p.get("base_channel", "luma")) if p.get("calc") else c
    op = float(p.get("opacity", 1.0))
    out = cb * (1 - op) + np.clip(blend(p.get("blend", "normal"), cb, cs), 0, 1) * op
    used.add("applyimage", 1, "NumPy blend of a source channel")
    if img.nc > 3:
        out = np.concatenate([out, img.color()[..., 3:]], axis=2)
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- fx
def op_texture(img, p, used):
    """Fine-scale clarity: c + amount (c - gauss(c, radius)); amount -1 gives the blur, + adds fine detail.
    A flat area has no detail, so it stays put."""
    a, r = float(p["amount"]), float(p.get("radius", 1.5))
    c = img.color()
    low = per_ch(c, lambda ch: core.gaussian_blur(ch, r))
    used.add("fx.texture", 1, "NumPy fine-scale band")
    return img.with_color(np.clip(c + a * (c - low), 0, 1).astype(np.float32))


def bg_fill(p, nc):
    bg = list(p.get("bg", [1, 1, 1]))
    return np.asarray((bg + [1.0] * nc)[:nc] if nc != 1 else [sum(bg) / 3], np.float32)


def jitter_seeds(h, w, cell, seed):
    rng = np.random.default_rng(int(seed))
    gy, gx = np.mgrid[0:h:cell, 0:w:cell]
    return (gy + rng.uniform(0, cell, gy.shape)).ravel(), (gx + rng.uniform(0, cell, gx.shape)).ravel()


def op_pointillize(img, p, used):
    """Seeded jittered-grid dots of radius cell * 0.6 on a background colour, each the mean of the source
    under it; later dots cover earlier ones."""
    cell = int(p["cell"])
    c = img.color()
    h, w = c.shape[:2]
    out = np.empty_like(c)
    out[:] = bg_fill(p, c.shape[2])
    r = max(1.0, cell * 0.6)
    ri = int(math.ceil(r))
    sy, sx = jitter_seeds(h, w, cell, p.get("seed", 0))
    for y, x in zip(sy, sx):
        ya, yb, xa, xb = max(0, int(y) - ri), min(h, int(y) + ri + 1), max(0, int(x) - ri), min(w, int(x) + ri + 1)
        Y, X = np.mgrid[ya:yb, xa:xb]
        m = (Y - y) ** 2 + (X - x) ** 2 <= r * r
        if m.any():
            out[ya:yb, xa:xb][m] = c[ya:yb, xa:xb][m].mean(0)
    used.add("fx.pointillize", 1, "NumPy seeded dots")
    return img.with_color(out.astype(np.float32))


def op_extrude(img, p, used):
    """Blocks: size x size tiles with their mean colour, each raised by a seeded depth up to `depth`
    (0..1): the face grows by (1 + depth) about the image centre and the sides between base and face
    are drawn at 60% brightness; blocks are painted lowest first."""
    s, depth = int(p["size"]), float(p.get("depth", 0.3))
    c = img.color()
    h, w = c.shape[:2]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    rng = np.random.default_rng(int(p.get("seed", 0)))
    blocks = []
    for y in range(0, h, s):
        for x in range(0, w, s):
            blocks.append((rng.uniform(0, depth), y, x, c[y:y + s, x:x + s].reshape(-1, c.shape[2]).mean(0)))
    out = np.empty_like(c)
    for d, y, x, col in blocks:          # base layer: every block flat at depth 0
        out[y:y + s, x:x + s] = col
    for d, y, x, col in sorted(blocks, key=lambda b: b[0]):
        if d <= 0:
            continue
        bh, bw = min(s, h - y), min(s, w - x)
        steps = max(2, int(math.ceil(d * max(h, w) / 2)))
        for i in range(steps + 1):
            f = 1 + d * i / steps
            ya = int(round(cy + (y - cy) * f))
            xa = int(round(cx + (x - cx) * f))
            hh, ww = max(1, int(round(bh * f))), max(1, int(round(bw * f)))
            y0, y1, x0, x1 = max(0, ya), min(h, ya + hh), max(0, xa), min(w, xa + ww)
            if y1 > y0 and x1 > x0:
                out[y0:y1, x0:x1] = col if i == steps else col * 0.6
    used.add("fx.extrude", 1, "NumPy seeded blocks")
    return img.with_color(out.astype(np.float32))


def op_tiles(img, p, used):
    """Split into n tiles across (square tiles), shift each by a seeded offset up to `offset` (0..1 of the
    tile size) and fill the gaps with the background colour. Tiles are pure translated copies."""
    n, off = int(p["n"]), float(p.get("offset", 0.1))
    c = img.color()
    h, w = c.shape[:2]
    t = max(1, int(math.ceil(w / n)))
    out = np.empty_like(c)
    out[:] = bg_fill(p, c.shape[2])
    rng = np.random.default_rng(int(p.get("seed", 0)))
    m = int(round(off * t))
    for y in range(0, h, t):
        for x in range(0, w, t):
            dy, dx = (rng.integers(-m, m + 1, 2) if m > 0 else (0, 0))
            tile = c[y:y + t, x:x + t]
            ya, xa = y + int(dy), x + int(dx)
            y0, x0 = max(0, ya), max(0, xa)
            y1, x1 = min(h, ya + tile.shape[0]), min(w, xa + tile.shape[1])
            if y1 > y0 and x1 > x0:
                out[y0:y1, x0:x1] = tile[y0 - ya:y1 - ya, x0 - xa:x1 - xa]
    used.add("fx.tiles", 1, "NumPy seeded tiles")
    return img.with_color(out.astype(np.float32))


def op_flare(img, p, used):
    """Lens flare added in linear light: a warm core glow at (x, y), a halo ring and three ghosts on the
    line from (x, y) through the centre. Only adds light; brightness 0 is the identity."""
    b = float(p.get("brightness", 1.0))
    if b <= 0:
        used.add("fx.flare", 1, "identity (brightness 0)")
        return img.copy()
    h, w, X, Y, cx, cy = grid(img)
    fx, fy = float(p["x"]), float(p["y"])
    D = math.hypot(w, h)
    d = np.hypot(X - fx, Y - fy)
    glow = np.exp(-(d / (0.06 * D)) ** 2) + 0.25 * np.exp(-d / (0.15 * D))
    halo = 0.15 * np.exp(-((d - 0.18 * D) / (0.012 * D)) ** 2)
    add = np.stack([glow * 1.0 + halo * 0.6, glow * 0.85 + halo * 0.8, glow * 0.6 + halo * 1.0], 2)
    for t, rad, col in ((-0.4, 0.03, (0.3, 0.5, 0.4)), (-0.75, 0.05, (0.4, 0.3, 0.5)), (-1.1, 0.02, (0.5, 0.4, 0.2))):
        gx, gy = cx + (fx - cx) * t, cy + (fy - cy) * t
        g = np.exp(-(np.hypot(X - gx, Y - gy) / (rad * D)) ** 4) * 0.3
        add += np.stack([g * k for k in col], 2)
    c = img.color()
    lin = core.to_lin(c[..., :3]) + (b * add).astype(np.float32)
    out = np.maximum(core.to_enc(np.clip(lin, 0, 1)), c[..., :3])
    if c.shape[2] > 3:
        out = np.concatenate([out, c[..., 3:]], axis=2)
    used.add("fx.flare", 1, "NumPy additive flare in linear light")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_light(img, p, used):
    """Lighting Effects: colour x (ambient + intensity max(0, N.L) cone), light at (x, y, z) px.
    N comes from the luma bump channel times `bump` (0 = flat); a spot light keeps only the cone
    of half-angle `cone` degrees around the ray to (tx, ty) on the image plane."""
    h, w, X, Y, cx, cy = grid(img)
    lx, ly, lz = float(p["x"]), float(p["y"]), float(p.get("z", max(h, w) / 2))
    amb, inten = float(p.get("ambient", 0.2)), float(p.get("intensity", 1.0))
    c = img.color()
    bump = float(p.get("bump", 0))
    if bump:
        B = luma(c[..., :3]).astype(np.float64) * bump
        gy, gx = np.gradient(B)
        N = np.stack([-gx, -gy, np.ones_like(B)], 2)
    else:
        N = np.zeros((h, w, 3))
        N[..., 2] = 1
    N /= np.linalg.norm(N, axis=2, keepdims=True)
    L = np.stack([lx - X, ly - Y, np.full_like(X, lz)], 2)
    L /= np.linalg.norm(L, axis=2, keepdims=True)
    diff = np.clip((N * L).sum(2), 0, None) * inten
    if p.get("kind", "point") == "spot":
        sd = np.array([float(p.get("tx", cx)) - lx, float(p.get("ty", cy)) - ly, -lz])
        sd /= np.linalg.norm(sd)
        cosang = (-L * sd).sum(2)
        diff = np.where(cosang >= math.cos(math.radians(float(p.get("cone", 30)))), diff, 0.0)
    f = (amb + diff)[..., None]
    out = c[..., :3] * f
    if c.shape[2] > 3:
        out = np.concatenate([out, c[..., 3:]], axis=2)
    used.add("fx.light", 1, f"NumPy {p.get('kind', 'point')} light")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- lens blur / shape blur
def shape_kernel(shape, r):
    """Binary kernel of radius r: disc, hexagon (flat top), square, ring or star (5 points)."""
    n = int(math.ceil(r))
    Y, X = np.mgrid[-n:n + 1, -n:n + 1].astype(np.float64)
    if shape == "disc":
        k = X * X + Y * Y <= r * r + 1e-9
    elif shape == "hexagon":
        ax, ay = np.abs(X), np.abs(Y)
        k = (ay <= r * math.sqrt(3) / 2) & (math.sqrt(3) * ax + ay <= math.sqrt(3) * r)
    elif shape == "square":
        k = (np.abs(X) <= r) & (np.abs(Y) <= r)
    elif shape == "ring":
        d = np.hypot(X, Y)
        k = (d <= r) & (d >= r * 0.6)
    elif shape == "star":
        a = np.arctan2(Y, X)
        rad = r * (0.45 + 0.55 * np.abs(np.cos(2.5 * a)))
        k = np.hypot(X, Y) <= rad
    else:
        raise ValueError(f"unknown shape {shape!r}")
    return k.astype(np.float64)


def op_lens_blur(img, p, used):
    """Bokeh: boost highlights in linear light (values above `threshold` are multiplied by 1 + boost
    on a smooth ramp), average over the shape kernel, then undo the boost curve on the mean where
    it is invertible (it is monotonic)."""
    r, shape = float(p["radius"]), p.get("shape", "disc")
    boost, thr = float(p.get("boost", 0)), float(p.get("threshold", 0.8))
    k = shape_kernel(shape, r)
    k = (k / k.sum()).astype(np.float32)
    c = img.color()
    lin = core.to_lin(c[..., :3])
    ramp = np.clip((lin - thr) / max(1e-6, 1 - thr), 0, 1)
    hot = lin * (1 + boost * ramp)
    out = core.to_enc(np.clip(per_ch(hot, lambda ch: convolve(ch, k)), 0, 1))
    if c.shape[2] > 3:
        out = np.concatenate([out, per_ch(c[..., 3:], lambda ch: convolve(ch, k))], axis=2)
    used.add("lensblur.lens", 1, f"NumPy {shape} bokeh in linear light")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_shape_blur(img, p, used):
    """Mean over a shaped kernel in encoded values (Photoshop Shape Blur)."""
    k = shape_kernel(p.get("shape", "star"), float(p["radius"]))
    k = (k / k.sum()).astype(np.float32)
    used.add("lensblur.shape", 1, "NumPy shape kernel")
    return img.with_color(np.clip(per_ch(img.color(), lambda ch: convolve(ch, k)), 0, 1).astype(np.float32))


# ---------------------------------------------------------------- liquify
def op_liquify(img, p, used):
    """Forward-warp push: walk the stroke in steps of radius/4; each step moves the content under a
    Gaussian brush (sigma radius/2, cut at radius) by strength x the step vector. The accumulated
    field D is applied backward through transform.remap: the output at q shows the source at q - D(q)."""
    pts = np.asarray(p["stroke"], np.float64).reshape(-1, 2)
    r, s = float(p["radius"]), float(p.get("strength", 0.5))
    h, w = img.px.shape[:2]
    if s == 0 or len(pts) < 2:
        used.add("liquify", 1, "identity (no push)")
        return img.copy()
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
    DX, DY = np.zeros((h, w)), np.zeros((h, w))
    for a, b in zip(pts[:-1], pts[1:]):
        L = float(np.hypot(*(b - a)))
        n = max(1, int(math.ceil(L / (r / 4))))
        for i in range(n):
            q0 = a + (b - a) * i / n
            q1 = a + (b - a) * (i + 1) / n
            vx, vy = q1 - q0
            d2 = (X - q0[0]) ** 2 + (Y - q0[1]) ** 2
            wgt = np.where(d2 < r * r, np.exp(-d2 / (2 * (r / 2) ** 2)), 0.0) * s
            DX += wgt * vx
            DY += wgt * vy
    used.add("liquify", 1, "own push field + transform.remap")
    return transform.remap(img, np.clip(X - DX, 0, w - 1).astype(np.float32),
                           np.clip(Y - DY, 0, h - 1).astype(np.float32), used, "liquify")


OPS.update({"filter.kernel": op_kernel, "applyimage": op_apply_image, "fx.texture": op_texture,
            "fx.pointillize": op_pointillize, "fx.extrude": op_extrude, "fx.tiles": op_tiles,
            "fx.flare": op_flare, "fx.light": op_light, "lensblur.lens": op_lens_blur,
            "lensblur.shape": op_shape_blur, "liquify": op_liquify})


# ---------------------------------------------------------------- commands
def cmd_apply_image(a):
    p = {"source": str(Path(a.source).resolve()), "channel": a.channel, "blend": a.blend, "opacity": a.opacity,
         "invert": a.invert, "calc": a.calc, "base_channel": a.base_channel}
    return core.edit_command(a, "apply-image", with_mask(a, [{"op": "applyimage", "params": p}]))


def cmd_fx(a):
    steps = []
    if a.texture is not None:
        steps.append({"op": "fx.texture", "params": {"amount": a.texture, "radius": a.texture_radius}})
    if a.pointillize:
        steps.append({"op": "fx.pointillize", "params": {"cell": a.pointillize, "seed": a.seed, "bg": hexcol(a.bg)}})
    if a.extrude:
        s, d = floats(a.extrude, 2)
        steps.append({"op": "fx.extrude", "params": {"size": int(s), "depth": d, "seed": a.seed}})
    if a.tiles:
        steps.append({"op": "fx.tiles", "params": {"n": a.tiles, "offset": a.tile_offset, "seed": a.seed,
                                                   "bg": hexcol(a.bg)}})
    if a.flare:
        x, y = floats(a.flare, 2)
        steps.append({"op": "fx.flare", "params": {"x": x, "y": y, "brightness": a.brightness}})
    if a.light:
        v = floats(a.light, (2, 3))
        prm = {"x": v[0], "y": v[1], "kind": a.light_kind, "ambient": a.ambient, "intensity": a.intensity,
               "bump": a.bump, "cone": a.cone}
        if len(v) == 3:
            prm["z"] = v[2]
        if a.target:
            prm["tx"], prm["ty"] = floats(a.target, 2)
        steps.append({"op": "fx.light", "params": prm})
    if not steps:
        raise SystemExit("fx: give --texture, --pointillize, --extrude, --tiles, --flare or --light")
    return core.edit_command(a, "fx", with_mask(a, steps))


def cmd_lensblur(a):
    steps = []
    if a.lens:
        steps.append({"op": "lensblur.lens", "params": {"radius": a.lens, "shape": a.iris, "boost": a.boost,
                                                        "threshold": a.threshold}})
    if a.shape_blur:
        steps.append({"op": "lensblur.shape", "params": {"radius": a.shape_blur, "shape": a.shape}})
    if not steps:
        raise SystemExit("lensblur: give --lens or --shape-blur")
    return core.edit_command(a, "lensblur", with_mask(a, steps))


def cmd_liquify(a):
    pts = [floats(t, 2) for t in a.stroke.replace(";", " ").split()]
    if a.mode != "push":
        st = {"op": "liquify.brush", "params": {"points": pts, "radius": a.radius, "strength": a.strength,
                                                 "mode": a.mode}}
        return core.edit_command(a, "liquify", with_mask(a, [st]))
    p = {"stroke": pts, "radius": a.radius, "strength": a.strength}
    return core.edit_command(a, "liquify", with_mask(a, [{"op": "liquify", "params": p}]))


def add_commands(sub, edit):
    p = edit("apply-image", cmd_apply_image, "Apply Image / Calculations: blend a source channel (rung 1)")
    p.add_argument("--source", required=True, help="same-size image to take the channel from")
    p.add_argument("--channel", choices=("rgb", "r", "g", "b", "luma"), default="rgb")
    p.add_argument("--blend", default="multiply", help="blend mode (phw explain blend)")
    p.add_argument("--opacity", type=float, default=1.0)
    p.add_argument("--invert", action="store_true", help="invert the source channel")
    p.add_argument("--calc", action="store_true", help="Calculations: reduce the input to --base-channel too (grey out)")
    p.add_argument("--base-channel", choices=("r", "g", "b", "luma"), default="luma")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("fx", cmd_fx, "texture, pointillize, extrude, tiles, lens flare, lighting effects (rung 1)")
    p.add_argument("--texture", type=float, help="-1..1 fine-scale clarity")
    p.add_argument("--texture-radius", type=float, default=1.5)
    p.add_argument("--pointillize", type=int, help="cell size in px")
    p.add_argument("--extrude", help="SIZE,DEPTH (block px, depth 0..1)")
    p.add_argument("--tiles", type=int, help="tiles across")
    p.add_argument("--tile-offset", type=float, default=0.1, help="max shift, fraction of a tile")
    p.add_argument("--bg", default="#ffffff", help="background for pointillize and tiles")
    p.add_argument("--flare", help="X,Y flare centre in px")
    p.add_argument("--brightness", type=float, default=1.0)
    p.add_argument("--light", help="X,Y[,Z] light position in px")
    p.add_argument("--light-kind", choices=("point", "spot"), default="point")
    p.add_argument("--target", help="TX,TY spot aim on the image (default: centre)")
    p.add_argument("--cone", type=float, default=30.0, help="spot half-angle in degrees")
    p.add_argument("--ambient", type=float, default=0.2)
    p.add_argument("--intensity", type=float, default=1.0)
    p.add_argument("--bump", type=float, default=0.0, help="luma bump height (0 = flat)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("lensblur", cmd_lensblur, "lens blur (disc/hexagon bokeh, highlight boost), shape blur (rung 1)")
    p.add_argument("--lens", type=float, help="bokeh radius in px")
    p.add_argument("--iris", choices=("disc", "hexagon"), default="disc")
    p.add_argument("--boost", type=float, default=0.0, help="specular highlight gain (linear light)")
    p.add_argument("--threshold", type=float, default=0.8, help="linear level where the boost starts")
    p.add_argument("--shape-blur", type=float, help="shape radius in px")
    p.add_argument("--shape", choices=("star", "ring", "square", "disc", "hexagon"), default="star")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("liquify", cmd_liquify, "forward-warp push along a stroke (rung 1)")
    p.add_argument("--stroke", required=True, help="'x,y x,y ...' brush path (push) or brush centres (twirl, pucker, bloat)")
    p.add_argument("--mode", choices=("push", "twirl", "pucker", "bloat"), default="push")
    p.add_argument("--radius", type=float, default=20.0)
    p.add_argument("--strength", type=float, default=0.5, help="0..1 of each step carried")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "filter --kernel (custom), canvas --reveal-all, apply-image (Calculations)": (1, "own NumPy"),
    "fx (texture, pointillize, extrude, tiles, lens flare, lighting effects)": (1, "own NumPy"),
    "lensblur (lens, shape), liquify (push)": (1, "own NumPy"),
})
