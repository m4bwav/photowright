"""Evidence checks for photowright's action evals, run in the eval's work folder.

    python evals/check.py psd|dxf|cutout     # exit 0 = pass
"""
import json, os, subprocess, sys

PHW = [sys.executable, os.environ.get("PHW_SCRIPT", os.path.join("scripts", "phw.py"))]


def psd(path="out/poster.psd", replay=True):
    r = subprocess.run(PHW + ["--json", "open", path], capture_output=True, text=True)
    layers = json.loads(r.stdout).get("layers", [])
    print([(l.get("name"), l.get("blend"), l.get("opacity")) for l in layers])
    by = {l.get("name"): l for l in layers}
    logo = by.get("mark") or {}
    ok = (len(layers) == 2 and "background" in by and logo.get("blend") == "multiply"
          and abs(float(logo.get("opacity", 0)) - 0.7) <= 0.02)
    if not (ok and replay):
        return ok
    # the recipe must rebuild the same file with phw run
    if subprocess.call(PHW + ["run", "out/poster.json", "-o", "out/replay.psd"]) != 0:
        return False
    return psd("out/replay.psd", False)


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
        ok = {"psd": psd, "dxf": dxf, "cutout": cutout}[sys.argv[1]]()
    except Exception as e:  # missing file, bad JSON: a failed check
        print("error:", e)
        ok = False
    sys.exit(0 if ok else 1)
