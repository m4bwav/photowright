"""Batch, sheet, diff (rung 1: Pillow + NumPy).

batch  a recipe's steps over a folder. Dry run by default (lists what would be written); --apply runs.
       Sources are only read. Outputs go to a separate folder and are never written over. A manifest
       (batch-manifest.json in the output folder) keys each source by path, its sha256 and the recipe's
       steps hash, so a second run with nothing changed writes nothing. A file that fails is reported and
       the rest finish.
sheet  images side by side in a grid with labels (before/after, variations), on a checkerboard for alpha.
diff   what changed between two images and where: heatmap PNG, stats (max, mean, PSNR, changed share,
       bounding box, number of changed regions).
"""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import core
from .core import Used, load, save, free_path, sha256, apply_steps

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}


# ---------------------------------------------------------------- batch
def steps_hash(steps):
    return hashlib.sha256(json.dumps(steps, sort_keys=True).encode()).hexdigest()[:16]


def batch(recipe_path, folder, out_dir=None, apply=False, pattern="*", recursive=False, ext=None):
    recipe_path, folder = Path(recipe_path), Path(folder)
    r = json.loads(recipe_path.read_text(encoding="utf-8"))
    if r.get("kind") not in (None, "image"):
        raise SystemExit(f"batch: recipe kind {r.get('kind')!r} is not an image recipe")
    steps = r["steps"]
    if not steps:
        raise SystemExit("batch: the recipe has no steps")
    for st in steps:
        if st.get("mask"):
            raise SystemExit("batch: steps with a mask file are tied to one image; remove the mask or use run")
    sh = steps_hash(steps)
    out_dir = Path(out_dir) if out_dir else folder.parent / f"{folder.name}-{recipe_path.stem}"
    if out_dir.resolve() == folder.resolve():
        raise SystemExit("batch: the output folder must differ from the source folder")
    files = sorted(p for p in (folder.rglob(pattern) if recursive else folder.glob(pattern))
                   if p.is_file() and p.suffix.lower() in IMAGE_EXT
                   and out_dir.resolve() not in p.resolve().parents)
    man_path = out_dir / "batch-manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    plan, done, skipped, failed = [], [], [], []
    for src in files:
        rel = src.relative_to(folder).as_posix()
        h = sha256(src)
        prev = man.get(rel)
        if prev and prev["source_sha256"] == h and prev["steps"] == sh and Path(out_dir / prev["output"]).exists() \
                and sha256(out_dir / prev["output"]) == prev["output_sha256"]:
            skipped.append({"source": rel, "output": prev["output"], "why": "up to date"})
            continue
        target = out_dir / Path(rel).with_suffix(ext or src.suffix)
        plan.append({"source": rel, "output": free_path(target).relative_to(out_dir).as_posix() if apply is False
                     else None})
        if not apply:
            continue
        t0 = time.time()
        try:
            used = Used()
            img = apply_steps(load(src, used), steps, used, recipe_path.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            out = free_path(target)
            if out.resolve() == src.resolve():
                raise RuntimeError("refusing to write over the source")
            save(img, out, None, used)
            item = {"source": rel, "output": out.relative_to(out_dir).as_posix(), "rung": used.rung(),
                    "tool": used.tool(), "seconds": round(time.time() - t0, 3)}
            man[rel] = {"source_sha256": h, "steps": sh, "output": item["output"], "output_sha256": sha256(out)}
            done.append(item)
        except Exception as e:  # one bad file must not stop the rest
            failed.append({"source": rel, "error": f"{type(e).__name__}: {e}"})
    if apply and (done or failed):
        out_dir.mkdir(parents=True, exist_ok=True)
        man_path.write_text(json.dumps(man, indent=1), encoding="utf-8")
        with open(out_dir / "batch-log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "recipe": str(recipe_path),
                                "steps": sh, "written": len(done), "skipped": len(skipped),
                                "failed": failed, "phw": core.VERSION}) + "\n")
    res = {"command": "batch", "recipe": str(recipe_path), "folder": str(folder), "output_folder": str(out_dir),
           "mode": "apply" if apply else "dry run", "files": len(files), "steps": [s["op"] for s in steps],
           "skipped": skipped, "failed": failed}
    if apply:
        res["written"] = done
        res["rung"] = max([d["rung"] for d in done] or [1])
    else:
        res["would_write"] = plan
        res["hint"] = "dry run: nothing written; add --apply to run"
    return res


