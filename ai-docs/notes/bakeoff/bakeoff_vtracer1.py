import json, subprocess, sys, time
from pathlib import Path
W = Path(sys.argv[1]); S = Path(sys.argv[2]); OUT = S / "runs2"; OUT.mkdir(exist_ok=True)
PHW = [sys.executable, str(W / "scripts/phw.py"), "--json"]
VT1 = str(S / "vt1/vtracer.exe")
KIND = {"logo": "logo", "icon": "icon", "lineart": "line", "photo": "photo", "sprite": "pixel"}
VT1_ARGS = {"default": [], "pixel": ["-m", "pixel", "-f", "0", "-p", "8"], "preset-bw": ["--preset", "bw"],
            "preset-poster": ["--preset", "poster"], "preset-photo": ["--preset", "photo"], "simplify1.5": ["--simplify", "1.5"]}
def js(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    try: return json.loads(r.stdout)
    except Exception: return {"error": (r.stderr or r.stdout)[-300:], "rc": r.returncode}
def check(svg, src, kind):
    c = js(PHW + ["vcheck", str(svg), "--source", str(src), "--kind", kind])
    return {k: c.get(k) for k in ("overlap", "pass", "fails")} | {"counts": c.get("counts"), "err": c.get("error")}
rows = []
for img, kind in KIND.items():
    src = W / f"ai-docs/notes/bakeoff/src_{img}.png"
    for be in ("own", "vtracer"):
        o = OUT / f"{img}_phw_{be}.svg"; t = time.time()
        r = js(PHW + ["trace", str(src), "-o", str(o), "--kind", kind, "--backend", be, "--no-check"])
        dt = time.time() - t
        out = Path(r.get("output", o))
        rows.append({"image": img, "tracer": f"phw {be}" + (" (0.6.15)" if be == "vtracer" else ""), "s": round(dt, 2),
                     **(check(out, src, kind) if out.exists() else {"err": r.get("error")})})
        print(rows[-1], flush=True)
    for name, args in VT1_ARGS.items():
        if name == "pixel" and img != "sprite": continue
        o = OUT / f"{img}_vt1_{name}.svg"; t = time.time()
        r = subprocess.run([VT1, *args, str(src), str(o)], capture_output=True, text=True)
        dt = time.time() - t
        rows.append({"image": img, "tracer": f"vtracer 1.0a4 {name}", "s": round(dt, 2),
                     **(check(o, src, kind) if o.exists() else {"err": (r.stderr or "")[-200:]})})
        print(rows[-1], flush=True)
(S / "results.json").write_text(json.dumps(rows, indent=1))
