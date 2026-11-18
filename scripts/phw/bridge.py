"""bridge: hand a file (layered or flat) to another editor so a person can finish by hand.

Targets and rungs (Mark's ruling 2026-11-17: free editors first, Photoshop is documentation only):
- gimp (rung 2, GPL, called as an external program): a Python-Fu batch script that opens the file,
  flattens it and exports a PNG; with --run it is run in gimp-console and the result is compared
  with photowright's own flatten, so the bridge is proven on every use.
- krita (rung 2, GPL): `krita FILE --export --export-filename OUT`; run with --run when Krita is found.
- photopea (rung 4, closed web app): a script to paste into File > Script. Nothing is uploaded:
  sending an image to an outside service waits on the owner.
- photoshop (rung 4, closed): an ExtendScript .jsx. Never run by photowright.

The script and the exact command are always written to an emit folder, so the hand-off works on a
machine without the editor too. A target above --rung-max (PHW_RUNG_MAX) is refused.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import core
from .core import Used, free_path

__all__ = ["krita_exe", "bridge_scripts", "TARGETS"]

TARGETS = {"gimp": 2, "krita": 2, "photopea": 4, "photoshop": 4}


def krita_exe():
    w = shutil.which("krita")
    if w:
        return w
    for r in (Path(os.environ.get("ProgramFiles", "C:/Program Files")), Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"):
        for c in (r / "Krita (x64)" / "bin" / "krita.exe", r / "Krita" / "bin" / "krita.exe"):
            if c.exists():
                return str(c)
    return None


def _js(s):
    return json.dumps(str(s))


def bridge_scripts(src, out, space="gamma"):
    """Return {target: (script_name, script_text, command_or_steps)} for one source and PNG output.

    space "gamma" (photowright's default, and Photoshop's) makes GIMP blend and composite every layer
    in perceptual RGB: GIMP 3 opens ORA layers in linear light and would otherwise differ (measured
    2026-11-17: multiply at 80% off by mean 8.9, max 60 of 255; its PSD import is already perceptual).
    """
    src, out = Path(src).resolve(), Path(out).resolve()
    # flatten() fills transparency with the background colour; keep alpha: merge visible instead.
    gimp_py = (
        "from gi.repository import Gimp, Gio\n"
        f"img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path({str(src)!r}))\n"
        "def walk(ls):\n"
        "    for l in ls:\n"
        f"        cs = Gimp.LayerColorSpace.{'RGB_PERCEPTUAL' if space == 'gamma' else 'RGB_LINEAR'}\n"
        "        l.set_blend_space(cs)\n"
        "        l.set_composite_space(cs)\n"
        "        if l.is_group():\n"
        "            walk(l.get_children())\n"
        "walk(img.get_layers())\n"
        "if len(img.get_layers()) > 1:\n"
        "    img.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)\n"
        f"Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path({str(out)!r}), None)\n"
        "img.delete()\n")
    photopea_js = (
        "// photowright bridge: open the file in Photopea first (File > Open), then File > Script, paste, Run.\n"
        "var doc = app.activeDocument;\n"
        "doc.mergeVisibleLayers();\n"
        "doc.saveToOE(\"png\");  // Photopea offers the PNG as a download\n")
    jsx = (
        "// photowright bridge for Photoshop (documentation only: photowright never runs it).\n"
        f"var doc = app.open(new File({_js(src.as_posix())}));\n"
        "doc.mergeVisibleLayers();\n"
        "var o = new PNGSaveOptions();\n"
        f"doc.saveAs(new File({_js(out.as_posix())}), o, true, Extension.LOWERCASE);\n"
        "doc.close(SaveOptions.DONOTSAVECHANGES);\n")
    return {
        "gimp": ("gimp_bridge.py", gimp_py, None),
        "krita": (None, None, ["krita", str(src), "--export", "--export-filename", str(out)]),
        "photopea": ("photopea_bridge.js", photopea_js,
                     ["open https://www.photopea.com", f"File > Open: {src}", "File > Script: paste photopea_bridge.js, Run",
                      "nothing is uploaded by photowright"]),
        "photoshop": ("photoshop_bridge.jsx", jsx, ["File > Scripts > Browse: photoshop_bridge.jsx"]),
    }


def _own_flat(src, space="gamma"):
    from .layered import read_layered
    from .compose import composite_doc
    return composite_doc(read_layered(src, Used()), space)


def _compare(src, png, space="gamma"):
    """Mean and max absolute difference (0-255) between the editor's PNG and photowright's flatten."""
    own = _own_flat(src, space)
    got = np.asarray(Image.open(png).convert("RGBA"), np.float32) / 255.0
    if got.shape != own.shape:
        return {"same_size": False, "editor": list(got.shape), "photowright": list(own.shape)}
    a = own[..., 3:4]
    # compare premultiplied colour so fully transparent pixels with any colour count as equal
    d = np.abs(got[..., :3] * got[..., 3:4] - own[..., :3] * a) * 255
    da = np.abs(got[..., 3] - own[..., 3]) * 255
    return {"same_size": True, "colour_mean": round(float(d.mean()), 3), "colour_max": round(float(d.max()), 1),
            "alpha_max": round(float(da.max()), 1), "pass": bool(d.mean() < 1.0 and da.max() <= 2)}


def cmd_bridge(a):
    t0 = time.time()
    to = a.to
    rung = TARGETS[to]
    src = Path(a.input)
    if not src.exists():
        raise FileNotFoundError(src)
    if core.rung_max() < rung:
        return {"command": "bridge", "to": to, "status": "refused",
                "reason": f"{to} is rung {rung}; --rung-max/PHW_RUNG_MAX is {core.rung_max()}", "rung": 0, "tool": []}
    emit = Path(a.emit) if a.emit else src.parent / f"{src.stem}-bridge-{to}"
    emit.mkdir(parents=True, exist_ok=True)
    out = free_path(Path(a.output) if a.output else emit / f"{src.stem}-{to}.png")
    if out.resolve() == src.resolve():
        raise RuntimeError("refusing to write over the source")
    space = a.space
    if space is None:
        space = json.loads(src.read_text(encoding="utf-8")).get("space", "gamma") if src.suffix.lower() == ".json" else "gamma"
    name, text, steps = bridge_scripts(src, out, space)[to]
    r = {"command": "bridge", "to": to, "input": str(src), "emit": str(emit), "output": str(out), "space": space, "rung": rung}
    if name:
        (emit / name).write_text(text, encoding="utf-8")
        r["script"] = str(emit / name)
    exe = core.gimp_console() if to == "gimp" else krita_exe() if to == "krita" else None
    if to == "gimp":
        cmd = [exe or "gimp-console-3", "-i", "-d", "-f", "--no-shm", "--batch-interpreter", "python-fu-eval",
               "-b", f"exec(open({str((emit / name).resolve())!r}, encoding='utf-8').read())", "--quit"]
    elif to == "krita":
        cmd = [exe or "krita"] + steps[1:]
    else:
        cmd = None
    if cmd:
        (emit / "command.txt").write_text(subprocess.list2cmdline(cmd) + "\n", encoding="utf-8")
        r["command_line"] = subprocess.list2cmdline(cmd)
    else:
        (emit / "steps.txt").write_text("\n".join(steps) + "\n", encoding="utf-8")
        r["steps"] = steps
    r["tool"] = [{"gimp": "GIMP 3 batch (Python-Fu)", "krita": "Krita CLI export", "photopea": "Photopea script (manual)",
                  "photoshop": "ExtendScript .jsx (documentation only)"}[to]]
    if to in ("photopea", "photoshop"):
        r["status"] = "emitted"
        r["note"] = "closed editor: photowright writes the script and never runs it or uploads the file"
    elif not exe:
        r["status"] = "absent"
        r["note"] = f"{to} not found; the script and command are written, run them where {to} is installed"
    elif not a.run:
        r["status"] = "emitted"
        r["note"] = "add --run to run it here and compare with photowright's own flatten"
    else:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout, errors="replace")
        if not out.exists():
            r["status"] = "failed"
            r["error"] = (p.stderr or p.stdout or "")[-600:]
        else:
            r["status"] = "ran"
            r["compare"] = _compare(src, out, space)
    r["seconds"] = round(time.time() - t0, 2)
    return r


def add_commands(sub, edit):
    p = sub.add_parser("bridge", help="hand a file to GIMP or Krita (run and compare) or Photopea/Photoshop (script only)")
    p.add_argument("input", help="image, .psd, .ora or layers recipe")
    p.add_argument("--to", required=True, choices=sorted(TARGETS))
    p.add_argument("-o", "--output", help="the PNG the editor writes (never overwritten)")
    p.add_argument("--emit", help="folder for the script and command (default: <input>-bridge-<to> next to it)")
    p.add_argument("--run", action="store_true", help="run it here when the editor is installed (gimp, krita)")
    p.add_argument("--space", choices=("gamma", "linear"), help="blend space GIMP must use (default: the recipe's, else gamma)")
    p.add_argument("--timeout", type=int, default=300)
    p.set_defaults(fn=cmd_bridge)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "bridge gimp": (2, core.gimp_console()) if core.gimp_console() else (0, "GIMP 3 not found: script emitted only"),
    "bridge krita": (2, krita_exe()) if krita_exe() else (0, "Krita not found: command emitted only"),
    "bridge photopea, photoshop": (4, "script emitted only, never run"),
})
