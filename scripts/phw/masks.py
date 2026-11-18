"""Selections and masks (select, mask) and background removal (cutout).

A mask is a float32 HxW array in 0..1 inside, an 8-bit greyscale PNG on disk (white =
selected). Mask steps are recipe steps {"op": "mask.<name>", "params": {...}}; a recipe
with "kind": "mask" replays them with `phw.py run`. Make-steps (color, luma, edge, flood,
rect, ellipse, polygon, file) take "mode": replace | add | subtract | intersect, which is
how masks combine. Rules: references/selection-matting.md.
"""
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import core
from .core import (OPS, Used, free_path, gaussian_blur, load, log_line, out_for, probe, sha256, to_lin)

__all__ = ["rgb_to_lab", "disc_offsets", "morph", "flood_region", "apply_mask_steps", "save_mask",
           "read_mask", "op_cutout", "combine"]


# ---------------------------------------------------------------- colour distance
def rgb_to_lab(c):
    """Encoded sRGB (HxWx3, 0..1) to CIE Lab (D65)."""
    lin = to_lin(c[..., :3]).astype(np.float64)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def rgb3(img):
    c = img.color()
    return np.repeat(c, 3, axis=2) if c.shape[2] == 1 else c[..., :3]


def soft_threshold(d, tol, soft):
    """1 where d <= tol, falling linearly to 0 at tol + soft."""
    if soft <= 0:
        return (d <= tol).astype(np.float32)
    return np.clip((tol + soft - d) / soft, 0, 1).astype(np.float32)


# ---------------------------------------------------------------- morphology and regions
def disc_offsets(r):
    r = int(r)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy <= r * r + r).astype(np.uint8)  # +r: rounder small discs, as GIMP


def morph(m, r, grow, used=None):
    """Grey dilation (grow) or erosion (shrink) by a disc of radius r. Outside the image counts
    as unselected when growing and as selected when shrinking, so masks touching the border keep it."""
    r = int(round(r))
    if r <= 0:
        return m
    k = disc_offsets(r)
    cv2 = probe("cv2")
    if cv2 is not None:
        if used:
            used.add("mask.grow" if grow else "mask.shrink", 2, "OpenCV dilate/erode")
        f = cv2.dilate if grow else cv2.erode
        return f(m.astype(np.float32), k, borderType=cv2.BORDER_CONSTANT, borderValue=0.0 if grow else 1.0)
    if used:
        used.add("mask.grow" if grow else "mask.shrink", 1, "NumPy disc max/min")
    h, w = m.shape
    p = np.pad(m, r, constant_values=0.0 if grow else 1.0)
    out = np.full_like(m, 0.0 if grow else 1.0)
    fn = np.maximum if grow else np.minimum
    for dy, dx in zip(*np.nonzero(k)):
        fn(out, p[dy:dy + h, dx:dx + w], out=out)
    return out


def flood_region(cand, seeds, used=None):
    """Pixels of boolean `cand` 4-connected to any True of boolean `seeds`."""
    nd = probe("scipy.ndimage")
    if nd is not None:
        lab, _ = nd.label(cand)
        ids = np.unique(lab[seeds & cand])
        ids = ids[ids > 0]
        if used:
            used.add("flood", 2, "scipy.ndimage.label")
        return np.isin(lab, ids) if len(ids) else np.zeros_like(cand)
    if used:
        used.add("flood", 1, "NumPy iterative 4-neighbour fill")
    reg = seeds & cand
    while True:
        g = reg.copy()
        g[1:] |= reg[:-1]
        g[:-1] |= reg[1:]
        g[:, 1:] |= reg[:, :-1]
        g[:, :-1] |= reg[:, 1:]
        g &= cand
        if (g == reg).all():
            return reg
        # jump ahead along rows and columns: cheap long-range propagation
        reg = g


def combine(cur, new, mode):
    if cur is None or mode == "replace":
        return new
    if mode == "add":
        return np.maximum(cur, new)
    if mode == "subtract":
        return np.minimum(cur, 1 - new)
    if mode == "intersect":
        return np.minimum(cur, new)
    raise ValueError(f"unknown combine mode {mode}")