def cmd_batch(a):
    return batch(a.recipe_file, a.folder, a.out, a.apply, a.glob, a.recursive, a.ext)


# ---------------------------------------------------------------- sheet
def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def checker(w, h, n=8):
    yy, xx = np.mgrid[:h, :w]
    v = np.where(((yy // n) + (xx // n)) % 2, 204, 255).astype(np.uint8)
    return Image.fromarray(np.stack([v] * 3, 2))


def sheet(paths, labels=None, cols=None, cell=320, pad=12, label_h=None, bg=(32, 32, 32)):
    ims = []
    for p in paths:
        im = Image.open(p)
        im.load()
        ims.append(im)
    labels = labels or [Path(p).stem for p in paths]
    if len(labels) != len(ims):
        raise SystemExit(f"sheet: {len(ims)} images but {len(labels)} labels")
    n = len(ims)
    cols = cols or min(n, 4)
    rows = -(-n // cols)
    fs = max(12, cell // 16)
    label_h = label_h or fs + 10
    W = cols * cell + (cols + 1) * pad
    H = rows * (cell + label_h) + (rows + 1) * pad
    out = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(out)
    f = font(fs)
    for i, (im, lab) in enumerate(zip(ims, labels)):
        r, c = divmod(i, cols)
        x0, y0 = pad + c * (cell + pad), pad + r * (cell + label_h + pad)
        rgba = im.convert("RGBA")
        k = min(cell / rgba.width, cell / rgba.height)
        size = (max(1, round(rgba.width * k)), max(1, round(rgba.height * k)))
        small = rgba.resize(size, Image.NEAREST if k >= 2 else Image.LANCZOS)
        ox, oy = x0 + (cell - size[0]) // 2, y0 + (cell - size[1]) // 2
        base = checker(*size).convert("RGBA")
        out.paste(Image.alpha_composite(base, small).convert("RGB"), (ox, oy))
        text = f"{lab}  ({im.width}x{im.height})"
        tw = d.textlength(text, font=f)
        d.text((x0 + max(0, (cell - tw) / 2), y0 + cell + 4), text, fill=(235, 235, 235), font=f)
    return out


def cmd_sheet(a):
    labels = [s.strip() for s in a.labels.split(",")] if a.labels else None
    img = sheet(a.inputs, labels, a.cols, a.cell)
    out = free_path(Path(a.output) if a.output else Path(a.inputs[0]).with_name(Path(a.inputs[0]).stem + "-sheet.png"))
    if any(out.resolve() == Path(p).resolve() for p in a.inputs):
        raise RuntimeError("refusing to write over a source")
    img.save(out)
    return {"command": "sheet", "inputs": [str(p) for p in a.inputs], "output": str(out), "size": list(img.size),
            "labels": labels or [Path(p).stem for p in a.inputs], "rung": 1, "tool": ["Pillow"]}


# ---------------------------------------------------------------- diff
def components(mask):
    """Count 8-connected regions (union-find over row runs; rung 1)."""
    parent = []

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    prev = []
    for row in mask:
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        cur = []
        j = 0
        for s, e in zip(starts, ends):
            idx = len(parent)
            parent.append(idx)
            while j < len(prev) and prev[j][1] < s:   # prev run ends (exclusive) before s-1
                j += 1
            k = j
            while k < len(prev) and prev[k][0] <= e:  # overlaps [s-1, e] (8-connected)
                a, b = find(idx), find(prev[k][2])
                if a != b:
                    parent[a] = b
                k += 1
            cur.append((s, e, idx))
        prev = cur
    return len({find(i) for i in range(len(parent))})


def heat(v):
    """0..1 -> black, red, yellow, white."""
    r = np.clip(v * 3, 0, 1)
    g = np.clip(v * 3 - 1, 0, 1)
    b = np.clip(v * 3 - 2, 0, 1)
    return np.stack([r, g, b], -1)


def diff(pa, pb, threshold=2 / 255, gain=None):
    A = np.asarray(Image.open(pa).convert("RGBA"), np.float32) / 255
    B = np.asarray(Image.open(pb).convert("RGBA"), np.float32) / 255
    if A.shape != B.shape:
        raise SystemExit(f"diff: sizes differ ({A.shape[1]}x{A.shape[0]} vs {B.shape[1]}x{B.shape[0]}); "
                         "resize or crop one first")
    D = np.abs(A - B).max(axis=2)
    ch = D > threshold
    mse = float(((A - B) ** 2).mean())
    st = {"identical": bool(not D.any()), "max": round(float(D.max()), 4), "mean": round(float(D.mean()), 5),
          "psnr_db": None if mse == 0 else round(10 * np.log10(1 / mse), 2),
          "changed_share": round(float(ch.mean()), 5), "changed_pixels": int(ch.sum()), "threshold": round(threshold, 4)}
    if ch.any():
        ys, xs = np.nonzero(ch)
        st["bbox"] = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        st["regions"] = components(ch)
        per = {}
        for i, n in enumerate("RGBA"):
            per[n] = round(float(np.abs(A[..., i] - B[..., i]).mean()), 5)
        st["mean_per_channel"] = per
    else:
        st["bbox"], st["regions"] = None, 0
    g = gain or (1.0 / max(float(D.max()), 1e-6))
    gray = (A[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None] * 0.35
    hm = np.clip(np.where(ch[..., None], heat(np.clip(D * g, 0, 1)), gray), 0, 1)
    return st, Image.fromarray(np.rint(hm * 255).astype(np.uint8))


def cmd_diff(a):
    st, hm = diff(a.a, a.b, a.threshold / 255.0, a.gain)
    out = free_path(Path(a.output) if a.output else Path(a.a).with_name(f"{Path(a.a).stem}-diff.png"))
    if out.resolve() in (Path(a.a).resolve(), Path(a.b).resolve()):
        raise RuntimeError("refusing to write over a source")
    hm.save(out)
    return {"command": "diff", "a": str(a.a), "b": str(a.b), "heatmap": str(out), **st, "rung": 1,
            "tool": ["NumPy"], "heatmap_key": "dim grey = unchanged; black-red-yellow-white = larger change "
                                              "(scaled so the largest change is white unless --gain)"}


def add_commands(sub, edit):
    p = sub.add_parser("batch", help="a recipe over a folder: dry run unless --apply; never overwrites")
    p.add_argument("recipe_file")
    p.add_argument("folder")
    p.add_argument("--out", help="output folder (default: <folder>-<recipe name> beside the folder)")
    p.add_argument("--apply", action="store_true", help="write the outputs (default: dry run)")
    p.add_argument("--glob", default="*", help="file pattern (default *)")
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--ext", help="output extension, e.g. .png (default: as the source)")
    p.set_defaults(fn=cmd_batch)
    p = sub.add_parser("sheet", help="images side by side with labels (before/after, variations)")
    p.add_argument("inputs", nargs="+")
    p.add_argument("-o", "--output")
    p.add_argument("--labels", help="comma-separated labels (default: file names)")
    p.add_argument("--cols", type=int)
    p.add_argument("--cell", type=int, default=320, help="cell size in px")
    p.set_defaults(fn=cmd_sheet)
    p = sub.add_parser("diff", help="what changed between two images and where: heatmap + stats")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("-o", "--output", help="heatmap PNG")
    p.add_argument("--threshold", type=float, default=2.0, help="change counted above this (0-255 scale)")
    p.add_argument("--gain", type=float, help="heatmap gain (default: largest change = white)")
    p.set_defaults(fn=cmd_diff)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {"batch, sheet, diff": (1, "own (Pillow + NumPy)")})
