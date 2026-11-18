"""Group the unit suite's verbose output by the eight feature groups of the goal and print a table.

Usage: PHW_RUNG_MAX=3 python -m unittest discover -s tests -v 2> out.txt
       python evals/ladder_report.py out.txt
A test counts in the first group whose keyword appears in its name (test id, lower case).
The finish line needs every group passing with rung 4 off (PHW_RUNG_MAX=3).
"""
import re
import sys
from collections import defaultdict

GROUPS = [
    ("vectorize", ("trace", "vcheck", "svg", "dxf", "simplify", "vector", "eps", "vtracer", "potrace", "centerline", "centreline")),
    ("files", ("psd", "ora", "tiff", "layered", "inspect", "convert", "heic", "heif", "jxl", "raw", "c2pa", "png16",
               "exif", "icc", "profile", "metadata", "export_layers", "assets", "indexed", "open", "save")),
    ("batch", ("batch", "replay", "recipe", "sheet", "diff", "variables", "run_upto", "bridge")),
    ("select", ("select", "mask", "cutout", "lasso", "focusarea", "matte", "grabcut", "sam", "florence")),
    ("retouch", ("heal", "clone", "fill", "remove", "restore", "caextend", "camove", "erase", "bucket", "lama",
                 "inpaint", "redeye", "dust", "patch", "spot")),
    ("transform", ("warp", "perspective", "upscale", "stitch", "stack", "hdr", "align", "liquify", "distort", "widefix",
                   "lens", "vpclone", "seam", "shake", "skew", "canvas", "crop", "rotate", "resize")),
    ("compose", ("layer", "blend", "compos", "comps", "gradient", "pattern", "text", "shape", "style", "satin", "clip")),
    ("adjust", ("adjust", "level", "curve", "exposure", "tone", "grade", "color", "colour", "detail", "camraw", "filter",
                "sharpen", "denoise", "blur", "hue", "sat", "lut", "balance", "vibrance", "noise", "emboss", "stylize",
                "fx", "pixelate", "kernel", "gallery", "fibers", "ntsc", "deinterlace", "dehaze", "clarity", "brush", "paint")),
]
LINE = re.compile(r"^(test\w*) \(([\w.]+)\)(?:\n?.*?)\.\.\. (ok|FAIL|ERROR|skipped.*|expected failure)$", re.M)


def group(name):
    n = name.lower()
    for g, keys in GROUPS:
        if any(k in n for k in keys):
            return g
    return "other"


def main(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    tally = defaultdict(lambda: defaultdict(int))
    for test, where, res in LINE.findall(text):
        r = "skip" if res.startswith("skipped") else res.lower()
        g = group(test)  # class names (Batch18...) would all read as "batch"
        tally[g if g != "other" else group(where.split(".")[-2] if "." in where else where)][r] += 1
    print("| group | ok | fail | error | skip |")
    print("|---|---|---|---|---|")
    for g in [g for g, _ in GROUPS][::-1] + ["other"]:
        t = tally.get(g, {})
        print(f"| {g} | {t.get('ok', 0)} | {t.get('fail', 0)} | {t.get('error', 0)} | {t.get('skip', 0)} |")
    m = re.search(r"^Ran (\d+) tests.*?\n\n(OK.*|FAILED.*)$", text, re.M | re.S)
    print("\n" + (f"Ran {m.group(1)}: {m.group(2)}" if m else "no summary line"))


if __name__ == "__main__":
    main(sys.argv[1])