def draw_shape(shape, kind, p):
    h, w = shape
    ss = int(p.get("antialias", 1)) or 1
    im = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(im)
    if kind in ("rect", "ellipse"):
        x, y, bw, bh = (float(v) * ss for v in p["box"])
        box = [x, y, x + bw - 1, y + bh - 1] if ss == 1 else [x, y, x + bw, y + bh]
        (d.rectangle if kind == "rect" else d.ellipse)(box, fill=255)
    else:
        d.polygon([(float(a) * ss, float(b) * ss) for a, b in p["points"]], fill=255)
    if ss > 1:
        im = im.resize((w, h), Image.BOX)
    return np.asarray(im, np.float32) / 255.0


def read_mask(path, shape=None):
    m = np.asarray(Image.open(path).convert("L"), np.float32) / 255.0
    if shape is not None and m.shape != tuple(shape):
        raise ValueError(f"mask {path} is {m.shape[::-1]}, expected {tuple(shape)[::-1]}")
    return m


def save_mask(m, path, used=None):
    path = Path(path)
    a = np.round(np.clip(m, 0, 1) * 255).astype(np.uint8)
    with open(path, "xb") as f:  # never overwrite
        Image.fromarray(a, "L").save(f, "PNG")
    if used:
        used.add("save mask", 1, "Pillow")
    return path


# ---------------------------------------------------------------- mask steps
MAKE = ("text", "color", "luma", "edge", "flood", "rect", "ellipse", "polygon", "file")


def make_mask(img, shape, kind, p, used, base_dir):
    if kind in ("rect", "ellipse", "polygon"):
        used.add(f"mask.{kind}", 1, "Pillow ImageDraw")
        return draw_shape(shape, kind, p)
    if kind == "file":
        f = Path(p["file"])
        if base_dir and not f.is_absolute():
            f = Path(base_dir) / f
        used.add("mask.file", 1, "Pillow")
        return read_mask(f, shape)
    if img is None:
        raise ValueError(f"mask.{kind} needs an image (use select, not mask)")
    if kind == "text":
        from . import comfy
        try:
            m, info = comfy.text_mask(rgb3(img), p["text"], p.get("seed", 1))
        except comfy.Unavailable as e:
            raise SystemExit(f"select --text needs rung 3 and cannot fall back (no rung 1/2 method reads text): {e}")
        used.add("mask.text", 3, f"ComfyUI {info['model']}")
        return np.clip(m, 0, 1).astype(np.float32)
    if kind == "luma":
        c = rgb3(img)
        y = c @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        lo, hi = p.get("range", [0.5, 1.0])
        soft = float(p.get("soft", 0))
        used.add("mask.luma", 1, "NumPy")
        return np.minimum(soft_threshold(lo - y, 0, soft), soft_threshold(y - hi, 0, soft))
    if kind == "edge":
        y = rgb3(img) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        q = np.pad(y, 1, mode="edge")
        gx = (q[:-2, 2:] + 2 * q[1:-1, 2:] + q[2:, 2:]) - (q[:-2, :-2] + 2 * q[1:-1, :-2] + q[2:, :-2])
        gy = (q[2:, :-2] + 2 * q[2:, 1:-1] + q[2:, 2:]) - (q[:-2, :-2] + 2 * q[:-2, 1:-1] + q[:-2, 2:])
        mag = np.hypot(gx, gy) / 4.0  # 1.0 = a full black-to-white step
        used.add("mask.edge", 1, "NumPy Sobel")
        return soft_threshold(-mag, -float(p.get("threshold", 0.1)), float(p.get("soft", 0)))
    lab = rgb_to_lab(rgb3(img))
    if "pick" in p or ("seed" in p and "color" not in p):
        x, y = (int(v) for v in p.get("pick", p.get("seed")))
        ref = lab[y, x]
    else:
        ref = rgb_to_lab(np.asarray(p["color"], np.float32).reshape(1, 1, 3))[0, 0]
    d = np.sqrt(((lab - ref) ** 2).sum(-1))
    tol, soft = float(p.get("tol", 10)), float(p.get("soft", 0))
    if kind == "color":
        used.add("mask.color", 1, "NumPy Lab distance")
        return soft_threshold(d, tol, soft)
    # flood (magic wand): connected to the seed, within tol (+soft for the edge ramp)
    seeds = np.zeros(d.shape, bool)
    x, y = (int(v) for v in p.get("seed", p.get("pick")))
    seeds[y, x] = True
    reg = flood_region(d <= tol + soft, seeds, used)
    return soft_threshold(d, tol, soft) * reg


