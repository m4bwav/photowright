"""Batch 17b (0.18.0): Layer Comps and Generator image assets.

comps:  Layer Comps: a JSON file of named comps, each overriding visibility, opacity and position of
        layers by name ({"comp": {"layer": {"visible": false, "opacity": 0.5, "x": 3, "y": 4}}});
        one flattened PNG per comp, the source document untouched.
assets: Generator image assets: every layer or group whose name ends in .png/.jpg/.webp (comma
        separated for several, an optional "200% " or "64x64 " prefix for the size) is rendered
        alone and written under that file name, like Photoshop's File > Generate > Image Assets.
Own NumPy and Pillow (the W3C compositor in compose.py).
"""
import json
import re
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import compose, core, layered


def walk(layers):
    for l in layers:
        yield l
        if l.group:
            yield from walk(l.children)


def to_png(rgba, fp, size=None):
    im = Image.fromarray(np.round(np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA")
    if size and size != im.size:
        im = im.resize(size, Image.LANCZOS)
    fp = core.free_path(fp)
    if fp.suffix.lower() in (".jpg", ".jpeg"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        bg.save(fp, quality=92)
    else:
        im.save(fp)
    return fp


def cmd_comps(a):
    t0 = time.time()
    used = core.Used()
    spec = json.loads(Path(a.comps).read_text(encoding="utf-8"))
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    res = []
    for name, over in spec.items():
        doc = layered.read_layered(a.input, used)   # fresh per comp: overrides never leak
        by = {l.name: l for l in walk(doc.layers)}
        missing = [k for k in over if k not in by]
        if missing:
            raise SystemExit(f"comps: comp {name!r} names layers not in the file: {missing}")
        for k, o in over.items():
            l = by[k]
            if "visible" in o:
                l.visible = bool(o["visible"])
            if "opacity" in o:
                l.opacity = float(o["opacity"])
            if "x" in o or "y" in o:
                dx, dy = int(o.get("x", l.x)) - l.x, int(o.get("y", l.y)) - l.y
                for m in walk([l]):
                    m.x, m.y, m.mask_x, m.mask_y = m.x + dx, m.y + dy, m.mask_x + dx, m.mask_y + dy
        rgba = compose.composite_doc(doc, a.space)
        fp = to_png(rgba, out / f"{layered._safe(name)}.png")
        res.append({"comp": name, "file": str(fp), "overrides": len(over)})
    used.add("comps", 1, "own per-comp overrides + W3C compositor")
    return {"command": "comps", "input": str(a.input), "outputs": res, "seconds": round(time.time() - t0, 3),
            "rung": used.rung(), "tool": used.tool(), "used": used.items}


ASSET = re.compile(r"^\s*(?:(\d+(?:\.\d+)?)%\s+|(\d+)x(\d+)\s+)?(\S.*\.(?:png|jpe?g|webp))\s*$", re.I)


def parse_asset_names(name):
    """'icon.png, 200% icon@2x.png, 32x32 tiny.png' -> [(file, scale or None, (w, h) or None)]."""
    outs = []
    for part in name.split(","):
        m = ASSET.match(part)
        if m:
            pct, w, h, fn = m.groups()
            outs.append((fn.strip(), float(pct) / 100 if pct else None, (int(w), int(h)) if w else None))
    return outs


def cmd_assets(a):
    t0 = time.time()
    used = core.Used()
    doc = layered.read_layered(a.input, used)
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    res = []
    for l in walk(doc.layers):
        specs = parse_asset_names(l.name)
        if not specs:
            continue
        was = l.visible
        l.visible = True
        rgba = compose.composite_doc(compose.Doc(doc.width, doc.height, [l]), a.space)
        l.visible = was
        ys, xs = np.nonzero(rgba[..., 3] > 0)
        if not len(xs):
            res.append({"layer": l.name, "skipped": "empty"})
            continue
        crop = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        h, w = crop.shape[:2]
        for fn, scale, size in specs:
            sz = size or (max(1, round(w * scale)), max(1, round(h * scale))) if (size or scale) else None
            fp = to_png(crop, out / Path(fn).name, sz)
            res.append({"layer": l.name, "file": str(fp), "size": list(sz or (w, h)),
                        "x": int(xs.min()), "y": int(ys.min())})
    if not res:
        raise SystemExit("assets: no layer is named like an image file (e.g. 'icon.png' or '200% icon@2x.png')")
    used.add("assets", 1, "own Generator-style asset export (W3C compositor, Lanczos resize)")
    return {"command": "assets", "input": str(a.input), "outputs": res, "seconds": round(time.time() - t0, 3),
            "rung": used.rung(), "tool": used.tool(), "used": used.items}


def add_commands(sub, edit):
    p = sub.add_parser("comps", help="Layer Comps: one flattened PNG per named set of layer overrides (rung 1)")
    p.add_argument("input", help="layered file: .psd, .ora or a layers .json")
    p.add_argument("comps", help='JSON {"comp": {"layer": {"visible": false, "opacity": 0.5, "x": 3, "y": 4}}}')
    p.add_argument("outdir")
    p.add_argument("--space", choices=("gamma", "linear"), default="gamma")
    p.set_defaults(fn=cmd_comps)
    p = sub.add_parser("assets", help="Generator image assets: export layers named like files (rung 1)")
    p.add_argument("input", help="layered file: .psd, .ora or a layers .json")
    p.add_argument("outdir")
    p.add_argument("--space", choices=("gamma", "linear"), default="gamma")
    p.set_defaults(fn=cmd_assets)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {"comps, assets": (1, "own NumPy + Pillow")})
