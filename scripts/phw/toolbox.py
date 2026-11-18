"""Batch 14 (0.15.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

filtergallery:  Filter Gallery: a chain of ordinary phw edit commands applied as one edit, with a
                labelled preview sheet of every stage (source first).
paint:          Blur, Sharpen and Smudge tools along a stroke (round brush, soft falloff).
camove:         Content-Aware Move: lift a rectangle, put it down at an offset, fill where it was.
export-layers:  Export Layers to Files / Artboards to Files from a .psd, .ora or layers recipe.
cropstraighten: Crop and Straighten Photos: find each photo on a flatbed scan, measure its angle,
                write it upright.
Own NumPy and Pillow only; edit ops keep alpha, take --mask/--recipe and replay through `phw run`.
"""
import json
import math
import shlex
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import compose, core, layered, retouch, transform
from .core import OPS, floats
from .grading import with_mask


# ---------------------------------------------------------------- filter gallery
class _Captured(Exception):
    def __init__(self, steps):
        super().__init__("captured")
        self.steps = steps


def chain_steps(chain, src):
    """Parse each chain entry as a phw edit command on `src` and return its steps, without running
    it: edit_command and region_command are swapped for a capture while the command builds its steps."""
    steps = []
    orig_e, orig_r = core.edit_command, retouch.region_command

    def cap_e(a, tag, st, ext=None):
        raise _Captured(st)

    def cap_r(a, tag, p):
        raise _Captured([{"op": tag, "params": p}])
    core.edit_command, retouch.region_command = cap_e, cap_r
    try:
        for entry in chain:
            argv = shlex.split(entry, posix=True)
            if not argv:
                continue
            if argv[0] in ("filtergallery", "run", "variables", "export-layers", "cropstraighten"):
                raise SystemExit(f"filtergallery: {argv[0]} cannot be a chain step")
            a = core.build_parser().parse_args([argv[0], str(src)] + argv[1:])
            try:
                a.fn(a)
            except _Captured as c:
                steps.append({"label": entry, "steps": c.steps})
                continue
            raise SystemExit(f"filtergallery: {argv[0]} is not an edit command")
    finally:
        core.edit_command, retouch.region_command = orig_e, orig_r
    return steps


def thumb(img, size):
    px = img.px
    if px.shape[2] in (1, 2):
        px = np.concatenate([np.repeat(px[..., :1], 3, 2), px[..., 1:]], 2)
    if px.shape[2] == 4:
        a = px[..., 3:]
        px = px[..., :3] * a + 0.8 * (1 - a)
    im = Image.fromarray(np.round(np.clip(px[..., :3], 0, 1) * 255).astype(np.uint8), "RGB")
    im.thumbnail((size, size), Image.LANCZOS)
    return im