def apply_mask_steps(img, mask, steps, used, base_dir=None, shape=None):
    """Run mask steps. img may be None (mask command); mask is the starting mask or None."""
    if shape is None:
        shape = img.px.shape[:2] if img is not None else mask.shape
    m = mask
    for st in steps:
        op = st["op"].split(".", 1)[1]
        p = dict(st.get("params") or {})
        if op in MAKE:
            m = combine(m, make_mask(img, shape, op, p, used, base_dir), p.get("mode", "replace" if m is None else "add"))
            continue
        if m is None:
            raise ValueError(f"mask.{op} needs a mask: start with a selection step")
        if op == "grow":
            m = morph(m, p["px"], True, used)
        elif op == "shrink":
            m = morph(m, p["px"], False, used)
        elif op == "feather":
            m = np.clip(gaussian_blur(m.astype(np.float32), float(p["sigma"]), used), 0, 1) if p["sigma"] > 0 else m
        elif op == "invert":
            m = 1 - m
            used.add("mask.invert", 1, "NumPy")
        elif op == "threshold":
            m = (m >= float(p.get("at", 0.5))).astype(np.float32)
            used.add("mask.threshold", 1, "NumPy")
        else:
            raise ValueError(f"unknown mask op {op}")
    if m is None:
        raise ValueError("no selection step given")
    return np.clip(m, 0, 1).astype(np.float32)


# ---------------------------------------------------------------- cutout
def cutout_mask(img, p, used):
    method = p.get("method", "auto")
    h, w = img.px.shape[:2]
    if method == "birefnet":
        from . import comfy
        try:
            m, info = comfy.birefnet_mask(rgb3(img))
            used.add("cutout", 3, f"ComfyUI BiRefNet ({info['model']})")
            img.notes.append(f"rung 3 BiRefNet via {info['server']}: {info['seconds']} s, {info['queued_ahead']} jobs ahead")
            return m.astype(np.float32), "birefnet"
        except comfy.Unavailable as e:
            img.notes.append(f"fell back: {e}")
            method = "auto"
    cv2 = probe("cv2")
    if method == "grabcut" and cv2 is None:
        raise SystemExit("cutout: GrabCut needs OpenCV (rung 2), which is absent or hidden; use --method key")
    if method in ("auto", "grabcut") and cv2 is not None:
        inset = float(p.get("inset", 0.04))
        rect = p.get("rect") or [int(w * inset), int(h * inset), max(1, int(w * (1 - 2 * inset))),
                                 max(1, int(h * (1 - 2 * inset)))]
        a8 = np.round(rgb3(img)[..., ::-1] * 255).astype(np.uint8)
        gm = np.zeros((h, w), np.uint8)
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.setRNGSeed(int(p.get("seed") or 0))
        cv2.grabCut(a8, gm, tuple(int(v) for v in rect), bgd, fgd, int(p.get("iterations", 5)), cv2.GC_INIT_WITH_RECT)
        used.add("cutout", 2, "OpenCV GrabCut")
        return ((gm == cv2.GC_FGD) | (gm == cv2.GC_PR_FGD)).astype(np.float32), "grabcut"
    # rung 1: key out the border colour, flooding from the border
    lab = rgb_to_lab(rgb3(img))
    border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    ref = np.asarray(p["key"], np.float32) if p.get("key") else None
    ref = rgb_to_lab(ref.reshape(1, 1, 3))[0, 0] if ref is not None else np.median(border, axis=0)
    d = np.sqrt(((lab - ref) ** 2).sum(-1))
    tol = float(p.get("tol", 12))
    seeds = np.zeros((h, w), bool)
    seeds[0], seeds[-1], seeds[:, 0], seeds[:, -1] = True, True, True, True
    bg = flood_region(d <= tol, seeds, used)
    used.add("cutout", 1, "colour key + border flood")
    return 1 - bg.astype(np.float32), "key"


