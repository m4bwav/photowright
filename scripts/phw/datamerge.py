"""Batch 13 (0.14.0): Variables (data-driven graphics), Photoshop's Image > Variables + Data Sets.

phw variables TEMPLATE.json DATA.csv OUTDIR [--name COLUMN] [--ext .png]
TEMPLATE.json is a `phw layers` recipe. Every CSV column named like a layer replaces it per row:
a text layer's "text", an image layer's "file" (relative to the CSV's folder), a fill or shape
layer's "color" (#rrggbb). --name picks the column the output is named from (default: the first).
A manifest (variables-manifest.json in OUTDIR) keys each output by the template, the row and the
sha256 of every image it used: a second run skips unchanged rows and never overwrites; a changed
row is written to a free name. A bad row (missing image, empty name, compose error) is reported
and the rest finish.
"""
import csv
import hashlib
import json
import re
import time
from pathlib import Path

from . import compose, core


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", s).strip(" .")


def hexcol(s):
    h = s.strip().lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def apply_row(specs, row, base, used_files):
    out = []
    for L in specs:
        L = dict(L)
        if L.get("type") == "group":
            L["layers"] = apply_row(L.get("layers", []), row, base, used_files)
        name = L.get("name")
        if name in row and row[name] is not None:
            v = row[name]
            t = L.get("type", "image")
            if t == "text":
                L["text"] = v
            elif t == "image":
                f = compose.resolve(base, v)
                if not f.exists():
                    raise FileNotFoundError(f"layer {name!r}: image {v!r} not found")
                L["file"] = str(f.resolve())
            elif t in ("fill", "shape"):
                L["color"] = hexcol(v)
        if L.get("type", "image") == "image" and L.get("file"):
            used_files.append(str(L["file"]))
        out.append(L)
    return out


def variables(template, data, out_dir, name_col=None, ext=".png"):
    t0 = time.time()
    template, data, out_dir = Path(template), Path(data), Path(out_dir)
    r = json.loads(template.read_text(encoding="utf-8"))
    tsha = core.sha256(template)
    with open(data, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("variables: the CSV has no data rows")
    name_col = name_col or next(iter(rows[0]))
    out_dir.mkdir(parents=True, exist_ok=True)
    man_p = out_dir / "variables-manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8")) if man_p.exists() else {}
    sources = {template.resolve(), data.resolve()}
    written, skipped, errors = [], [], []
    used = core.Used()
    for i, row in enumerate(rows, start=2):  # line 1 is the header
        try:
            nm = safe_name(row.get(name_col) or "")
            if not nm:
                raise ValueError(f"empty {name_col!r}")
            files = []
            rr = dict(r)
            rr["layers"] = apply_row(r.get("layers", []), row, data.parent, files)
            key = hashlib.sha256(json.dumps({"t": tsha, "row": row, "f": [[f, core.sha256(compose.resolve(template.parent, f))]
                                                                         for f in files]}, sort_keys=True).encode()).hexdigest()
            prev = man.get(nm)
            if prev and prev.get("key") == key and Path(prev["output"]).exists() \
                    and core.sha256(prev["output"]) == prev.get("output_sha256"):
                skipped.append(prev["output"])
                continue
            out = core.free_path(out_dir / f"{nm}{ext}")
            if out.resolve() in sources or str(out.resolve()) in {str(Path(f).resolve()) for f in files}:
                raise RuntimeError("refusing to write over a source")
            doc = compose.doc_from_recipe(rr, template.parent, used)
            compose.write_doc(doc, out, used, r.get("space", "gamma"))
            man[nm] = {"key": key, "output": str(out), "output_sha256": core.sha256(out), "line": i}
            written.append(str(out))
        except Exception as e:  # noqa: BLE001  a bad row must not stop the rest
            errors.append({"line": i, "row": row, "error": f"{type(e).__name__}: {e}"})
    man_p.write_bytes(json.dumps(man, indent=1).encode())
    used.add("variables", 1, "own CSV data sets over a layers recipe")
    return {"command": "variables", "template": str(template), "data": str(data), "output_folder": str(out_dir),
            "rows": len(rows), "written": written, "skipped": skipped, "errors": errors,
            "seconds": round(time.time() - t0, 3), "rung": used.rung(), "tool": used.tool(), "used": used.items}


def cmd_variables(a):
    return variables(a.template, a.data, a.out_dir, a.name, a.ext)


def add_commands(sub, edit):
    p = sub.add_parser("variables", help="data-driven graphics: a layers recipe once per CSV row "
                                         "(text, image and colour layers replaced by column)")
    p.add_argument("template", help="phw layers recipe .json")
    p.add_argument("data", help="CSV; columns named like layers replace them")
    p.add_argument("out_dir")
    p.add_argument("--name", help="column the output is named from (default: the first)")
    p.add_argument("--ext", default=".png", help="output extension (.png, .jpg, .psd, .ora ...)")
    p.set_defaults(fn=cmd_variables)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {"variables (CSV data sets over a layers recipe)": (1, "own")})
