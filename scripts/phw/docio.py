"""Batch 20 (0.21.0): the last open rung 2 rows of the coverage table: PDF/EPS open and video frames.

External programs only (rung 2), called by path and never bundled (all copyleft):
  PDF         pdftoppm (Poppler, GPL-2/3) or mutool (MuPDF, AGPL-3), first found
  EPS/PS/AI   Ghostscript (gs / gswin64c, AGPL-3)
  video       ffmpeg (LGPL/GPL builds)
A page or frame is picked with an ImageMagick-style suffix: `doc.pdf[2]` (1-based page),
`clip.mp4[48]` (0-based frame). Without one, page 1 / frame 0. `PHW_DOC_DPI` sets the PDF/EPS
render resolution (default 150). `frames VIDEO OUTDIR` writes numbered PNG frames (Photoshop's
video layers, as a folder the batch, stack and layers commands take).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import core

PDF_EXT = {".pdf"}
PS_EXT = {".eps", ".ps", ".epsf", ".ai"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv"}


def split_index(path):
    """'doc.pdf[2]' -> (Path('doc.pdf'), 2); a path without a suffix -> (path, None)."""
    s = str(path)
    if s.endswith("]") and "[" in s and not Path(s).exists():
        head, num = s[:s.rindex("[")], s[s.rindex("[") + 1:-1]
        if num.isdigit():
            return Path(head), int(num)
    return Path(s), None


def kind_of(path):
    p, _ = split_index(path)
    s = p.suffix.lower()
    return "pdf" if s in PDF_EXT else "ps" if s in PS_EXT else "video" if s in VIDEO_EXT else None


def find_tool(kind):
    names = {"pdf": ("pdftoppm", "mutool"), "ps": ("gswin64c", "gswin32c", "gs"), "video": ("ffmpeg",)}[kind]
    if core.rung_max() < 2:
        raise SystemExit(f"{kind} input needs an external program (rung 2): PHW_RUNG_MAX is below 2")
    for n in names:
        w = shutil.which(n)
        if w:
            return n, w
    hint = {"pdf": "install Poppler (pdftoppm) or MuPDF (mutool)", "ps": "install Ghostscript",
            "video": "install ffmpeg"}[kind]
    raise SystemExit(f"{kind} input needs one of {', '.join(names)} on PATH (rung 2): {hint}")


def dpi():
    try:
        return max(10, min(1200, int(os.environ.get("PHW_DOC_DPI", "150"))))
    except ValueError:
        return 150


def render_cmd(kind, tool, exe, src, idx, out_png):
    """The command line that renders one page or frame of src to out_png."""
    if kind == "pdf":
        page = idx or 1
        if tool == "pdftoppm":
            return [exe, "-f", str(page), "-l", str(page), "-r", str(dpi()), "-png", "-singlefile",
                    "-cropbox", str(src), str(out_png)[:-4]]
        return [exe, "draw", "-q", "-r", str(dpi()), "-o", str(out_png), str(src), str(page)]
    if kind == "ps":
        return [exe, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop", "-sDEVICE=pngalpha",
                f"-r{dpi()}", f"-dFirstPage={idx or 1}", f"-dLastPage={idx or 1}",
                f"-sOutputFile={out_png}", str(src)]
    return [exe, "-v", "error", "-y", "-i", str(src), "-vf", f"select='eq(n,{idx or 0})'",
            "-frames:v", "1", "-fps_mode", "passthrough", str(out_png)]


def load_hook(path, used=None):
    k = kind_of(path)
    if not k:
        return None
    src, idx = split_index(path)
    if not src.exists():
        raise SystemExit(f"no such file: {src}")
    tool, exe = find_tool(k)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "page.png"
        r = subprocess.run(render_cmd(k, tool, exe, src, idx, out), capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            what = "frame" if k == "video" else "page"
            raise SystemExit(f"{tool} could not render {what} {'' if idx is None else idx} of {src}: "
                             f"{(r.stderr or '').strip()[:300]}")
        img = core.load(out, used)
        img.px = img.px.copy()
    if used:
        used.add("load", 2, tool)
    what = f"frame {idx or 0}" if k == "video" else f"page {idx or 1} at {dpi()} dpi"
    img.notes.append(f"{src.name}: {what} rendered by {tool} (rung 2, external program)")
    return img


def cmd_frames(a):
    src = Path(a.input)
    if not src.exists():
        raise SystemExit(f"no such file: {src}")
    if a.every < 1:
        raise SystemExit("--every must be 1 or more")
    tool, exe = find_tool("video")
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    vf = [f"select='not(mod(n,{a.every}))'"] + ([f"scale={a.width}:-2"] if a.width else [])
    cmd = [exe, "-v", "error", "-y", "-i", str(src), "-vf", ",".join(vf), "-fps_mode", "passthrough"]
    if a.max:
        cmd += ["-frames:v", str(a.max)]
    cmd.append(str(out / "frame_%05d.png"))
    r = subprocess.run(cmd, capture_output=True, text=True)
    files = sorted(out.glob("frame_*.png"))
    if r.returncode != 0 or not files:
        raise SystemExit(f"ffmpeg wrote no frames: {(r.stderr or '').strip()[:300]}")
    return {"command": "frames", "input": str(src), "outdir": str(out), "frames": len(files),
            "every": a.every, "rung": 2, "tool": tool}


def add_commands(sub, edit=None):
    p = sub.add_parser("frames", help="video to numbered PNG frames (video layers as a folder), via ffmpeg")
    p.add_argument("input")
    p.add_argument("outdir")
    p.add_argument("--every", type=int, default=1, help="keep every Nth frame")
    p.add_argument("--max", type=int, default=0, help="stop after this many frames (0 = all)")
    p.add_argument("--width", type=int, default=0, help="scale to this width, keeping aspect")
    p.set_defaults(fn=cmd_frames)


core.LOAD_HOOKS.append(load_hook)
core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "PDF open": (2, "pdftoppm") if shutil.which("pdftoppm") else (2, "mutool") if shutil.which("mutool")
    else (0, "missing: Poppler pdftoppm or MuPDF mutool"),
    "EPS/PS open": (2, "Ghostscript") if any(shutil.which(n) for n in ("gswin64c", "gs"))
    else (0, "missing: Ghostscript"),
    "video frames": (2, "ffmpeg") if shutil.which("ffmpeg") else (0, "missing: ffmpeg"),
})