def op_cutout(img, p, used):
    m, method = cutout_mask(img, p, used)
    if p.get("shrink"):
        m = morph(m, p["shrink"], False, used)
    if p.get("feather"):
        m = np.clip(gaussian_blur(m, float(p["feather"]), used), 0, 1)
    c = img.color()
    old = img.px[..., -1] if img.alpha else np.ones(m.shape, np.float32)
    out = img.copy(px=np.concatenate([c, (old * m)[..., None]], axis=2), alpha=True)
    out.notes = img.notes + [f"cutout method: {method}; colour channels unchanged, only alpha set"]
    out._mask = m
    return out


OPS["cutout"] = op_cutout


# ---------------------------------------------------------------- commands
def mask_steps_from_args(a, with_image):
    steps = []
    mode = a.combine

    def make(op, params):
        params["mode"] = "replace" if not steps else mode
        steps.append({"op": f"mask.{op}", "params": params})

    if with_image:
        if getattr(a, "text", None):
            make("text", {"text": a.text, "seed": a.seed, "model": "Florence-2-large + sam2.1_hiera_base_plus"})
        if a.color or a.pick:
            p = {"tol": a.tol, "soft": a.soft}
            if a.pick:
                p["pick"] = core.floats(a.pick, 2)
            else:
                p["color"] = core.floats(a.color, 3)
            make("color", p)
        if a.luma:
            make("luma", {"range": core.floats(a.luma, 2), "soft": a.soft})
        if a.edge is not None:
            make("edge", {"threshold": a.edge, "soft": a.soft})
        if a.flood:
            make("flood", {"seed": core.floats(a.flood, 2), "tol": a.tol, "soft": a.soft})
    for kind in ("rect", "ellipse"):
        v = getattr(a, kind)
        if v:
            make(kind, {"box": core.floats(v, 4), "antialias": a.antialias})
    if a.polygon:
        make("polygon", {"points": [core.floats(q, 2) for q in a.polygon.split()], "antialias": a.antialias})
    for mode2 in ("add", "subtract", "intersect"):
        for f in getattr(a, mode2) or []:
            steps.append({"op": "mask.file", "params": {"file": str(Path(f).resolve()), "mode": mode2}})
    if a.grow:
        steps.append({"op": "mask.grow", "params": {"px": a.grow}})
    if a.shrink:
        steps.append({"op": "mask.shrink", "params": {"px": a.shrink}})
    if a.feather:
        steps.append({"op": "mask.feather", "params": {"sigma": a.feather}})
    if a.invert:
        steps.append({"op": "mask.invert", "params": {}})
    return steps


def record_kind(recipe, kind, src, steps, out, used, seconds, extra=None):
    recipe = Path(recipe)
    if recipe.exists():
        r = json.loads(recipe.read_text(encoding="utf-8"))
        if r.get("kind", "image") != kind:
            raise SystemExit(f"{recipe} is a {r.get('kind', 'image')} recipe, not {kind}")
    else:
        recipe.parent.mkdir(parents=True, exist_ok=True)
        r = {"version": 1, "kind": kind, "steps": []}
        if src:
            r["source"] = {"file": str(Path(src).resolve()).replace("\\", "/"), "sha256": sha256(src)}
        r.update(extra or {})
    r["steps"] += steps
    recipe.write_text(json.dumps(r, indent=1), encoding="utf-8")
    log_line(recipe.parent / "log.jsonl", [s["op"] for s in steps], out, used, seconds)


def cmd_select(a):
    t0 = time.time()
    used = Used()
    img = load(a.input, used)
    steps = mask_steps_from_args(a, True)
    if not steps:
        raise SystemExit("select: give at least one of --text --color --pick --luma --edge --flood --rect --ellipse --polygon")
    m = apply_mask_steps(img, None, steps, used)
    out = save_mask(m, out_for(a.input, a.output, "mask", ".png"), used)
    if a.recipe:
        record_kind(a.recipe, "mask", a.input, steps, out, used, time.time() - t0, {"start": "select"})
    return {"command": "select", "input": str(a.input), "output": str(out), "selected_share": round(float(m.mean()), 4),
            "rung": used.rung(), "tool": used.tool(), "used": used.items, "steps": steps}


