"""Batch, sheet, diff (rung 1: Pillow + NumPy).

batch  a recipe's steps over a folder. Dry run by default (lists what would be written); --apply runs.
       Sources are only read. Outputs go to a separate folder and are never written over. A manifest
       (batch-manifest.json in the output folder) keys each source by path, its sha256 and the recipe's
       steps hash, so a second run with nothing changed writes nothing. A file that fails is reported and
       the rest finish.
sheet  images side by side in a grid with labels (before/after, variations), on a checkerboard for alpha.
diff   what changed between two images and where: heatmap PNG, stats (max, mean, PSNR, changed share,
       bounding box, number of changed regions).
drift  a chain of edit rounds scored against round 0 (or the previous round): median colour difference
       (CIE76 and CIEDE2000 in Lab), mean L/a/b shift, chroma and sharpness ratios, PSNR, SSIM, optionally
       outside the edit masks only, with a restart flag past a limit. After arXiv:2611.06741 (TailSteer):
       multi-turn edits drift through late-step colour and detail error that compounds with each re-encode.
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
    # cells are `cell` wide and as tall as the tallest input's aspect needs (wide frames get no empty band)
    ch = max(1, min(cell * 4, round(cell * max(im.height / im.width for im in ims))))
    W = cols * cell + (cols + 1) * pad
    H = rows * (ch + label_h) + (rows + 1) * pad
    out = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(out)
    f = font(fs)
    for i, (im, lab) in enumerate(zip(ims, labels)):
        r, c = divmod(i, cols)
        x0, y0 = pad + c * (cell + pad), pad + r * (ch + label_h + pad)
        rgba = im.convert("RGBA")
        k = min(cell / rgba.width, ch / rgba.height)
        size = (max(1, round(rgba.width * k)), max(1, round(rgba.height * k)))
        small = rgba.resize(size, Image.NEAREST if k >= 2 else Image.LANCZOS)
        ox, oy = x0 + (cell - size[0]) // 2, y0 + (ch - size[1]) // 2
        base = checker(*size).convert("RGBA")
        out.paste(Image.alpha_composite(base, small).convert("RGB"), (ox, oy))
        text = f"{lab}  ({im.width}x{im.height})"
        tw = d.textlength(text, font=f)
        d.text((x0 + max(0, (cell - tw) / 2), y0 + ch + 4), text, fill=(235, 235, 235), font=f)
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


# ---------------------------------------------------------------- drift over an edit chain
def de2000(lab1, lab2):
    """CIEDE2000 colour difference, elementwise (Sharma, Wu and Dalal 2005 formulation)."""
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    cbar7 = ((np.hypot(a1, b1) + np.hypot(a2, b2)) / 2) ** 7
    g = 0.5 * (1 - np.sqrt(cbar7 / (cbar7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1, c2 = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1 = np.degrees(np.arctan2(b1, a1p)) % 360
    h2 = np.degrees(np.arctan2(b2, a2p)) % 360
    cc = c1 * c2
    zero = cc == 0
    dh = h2 - h1
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(zero, 0.0, dh)
    dH = 2 * np.sqrt(cc) * np.sin(np.radians(dh / 2))
    lbar, cbar = (L1 + L2) / 2, (c1 + c2) / 2
    hs = h1 + h2
    hbar = np.where(np.abs(h1 - h2) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2))
    hbar = np.where(zero, hs, hbar)
    t = (1 - 0.17 * np.cos(np.radians(hbar - 30)) + 0.24 * np.cos(np.radians(2 * hbar))
         + 0.32 * np.cos(np.radians(3 * hbar + 6)) - 0.20 * np.cos(np.radians(4 * hbar - 63)))
    dtheta = 30 * np.exp(-(((hbar - 275) / 25) ** 2))
    cb7 = cbar ** 7
    rc = 2 * np.sqrt(cb7 / (cb7 + 25.0 ** 7))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / np.sqrt(20 + (lbar - 50) ** 2)
    sc = 1 + 0.045 * cbar
    sh = 1 + 0.015 * cbar * t
    rt = -np.sin(np.radians(2 * dtheta)) * rc
    tl, tc, th = (L2 - L1) / sl, (c2 - c1) / sc, dH / sh
    return np.sqrt(np.maximum(tl ** 2 + tc ** 2 + th ** 2 + rt * tc * th, 0))


def _drift_load(path, shape=None, size=0):
    """RGB float64 0..1 with EXIF orientation; resized to `shape` (H, W), or to `size` px on the long edge."""
    from PIL import ImageOps
    with Image.open(path) as im:
        orig = im.size
        im = ImageOps.exif_transpose(im).convert("RGB")
        if shape is not None:
            if im.size != (shape[1], shape[0]):
                im = im.resize((shape[1], shape[0]), Image.LANCZOS)
        elif size and max(im.size) > size:
            s = size / max(im.size)
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
        return np.asarray(im, np.float64) / 255.0, orig


def _lap(grey):
    return (grey[:-2, 1:-1] + grey[2:, 1:-1] + grey[1:-1, :-2] + grey[1:-1, 2:]) - 4 * grey[1:-1, 1:-1]


def _block_ssim(ga, gb, keep, n=8):
    """Mean SSIM over n x n blocks lying wholly in `keep` (box window, grey 0..1)."""
    h, w = (ga.shape[0] // n) * n, (ga.shape[1] // n) * n
    if h == 0 or w == 0:
        return None

    def blocks(x):
        return x[:h, :w].reshape(h // n, n, w // n, n).swapaxes(1, 2).reshape(-1, n * n)
    A, B, K = blocks(ga), blocks(gb), blocks(keep).all(1)
    if not K.any():
        return None
    A, B = A[K], B[K]
    ma, mb = A.mean(1), B.mean(1)
    va, vb = A.var(1), B.var(1)
    cov = ((A - ma[:, None]) * (B - mb[:, None])).mean(1)
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    return float((((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma ** 2 + mb ** 2 + c1) * (va + vb + c2))).mean())


def drift_pair(ref, img, keep):
    """Drift metrics of `img` against `ref` (RGB 0..1) over the pixels where `keep` is True."""
    from .masks import rgb_to_lab
    la, lb = rgb_to_lab(ref), rgb_to_lab(img)
    d76 = np.linalg.norm(lb - la, axis=-1)[keep]
    d00 = de2000(la[keep], lb[keep])
    shift = (lb - la)[keep].mean(0)
    ca = np.hypot(la[..., 1], la[..., 2])[keep].mean()
    cb = np.hypot(lb[..., 1], lb[..., 2])[keep].mean()
    ga, gb = la[..., 0] / 100, lb[..., 0] / 100
    inner = keep[1:-1, 1:-1] & keep[:-2, 1:-1] & keep[2:, 1:-1] & keep[1:-1, :-2] & keep[1:-1, 2:]
    sa = float(_lap(ga)[inner].var()) if inner.any() else 0.0
    sb = float(_lap(gb)[inner].var()) if inner.any() else 0.0
    mse = float(((img - ref) ** 2)[keep].mean())
    ss = _block_ssim(ga, gb, keep)
    return {"dE76_median": round(float(np.median(d76)), 2), "dE00_median": round(float(np.median(d00)), 2),
            "dE76_p90": round(float(np.percentile(d76, 90)), 2), "over10_share": round(float((d76 > 10).mean()), 4),
            "dL": round(float(shift[0]), 2), "da": round(float(shift[1]), 2), "db": round(float(shift[2]), 2),
            "chroma_ratio": round(float(cb / ca), 3) if ca > 1e-9 else None,
            "sharpness_ratio": round(sb / sa, 3) if sa > 1e-12 else None,
            "psnr_db": None if mse == 0 else round(float(10 * np.log10(1 / mse)), 2),
            "ssim": None if ss is None else round(ss, 4)}


def drift(paths, prev=False, masks=(), global_rounds=(), limit_de=4.0, size=1024):
    """Score rounds 1..N of an edit chain against round 0 (or the previous round, or the last global round)."""
    if len(paths) < 2:
        raise SystemExit("drift: give round 0 and at least one later round")
    notes = []
    r0, size0 = _drift_load(paths[0], size=size)
    shape = r0.shape[:2]
    imgs = [r0]
    for p in paths[1:]:
        im, sz = _drift_load(p, shape=shape)
        if sz != size0:
            notes.append(f"{Path(p).name} is {sz[0]}x{sz[1]}, round 0 is {size0[0]}x{size0[1]}: resized to compare")
        imgs.append(im)
    edit = np.zeros(shape, bool)
    for m in masks:
        with Image.open(m) as mi:
            mm = mi.convert("L").resize((shape[1], shape[0]), Image.NEAREST)
        edit |= np.asarray(mm) >= 128
    keep = ~edit
    if keep.mean() < 0.01:
        raise SystemExit("drift: the masks cover the whole image; nothing is left to score")
    glob = sorted({int(g) for g in global_rounds})
    bad = [g for g in glob if not 1 <= g < len(paths)]
    if bad:
        raise SystemExit(f"drift: --global rounds {bad} are outside 1..{len(paths) - 1}")
    rows = []
    for k in range(1, len(imgs)):
        ref = k - 1 if prev else max([g for g in glob if g < k], default=0)
        row = {"round": k, "file": str(paths[k]), "against": ref, "global": k in glob}
        row.update(drift_pair(imgs[ref], imgs[k], keep))
        row["over_limit"] = (not row["global"]) and row["dE76_median"] > limit_de
        rows.append(row)
    over = [r["round"] for r in rows if r["over_limit"]]
    advice = ("within the limit: keep editing from the latest round" if not over else
              f"round {over[0]} passed median dE {limit_de:g} outside the edits: restart from the original "
              "(round 0) or composite the untouched pixels back from round 0 through the edit mask")
    return {"rounds": rows, "limit_de": limit_de, "first_over_limit": over[0] if over else None,
            "over_limit": over, "scored_share": round(float(keep.mean()), 4),
            "compared_at": f"{shape[1]}x{shape[0]}", "advice": advice, "notes": notes}


def _fmt(v, spec):
    return "-".rjust(len(format(0.0, spec))) if v is None else format(v, spec)


def drift_table(r):
    lines = ["round vs  dE76  dE00  >10%     dL     da     db chroma sharp  PSNR   SSIM"]
    for x in r["rounds"]:
        lines.append(f"{x['round']:>5} {x['against']:>2} {x['dE76_median']:5.2f} {x['dE00_median']:5.2f} "
                     f"{x['over10_share'] * 100:5.1f} {x['dL']:+6.2f} {x['da']:+6.2f} {x['db']:+6.2f} "
                     f"{_fmt(x['chroma_ratio'], '6.3f')} {_fmt(x['sharpness_ratio'], '5.3f')} "
                     f"{_fmt(x['psnr_db'], '5.2f')} {_fmt(x['ssim'], '6.4f')}"
                     + (" global" if x["global"] else "") + (" OVER" if x["over_limit"] else ""))
    return "\n".join(lines)


def cmd_drift(a):
    glob = [g for s in (a.global_rounds or []) for g in str(s).split(",") if g.strip()]
    r = drift(a.rounds, a.prev, a.mask or [], glob, a.limit_de, a.size)
    if getattr(a, "json_sub", False):
        a.json = True
    if not a.json:
        out = {"command": "drift", "table": "\n" + drift_table(r), "first_over_limit": r["first_over_limit"],
               "advice": r["advice"], "scored_share": r["scored_share"], "compared_at": r["compared_at"]}
        if r["notes"]:
            out["notes"] = "; ".join(r["notes"])
        return out
    return {"command": "drift", **r, "rung": 1, "tool": ["NumPy"], "source": "arXiv:2611.06741 (TailSteer)"}


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
    p = sub.add_parser("drift", help="score an edit chain against round 0: colour, sharpness, PSNR, SSIM, restart flag")
    p.add_argument("rounds", nargs="+", help="ROUND0 ROUND1 ... in order")
    p.add_argument("--prev", action="store_true", help="score each round against the previous one instead")
    p.add_argument("--mask", action="append", help="edit mask (white = intended change), scored outside only; repeatable")
    p.add_argument("--global", dest="global_rounds", action="append",
                   help="round(s) with an intended global change (relight, outpaint), e.g. 3 or 3,5: "
                        "later rounds are scored against the latest of them")
    p.add_argument("--limit-de", type=float, default=4.0, help="median CIE76 dE outside the edits that trips the "
                                                                "restart flag (default 4)")
    p.add_argument("--size", type=int, default=1024, help="compare at this long edge in px (0 = full size)")
    p.add_argument("--json", dest="json_sub", action="store_true", help="print JSON")
    p.set_defaults(fn=cmd_drift)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {"batch, sheet, diff, drift": (1, "own (Pillow + NumPy)")})
