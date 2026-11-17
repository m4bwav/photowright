"""Evidence checks for photowright's action evals, run in the eval's work folder.

    python evals/check.py trace|dxf|cutout     # exit 0 = pass
"""
import json, os, subprocess, sys

PHW = [sys.executable, os.environ.get("PHW_SCRIPT", os.path.join("scripts", "phw.py"))]


def trace():
    r = subprocess.run(PHW + ["--json", "vcheck", "out/logo.svg", "--source", "tests/fixtures/logo.png"],
                       capture_output=True, text=True)
    j = json.loads(r.stdout)
    print("overlap", j.get("overlap"), "paths", j.get("counts", {}).get("paths"))
    return j["overlap"] >= 0.95 and j["counts"]["paths"] <= 8


def dxf():
    lines = [x.strip() for x in open("out/logo.dxf", encoding="utf-8", errors="replace").read().splitlines()]
    if "ENTITIES" not in lines or "$EXTMAX" not in lines:
        return False
    i = lines.index("$EXTMAX")
    xmax = float(lines[i + 2]) if lines[i + 1] == "10" else -1
    print("EXTMAX x", xmax)
    return abs(xmax - 50) <= 1.5  # 50 mm wide; a px export would read 256


def cutout():
    from PIL import Image
    a = Image.open("out/logo-cut.png").convert("RGBA").getchannel("A")
    if not (a.getpixel((2, 2)) < 20 and a.getpixel((128, 128)) > 235):
        return False
    return subprocess.call(PHW + ["run", "out/cut.json", "-o", "out/replay.png"]) == 0


if __name__ == "__main__":
    try:
        ok = {"trace": trace, "dxf": dxf, "cutout": cutout}[sys.argv[1]]()
    except Exception as e:  # missing file, bad JSON: a failed check
        print("error:", e)
        ok = False
    sys.exit(0 if ok else 1)