def cmd_mask(a):
    t0 = time.time()
    used = Used()
    if a.input:
        m = read_mask(a.input)
        src = a.input
    elif a.size:
        w, h = (int(v) for v in core.floats(a.size, 2))
        m, src = None, None
    else:
        raise SystemExit("mask: give a mask PNG or --size W,H")
    steps = mask_steps_from_args(a, False)
    if not steps:
        raise SystemExit("mask: nothing to do (give --grow --shrink --feather --invert --add --subtract --intersect or a shape)")
    if m is not None:
        for s in steps:  # shapes combine with the input mask instead of replacing it
            if s["op"] in ("mask.rect", "mask.ellipse", "mask.polygon") and s["params"]["mode"] == "replace":
                s["params"]["mode"] = a.combine
    m = apply_mask_steps(None, m, steps, used, shape=(h, w) if m is None else None)
    out = free_path(Path(a.output)) if a.output else (
        out_for(a.input, None, "mask") if a.input else free_path(Path.cwd() / "mask.png"))
    if a.input and Path(out).resolve() == Path(a.input).resolve():
        raise RuntimeError("refusing to write over the source")
    save_mask(m, out, used)
    if a.recipe:
        record_kind(a.recipe, "mask", src, steps, out, used, time.time() - t0,
                    {"start": "mask" if src else "empty", "size": [int(m.shape[1]), int(m.shape[0])]})
    return {"command": "mask", "input": str(a.input), "output": str(out), "selected_share": round(float(m.mean()), 4),
            "rung": used.rung(), "tool": used.tool(), "used": used.items, "steps": steps}


def run_mask_recipe(a, recipe, r):
    t0 = time.time()
    used = Used()
    start = r.get("start", "select")
    img, m, src = None, None, None
    if r.get("source"):
        src = Path(r["source"]["file"])
        if not src.is_absolute():
            src = recipe.parent / src
    notes = []
    if src and sha256(src) != r["source"].get("sha256"):
        notes.append("source sha256 differs from the recipe: the source changed")
    if start == "select":
        img = load(src, used)
    elif start == "mask":
        m = read_mask(src)
    w, h = r.get("size", [0, 0])
    m = apply_mask_steps(img, m, r["steps"], used, recipe.parent, shape=(h, w) if start == "empty" else None)
    out = Path(a.output) if a.output else recipe.parent / "out" / f"{(src.stem if src else 'mask')}-mask.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out = free_path(out)
    save_mask(m, out, used)
    log_line(recipe.parent / "log.jsonl", [s["op"] for s in r["steps"]], out, used, time.time() - t0, {"run": True})
    return {"command": "run", "kind": "mask", "recipe": str(recipe), "output": str(out), "steps": len(r["steps"]),
            "rung": used.rung(), "tool": used.tool(), "notes": notes}


core.RUN_KINDS["mask"] = run_mask_recipe


def cmd_cutout(a):
    p = {"method": a.method}
    for k in ("tol", "feather", "shrink", "iterations"):
        v = getattr(a, k)
        if v is not None:
            p[k] = v
    if a.rect:
        p["rect"] = [int(v) for v in core.floats(a.rect, 4)]
    if a.key:
        p["key"] = core.floats(a.key, 3)
    if a.method == "birefnet":
        from . import comfy
        p.update(model=comfy.BIREFNET, seed=None)  # BiRefNet is deterministic: no seed
    ext = None if Path(a.output or a.input).suffix.lower() in (".png", ".webp", ".tif", ".tiff") else ".png"
    r = core.edit_command(a, "cutout", [{"op": "cutout", "params": p}], ext)
    if a.mask_out:
        img = load(r["output"])
        r["mask_output"] = str(save_mask(img.px[..., -1], free_path(Path(a.mask_out))))
    return r