def preview_sheet(stages, out, size=192, cols=4):
    """Contact sheet: one tile per stage, label underneath, source first."""
    n = len(stages)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols
    lab = 14
    sheet = Image.new("RGB", (cols * (size + 8) + 8, rows * (size + lab + 8) + 8), (40, 40, 40))
    d = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(stages):
        t = thumb(img, size)
        x0, y0 = 8 + (i % cols) * (size + 8), 8 + (i // cols) * (size + lab + 8)
        sheet.paste(t, (x0 + (size - t.width) // 2, y0 + (size - t.height) // 2))
        d.text((x0, y0 + size + 1), f"{i}. {label}"[:34], fill=(230, 230, 230))
    out = core.free_path(Path(out))
    sheet.save(out)
    return out


def cmd_filtergallery(a):
    t0 = time.time()
    if not a.step:
        raise SystemExit('filtergallery: give one or more --step "COMMAND ARGS", e.g. --step "filter --blur gaussian"')
    groups = chain_steps(a.step, a.input)
    used = core.Used()
    img = core.load(a.input, used)
    stages = [("source", img)]
    steps = []
    for g in groups:
        img = core.apply_steps(img, g["steps"], used)
        stages.append((g["label"], img))
        steps += g["steps"]
    steps = with_mask(a, steps) if a.mask else steps
    if a.mask:  # the mask applies to the whole chain: re-run with it on every step
        img = core.apply_steps(stages[0][1], steps, used)
    out = core.out_for(a.input, a.output, "filtergallery")
    core.save(img, out, getattr(a, "bits", None), used)
    sheet = preview_sheet(stages, a.sheet or out.with_name(out.stem + "-sheet.png"), a.thumb)
    if a.recipe:
        core.record(a.recipe, a.input, steps, out, used, time.time() - t0)
    used.add("filtergallery", 1, "own chain of phw edit steps + Pillow preview sheet")
    return {"command": "filtergallery", "input": str(a.input), "output": str(out), "sheet": str(sheet),
            "stages": [s[0] for s in stages], "rung": used.rung(), "tool": used.tool(), "used": used.items,
            "steps": steps, "notes": img.notes}


# ---------------------------------------------------------------- blur / sharpen / smudge brushes
def stamps(pts, radius):
    """Stamp centres every radius / 4 px along the polyline (a single point is one stamp)."""
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    out = [pts[0]]
    step = max(0.5, radius / 4)
    for p0, p1 in zip(pts[:-1], pts[1:]):
        L = float(np.hypot(*(p1 - p0)))
        n = max(1, int(math.ceil(L / step)))
        out += [p0 + (p1 - p0) * (i / n) for i in range(1, n + 1)]
    return np.array(out)


def stroke_weight(shape, pts, radius, hardness):
    """Max over stamps of the brush falloff: 1 inside hardness x r, smooth to 0 at r, 0 outside."""
    h, w = shape
    Y, X = np.mgrid[0:h, 0:w].astype(np.float64)
    wgt = np.zeros((h, w))
    hard = min(max(hardness, 0.0), 0.999) * radius
    for cx, cy in stamps(pts, radius):
        d = np.hypot(X - cx, Y - cy)
        f = np.clip((radius - d) / max(radius - hard, 1e-6), 0, 1)
        wgt = np.maximum(wgt, f * f * (3 - 2 * f))
    return wgt


def op_paint(img, p, used):
    """blur: src + s w (gaussian - src); sharpen: src + s w (src - gaussian) (unsharp, amount 1 at
    s 1); smudge: a brush-sized pigment patch picked up at the first stamp and laid down at each
    next stamp (patch = canvas (1 - s f) + pigment s f), then picked up again from the result.
    w is the stroke's soft weight: pixels farther than the radius from every stamp are unchanged."""
    tool, s, r = p["tool"], float(p.get("strength", 0.5)), float(p.get("radius", 8))
    c = img.color().astype(np.float64)
    if s == 0:
        used.add("paint." + tool, 1, "identity (strength 0)")
        return img.copy()
    if tool in ("blur", "sharpen"):
        wgt = stroke_weight(c.shape[:2], p["points"], r, float(p.get("hardness", 0.5)))[..., None]
        b = blur_all64(c, float(p.get("sigma", max(1.0, r / 4))))
        delta = (b - c) if tool == "blur" else (c - b)
        out = np.where(wgt > 0, c + s * wgt * delta, c)
    elif tool == "smudge":
        out = smudge(c, stamps(p["points"], r), r, s, float(p.get("hardness", 0.5)))
    else:
        raise ValueError(f"paint: unknown tool {tool}")
    used.add("paint." + tool, 1, f"own {tool} brush along a stroke")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def blur_all64(c, sigma):
    return np.stack([core.gaussian_blur(c[..., i].astype(np.float32), sigma).astype(np.float64)
                     for i in range(c.shape[2])], axis=2)


def smudge(c, centres, r, s, hardness):
    out = c.copy()
    h, w = c.shape[:2]
    R = int(math.ceil(r))
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1].astype(np.float64)
    d = np.hypot(xx, yy)
    hard = min(max(hardness, 0.0), 0.999) * r
    f = np.clip((r - d) / max(r - hard, 1e-6), 0, 1)
    f = (f * f * (3 - 2 * f))[..., None]

    def window(cx, cy):
        x0, y0 = int(round(cx)) - R, int(round(cy)) - R
        xs, ys = slice(max(0, x0), min(w, x0 + 2 * R + 1)), slice(max(0, y0), min(h, y0 + 2 * R + 1))
        ks = (slice(ys.start - y0, ys.stop - y0), slice(xs.start - x0, xs.stop - x0))
        return ys, xs, ks
    ys, xs, ks = window(*centres[0])
    pig = np.zeros((2 * R + 1, 2 * R + 1, c.shape[2]))
    pig[ks] = out[ys, xs]
    have = np.zeros((2 * R + 1, 2 * R + 1, 1))
    have[ks] = 1
    for cx, cy in centres[1:]:
        ys, xs, ks = window(cx, cy)
        k = s * f[ks] * have[ks]
        out[ys, xs] = out[ys, xs] * (1 - k) + pig[ks] * k
        pig = np.zeros_like(pig)
        have = np.zeros_like(have)
        pig[ks], have[ks] = out[ys, xs], 1
    return out


# ---------------------------------------------------------------- content-aware move
def op_camove(img, p, used):
    """Copy the rect (x, y, w, h) to (x + dx, y + dy) bit for bit, then fill the part of the old
    rect the new one does not cover with retouch's content-aware fill (method as `fill`). Pixels
    outside both rects are the source unchanged."""
    x, y, rw, rh = (int(round(v)) for v in p["rect"])
    dx, dy = (int(round(v)) for v in p["offset"])
    c = img.px
    h, w = c.shape[:2]
    if not (0 <= x and 0 <= y and x + rw <= w and y + rh <= h):
        raise ValueError(f"camove: rect {p['rect']} outside the image {w}x{h}")
    patch = c[y:y + rh, x:x + rw].copy()
    hole = np.zeros((h, w), bool)
    hole[y:y + rh, x:x + rw] = True
    nx0, ny0 = max(0, x + dx), max(0, y + dy)
    nx1, ny1 = min(w, x + dx + rw), min(h, y + dy + rh)
    placed = np.zeros((h, w), bool)
    placed[ny0:ny1, nx0:nx1] = True
    hole &= ~placed
    out = img
    if hole.any():
        fp = {"method": p.get("method", "auto"), "patch": p.get("patch", 7), "seed": p.get("seed", 0)}
        # the moved patch is not a fill source: fill as if the patch were already at its new place
        tmp = c.copy()
        tmp[ny0:ny1, nx0:nx1] = patch[ny0 - y - dy:ny1 - y - dy, nx0 - x - dx:nx1 - x - dx]
        timg = img.copy(px=tmp)
        filled = retouch.fill_color(timg, timg.color(), hole, fp, used)
        out = retouch.composite(timg, filled, hole)
    else:
        tmp = c.copy()
        tmp[ny0:ny1, nx0:nx1] = patch[ny0 - y - dy:ny1 - y - dy, nx0 - x - dx:nx1 - x - dx]
        out = img.copy(px=tmp)
    used.add("camove", 1, "own move + content-aware fill of the vacated area")
    return out


# ---------------------------------------------------------------- export layers / artboards
def layer_bounds(rgba):
    ys, xs = np.nonzero(rgba[..., 3] > 0)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def export_layers(src, out_dir, trim=False, artboards=False, hidden=False, space="gamma"):
    """One PNG per pixel layer (each rendered alone on the canvas with its opacity, mask and
    blend over transparency), or with artboards one per top-level group (the group flattened,
    cropped to its content). --trim crops to the visible pixels and records the offset."""
    t0 = time.time()
    used = core.Used()
    doc = layered.read_layered(src, used)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    if artboards:
        todo = [(l, l.name) for l in doc.layers if l.group and (l.visible or hidden)]
        if not todo:
            raise SystemExit("export-layers --artboards: the file has no top-level groups")
        trim = True
    else:
        todo = []

        def walk(ls, prefix, vis):
            for l in ls:
                v = vis and l.visible
                if l.group:
                    walk(l.children, prefix + layered._safe(l.name) + "-", v)
                elif v or hidden:
                    todo.append((l, prefix + l.name))
        walk(doc.layers, "", True)
    written = []
    for i, (lay, name) in enumerate(todo, 1):
        was = lay.visible
        lay.visible = True
        rgba = compose.composite_doc(compose.Doc(doc.width, doc.height, [lay]), space)
        lay.visible = was
        box = (0, 0, doc.width, doc.height)
        if trim:
            box = layer_bounds(rgba)
            if box is None:
                items.append({"layer": name, "skipped": "empty"})
                continue
        x0, y0, x1, y1 = box
        fp = core.free_path(out_dir / f"{i:03d}-{layered._safe(name)}.png")
        Image.fromarray(np.round(np.clip(rgba[y0:y1, x0:x1], 0, 1) * 255).astype(np.uint8), "RGBA").save(fp)
        items.append({"layer": name, "file": str(fp), "x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0,
                      "blend": lay.blend})
        written.append(str(fp))
    man = core.free_path(out_dir / "export-manifest.json")
    man.write_text(json.dumps({"source": str(src), "canvas": [doc.width, doc.height], "items": items}, indent=1),
                   encoding="utf-8")
    used.add("export-layers", 1, "own per-layer render (W3C compositor)")
    return {"command": "export-layers", "input": str(src), "output_folder": str(out_dir), "written": written,
            "items": items, "manifest": str(man), "seconds": round(time.time() - t0, 3), "rung": used.rung(),
            "tool": used.tool(), "used": used.items, "notes": doc.notes}


def cmd_export_layers(a):
    return export_layers(a.input, a.out_dir, a.trim, a.artboards, a.hidden)


# ---------------------------------------------------------------- crop and straighten photos
def label(mask):
    nd = core.probe("scipy.ndimage")
    if nd is not None:
        lab, n = nd.label(mask)
        return lab, n
    lab = np.zeros(mask.shape, np.int32)
    n = 0
    h, w = mask.shape
    for sy, sx in zip(*np.nonzero(mask)):
        if lab[sy, sx]:
            continue
        n += 1
        stack = [(sy, sx)]
        lab[sy, sx] = n
        while stack:
            y, x = stack.pop()
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n
                    stack.append((yy, xx))
    return lab, n


def min_area_angle(xs, ys):
    """Angle (degrees, -45..45) whose rotation gives the smallest axis-aligned box around the
    points: a coarse 1 degree search, then 0.05 degree steps around the best."""
    def area(t):
        a = math.radians(t)
        u = xs * math.cos(a) + ys * math.sin(a)
        v = -xs * math.sin(a) + ys * math.cos(a)
        return (u.max() - u.min()) * (v.max() - v.min())
    best = min(np.arange(-45, 45, 1.0), key=area)
    return float(min(np.arange(best - 1, best + 1.0001, 0.05), key=area))


def crop_straighten(src, out_dir, threshold=0.12, min_area=0.01, inset=1):
    t0 = time.time()
    used = core.Used()
    img = core.load(src, used)
    c = img.color()[..., :3] if img.nc >= 3 else np.repeat(img.color(), 3, 2)
    h, w = c.shape[:2]
    border = np.concatenate([c[0], c[-1], c[:, 0], c[:, -1]])
    bg = np.median(border, axis=0)
    fg = np.abs(c - bg).max(axis=2) > threshold
    fg = retouch.morph(fg.astype(np.float32), 1, False) > 0.5  # open: drop dust
    fg = retouch.morph(fg.astype(np.float32), 1, True) > 0.5
    lab, n = label(fg)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    photos = []
    for k in range(1, n + 1):
        ys, xs = np.nonzero(lab == k)
        if len(xs) < min_area * h * w:
            continue
        xs, ys = xs.astype(np.float64), ys.astype(np.float64)
        ang = min_area_angle(xs, ys)
        a = math.radians(ang)
        u = xs * math.cos(a) + ys * math.sin(a)
        v = -xs * math.sin(a) + ys * math.cos(a)
        u0, v0 = u.min() + inset, v.min() + inset
        ow, oh = int(round(u.max() - u.min() + 1)) - 2 * inset, int(round(v.max() - v.min() + 1)) - 2 * inset
        if ow < 2 or oh < 2:
            continue
        J, I = np.meshgrid(np.arange(ow, dtype=np.float64), np.arange(oh, dtype=np.float64))
        U, V = u0 + J, v0 + I
        X = U * math.cos(a) - V * math.sin(a)
        Y = U * math.sin(a) + V * math.cos(a)
        res = transform.remap(img, X.astype(np.float32), Y.astype(np.float32), used, "cropstraighten")
        fp = core.free_path(out_dir / f"{Path(src).stem}-photo{len(photos) + 1:02d}.png")
        core.save(res, fp, None, used)
        photos.append({"file": str(fp), "angle": round(ang, 2), "width": ow, "height": oh,
                       "centre": [round(float(xs.mean()), 1), round(float(ys.mean()), 1)]})
    used.add("cropstraighten", 1, "own background key, components, min-area angle, remap")
    return {"command": "cropstraighten", "input": str(src), "output_folder": str(out_dir), "photos": photos,
            "background": [round(float(x), 4) for x in bg], "seconds": round(time.time() - t0, 3),
            "rung": used.rung(), "tool": used.tool(), "used": used.items}


def cmd_cropstraighten(a):
    return crop_straighten(a.input, a.out_dir, a.threshold, a.min_area)


OPS.update({"paint": op_paint, "camove": op_camove})


# ---------------------------------------------------------------- commands
def cmd_paint(a):
    p = {"tool": a.tool, "points": [floats(t, 2) for t in a.stroke.replace(";", " ").split()],
         "radius": a.radius, "strength": a.strength, "hardness": a.hardness}
    if a.sigma:
        p["sigma"] = a.sigma
    return core.edit_command(a, "paint", with_mask(a, [{"op": "paint", "params": p}]))


def cmd_camove(a):
    p = {"rect": floats(a.rect, 4), "offset": floats(a.to, 2), "method": a.method, "seed": a.seed}
    return core.edit_command(a, "camove", with_mask(a, [{"op": "camove", "params": p}]))


def add_commands(sub, edit):
    p = edit("filtergallery", cmd_filtergallery, "Filter Gallery: chain phw edit commands, preview sheet (rung 1)")
    p.add_argument("--step", action="append", help='one phw edit command without the input, e.g. "filter --blur gaussian"; repeat')
    p.add_argument("--sheet", help="preview sheet PNG (default: OUTPUT-sheet.png)")
    p.add_argument("--thumb", type=int, default=192, help="sheet tile size in px")
    p.add_argument("--mask", help="8-bit mask PNG: the whole chain applies where white")
    p = edit("paint", cmd_paint, "Blur, Sharpen, Smudge brushes along a stroke (rung 1)")
    p.add_argument("--tool", choices=("blur", "sharpen", "smudge"), required=True)
    p.add_argument("--stroke", required=True, help="'x,y x,y ...' brush path")
    p.add_argument("--radius", type=float, default=8.0, help="brush radius in px")
    p.add_argument("--strength", type=float, default=0.5, help="0..1")
    p.add_argument("--hardness", type=float, default=0.5, help="0 soft .. 1 hard edge")
    p.add_argument("--sigma", type=float, help="blur/sharpen Gaussian sigma (default radius / 4)")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("camove", cmd_camove, "Content-Aware Move: move a rect, fill where it was (rung 1)")
    p.add_argument("--rect", required=True, help="x,y,width,height to move")
    p.add_argument("--to", required=True, help="dx,dy offset")
    p.add_argument("--method", choices=("auto", "patch", "membrane", "thin"), default="auto", help="fill method")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = sub.add_parser("export-layers", help="Export Layers / Artboards to Files: one PNG per layer or top group")
    p.add_argument("input", help=".psd, .ora or layers recipe .json")
    p.add_argument("out_dir")
    p.add_argument("--trim", action="store_true", help="crop each to its visible pixels (offset in the manifest)")
    p.add_argument("--artboards", action="store_true", help="one PNG per top-level group, trimmed")
    p.add_argument("--hidden", action="store_true", help="also export hidden layers")
    p.set_defaults(fn=cmd_export_layers)
    p = sub.add_parser("cropstraighten", help="Crop and Straighten Photos: each photo on a scan, upright")
    p.add_argument("input")
    p.add_argument("out_dir")
    p.add_argument("--threshold", type=float, default=0.12, help="max channel distance from the background colour")
    p.add_argument("--min-area", type=float, default=0.01, help="smallest photo as a fraction of the scan")
    p.set_defaults(fn=cmd_cropstraighten)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "filtergallery, paint (blur/sharpen/smudge), camove, export-layers, cropstraighten": (1, "own NumPy + Pillow"),
})