def add_commands(sub, edit):
    def mask_flags(p, with_image):
        if with_image:
            p.add_argument("--color", help="r,g,b 0..1: colour range (Lab distance)")
            p.add_argument("--pick", help="x,y: colour range around this pixel's colour")
            p.add_argument("--luma", help="lo,hi 0..1: luminance range")
            p.add_argument("--edge", type=float, help="Sobel edge threshold (1 = full black-white step)")
            p.add_argument("--flood", help="x,y: magic wand from this seed (4-connected)")
            p.add_argument("--tol", type=float, default=10.0, help="colour tolerance in Lab Delta E (default 10)")
            p.add_argument("--soft", type=float, default=0.0, help="soft ramp width past the tolerance")
        p.add_argument("--rect", help="x,y,w,h")
        p.add_argument("--ellipse", help="x,y,w,h bounding box")
        p.add_argument("--polygon", help="'x,y x,y x,y ...'")
        p.add_argument("--antialias", type=int, default=1, help="supersampling for shapes (1 = hard edge)")
        p.add_argument("--combine", choices=("add", "subtract", "intersect"), default="add",
                       help="how later selections combine with the first (default add)")
        p.add_argument("--add", action="append", help="union with this mask PNG")
        p.add_argument("--subtract", action="append", help="remove this mask PNG")
        p.add_argument("--intersect", action="append", help="keep only the overlap with this mask PNG")
        p.add_argument("--grow", type=float, help="dilate by N px (disc)")
        p.add_argument("--shrink", type=float, help="erode by N px (disc)")
        p.add_argument("--feather", type=float, help="Gaussian sigma in px")
        p.add_argument("--invert", action="store_true")
        p.add_argument("-o", "--output", help="mask PNG (never overwritten)")
        p.add_argument("--recipe", help="append the steps to this mask recipe.json")

    p = sub.add_parser("select", help="make an 8-bit mask from an image: text (rung 3), colour, luma, edge, flood, shapes")
    p.add_argument("input")
    p.add_argument("--text", help="select what this phrase names (rung 3: Florence-2 boxes into SAM 2.1 via ComfyUI)")
    p.add_argument("--seed", type=int, default=1, help="seed for --text (recorded in the recipe)")
    mask_flags(p, True)
    p.set_defaults(fn=cmd_select)
    p = sub.add_parser("mask", help="edit a mask: grow, shrink, feather, invert, add/subtract/intersect, shapes")
    p.add_argument("input", nargs="?")
    p.add_argument("--size", help="W,H for a new empty mask")
    mask_flags(p, False)
    p.set_defaults(fn=cmd_mask)
    p = edit("cutout", cmd_cutout, "remove the background: GrabCut (rung 2) or colour key (rung 1)")
    p.add_argument("--method", "--model", dest="method", choices=("auto", "grabcut", "key", "birefnet"), default="auto",
                   help="birefnet: rung 3 via the local ComfyUI, falls back to auto when it cannot run")
    p.add_argument("--rect", help="x,y,w,h around the subject (GrabCut; default 4%% inset)")
    p.add_argument("--key", help="r,g,b background colour for --method key (default: border median)")
    p.add_argument("--tol", type=float, help="key tolerance, Lab Delta E (default 12)")
    p.add_argument("--iterations", type=int, help="GrabCut iterations (default 5)")
    p.add_argument("--shrink", type=float, help="erode the subject mask by N px")
    p.add_argument("--feather", type=float, help="Gaussian sigma for the edge")
    p.add_argument("--mask-out", help="also write the subject mask PNG here")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "select/mask (colour, luma, edge, shapes)": (1, "NumPy, Pillow ImageDraw"),
    "mask grow/shrink": (2, "OpenCV") if probe("cv2") else (1, "NumPy disc"),
    "flood fill": (2, "scipy.ndimage.label") if probe("scipy.ndimage") else (1, "NumPy iterative fill"),
    "cutout": (2, "OpenCV GrabCut") if probe("cv2") else (1, "colour key + border flood"),
    "cutout --method birefnet": (3, "ComfyUI RemoveBackground + birefnet.safetensors (falls back)"),
    "select --text": (3, "ComfyUI Florence-2-large + SAM 2.1 base_plus (no fallback for text)"),
})
