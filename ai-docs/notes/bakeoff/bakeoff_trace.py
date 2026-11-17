"""Tracer bake-off for the photowright design note (Step C).

Makes a fixed test set in code (plus skimage's public-domain astronaut photo),
traces each image with VTracer (MIT) and two own tracers, renders every SVG back
with an own minimal rasterizer (no SVG library is installed) and scores:
  overlap  share of pixels whose rendered colour is within 24 (max channel) of the source
  paths, nodes, bytes, seconds
Run: python bakeoff_trace.py  -> writes results.json and results.md beside it.
"""
import json, re, time, sys
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
TOL = 24

# ---------- test set ----------
def aa(draw_fn, size, scale=4, bg=(255, 255, 255)):
    big = Image.new("RGB", (size * scale, size * scale), bg)
    draw_fn(ImageDraw.Draw(big), scale)
    return big.resize((size, size), Image.LANCZOS)

def logo():
    def f(d, s):
        d.ellipse([20*s, 20*s, 236*s, 236*s], fill=(200, 30, 40))
        d.ellipse([70*s, 70*s, 186*s, 186*s], fill=(255, 255, 255))
        d.rectangle([118*s, 30*s, 138*s, 226*s], fill=(20, 40, 120))
    return aa(f, 256)

def icon():
    def f(d, s):
        d.rounded_rectangle([16*s, 16*s, 240*s, 240*s], 40*s, fill=(40, 160, 220))
        d.polygon([(128*s, 50*s), (210*s, 200*s), (46*s, 200*s)], fill=(250, 210, 50))
        d.ellipse([108*s, 120*s, 148*s, 160*s], fill=(30, 30, 30))
        d.rectangle([60*s, 210*s, 196*s, 226*s], fill=(240, 90, 60))
    return aa(f, 256)

def lineart():
    def f(d, s):
        d.ellipse([40*s, 40*s, 216*s, 216*s], outline=(0, 0, 0), width=3*s)
        d.line([(60*s, 200*s), (200*s, 60*s)], fill=(0, 0, 0), width=2*s)
        d.arc([80*s, 80*s, 176*s, 176*s], 20, 250, fill=(0, 0, 0), width=2*s)
        for i in range(5):
            d.line([(30*s, (30+i*8)*s), (110*s, (20+i*8)*s)], fill=(0, 0, 0), width=1*s)
    return aa(f, 256)

def sprite():
    rng = np.random.default_rng(7)
    pal = np.array([[0, 0, 0], [255, 255, 255], [190, 60, 50], [60, 140, 70], [240, 200, 90], [40, 60, 140]], np.uint8)
    idx = np.ones((16, 16), int)
    yy, xx = np.mgrid[:16, :16]
    idx[(yy-8)**2 + (xx-8)**2 < 36] = 2
    idx[(yy-8)**2 + (xx-8)**2 < 12] = 4
    idx[12:15, 3:13] = 3
    idx[rng.random((16, 16)) < 0.06] = 5
    idx[0, :] = 0
    return Image.fromarray(pal[idx]).resize((128, 128), Image.NEAREST)

def photo():
    from skimage import data  # astronaut: NASA, public domain (skimage docs)
    return Image.fromarray(data.astronaut()).resize((256, 256), Image.LANCZOS)

SET = {"logo": logo, "icon": icon, "lineart": lineart, "sprite": sprite, "photo": photo}

# ---------- minimal SVG rasterizer (paths + rects, fill only, painter's order) ----------
NUM = r"-?\d*\.?\d+(?:e-?\d+)?"
def flatten(d, tx=0.0, ty=0.0):
    toks = re.findall(r"[MLCQZHVmlcqzhv]|" + NUM, d)
    polys, cur, pts, i, cmd = [], (0.0, 0.0), [], 0, None
    def num():
        nonlocal i; v = float(toks[i]); i += 1; return v
    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]): cmd = toks[i]; i += 1
        c = cmd.upper(); rel = cmd.islower()
        ox, oy = (cur if rel else (0.0, 0.0))
        if c == "M":
            if len(pts) > 2: polys.append(pts)
            cur = (num()+ox, num()+oy); pts = [cur]; cmd = "l" if rel else "L"
        elif c == "L":
            cur = (num()+ox, num()+oy); pts.append(cur)
        elif c == "H":
            cur = (num()+ox, cur[1]); pts.append(cur)
        elif c == "V":
            cur = (cur[0], num()+(cur[1] if rel else 0)); pts.append(cur)
        elif c in "CQ":
            n = 3 if c == "C" else 2
            cp = [cur] + [(num()+ox, num()+oy) for _ in range(n)]
            for t in np.linspace(0, 1, 12)[1:]:
                p = cp
                while len(p) > 1:
                    p = [((1-t)*a[0]+t*b[0], (1-t)*a[1]+t*b[1]) for a, b in zip(p, p[1:])]
                pts.append(p[0])
            cur = cp[-1]
        elif c == "Z":
            if len(pts) > 2: polys.append(pts)
            pts = [cur]
    if len(pts) > 2: polys.append(pts)
    return [[(x+tx, y+ty) for x, y in p] for p in polys]

def render(svg, w, h):
    img = np.full((h*16, w*16, 3), 255, np.uint8)
    for m in re.finditer(r"<(path|rect)\b([^>]*)/?>", svg):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(2)))
        fill = a.get("fill", "#000")
        if fill == "none": continue
        col = tuple(int(fill[k:k+2], 16) for k in (1, 3, 5))
        if m.group(1) == "rect":
            x, y, rw, rh = (float(a.get(k, 0)) for k in ("x", "y", "width", "height"))
            polys = [[(x, y), (x+rw, y), (x+rw, y+rh), (x, y+rh)]]
        else:
            tx = ty = 0.0
            t = re.search(r"translate\(\s*(" + NUM + r")[ ,]+(" + NUM + r")", a.get("transform", ""))
            if t: tx, ty = float(t.group(1)), float(t.group(2))
            polys = flatten(a.get("d", ""), tx, ty)
        arr = [np.round(np.array(p) * 16).astype(np.int32) for p in polys]
        if arr: cv2.fillPoly(img, arr, col)  # array stays RGB; stacked fills, so no even-odd rule
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)

# ---------- tracers ----------
def t_vtracer(src, kind):
    p_in, p_out = OUT / f"_in_{kind}.png", OUT / f"vtracer_{kind}.svg"
    src.save(p_in)
    opts = {}  # colormode="binary" segfaults in vtracer 0.6.15 (py3.14, win_amd64)
    if kind == "sprite": opts = dict(mode="none", filter_speckle=0, color_precision=8)
    import subprocess  # own process: the binding segfaults on some inputs
    r = subprocess.run([sys.executable, "-c", "import sys,json,vtracer;vtracer.convert_image_to_svg_py(sys.argv[1],sys.argv[2],**json.loads(sys.argv[3]))", str(p_in), str(p_out), json.dumps(opts)])
    p_in.unlink()
    if r.returncode: raise RuntimeError(f"vtracer exited {r.returncode} (segfault)")
    return p_out.read_text()

def svg_doc(w, h, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">' + body + "</svg>"

def t_pixel_exact(src, kind):
    """Own: detect the pixel grid, then one rectangle-run path per colour (exact squares)."""
    a = np.asarray(src)
    h, w = a.shape[:2]
    diff = np.any(a[:, 1:] != a[:, :-1], axis=2).any(axis=0)
    edges = np.flatnonzero(diff) + 1
    g = int(np.gcd.reduce(np.concatenate([edges, [w]]))) if len(edges) else w
    small = a[::g, ::g]
    paths = {}
    for y in range(small.shape[0]):
        x = 0
        while x < small.shape[1]:
            c = tuple(small[y, x]); x0 = x
            while x < small.shape[1] and tuple(small[y, x]) == c: x += 1
            paths.setdefault(c, []).append(f"M{x0*g} {y*g}h{(x-x0)*g}v{g}h{-(x-x0)*g}z")
    body = "".join(f'<path fill="#{c[0]:02x}{c[1]:02x}{c[2]:02x}" d="{"".join(d)}"/>' for c, d in paths.items())
    return svg_doc(w, h, body)

def t_quant_contour(src, kind, k=None):
    """Own Potrace-lite baseline: k-means quantize, contours per colour, polygon simplify, stacked by area."""
    a = np.asarray(src).astype(np.float32)
    h, w = a.shape[:2]
    k = k or {"logo": 4, "icon": 6, "lineart": 2, "sprite": 6, "photo": 12}[kind]
    _, lab, cen = cv2.kmeans(a.reshape(-1, 3), k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    lab = lab.reshape(h, w); cen = cen.astype(np.uint8)
    order = np.argsort([-np.sum(lab == i) for i in range(k)])
    body = []
    for n, i in enumerate(order):
        c = cen[i]
        if n == 0:
            body.append(f'<rect width="{w}" height="{h}" fill="#{c[0]:02x}{c[1]:02x}{c[2]:02x}"/>'); continue
        m = (lab == i).astype(np.uint8)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        d = ""
        for cnt in cs:
            if cv2.contourArea(cnt) < 2: continue
            ap = cv2.approxPolyDP(cnt, 0.8, True).reshape(-1, 2)
            if len(ap) < 3: continue
            d += "M" + "L".join(f"{x} {y}" for x, y in ap) + "Z"
        if d: body.append(f'<path fill="#{c[0]:02x}{c[1]:02x}{c[2]:02x}" d="{d}"/>')
    return svg_doc(w, h, "".join(body))

TRACERS = {"vtracer": t_vtracer, "own_quant_contour": t_quant_contour, "own_pixel_exact": t_pixel_exact}

def score(src, svg):
    a = np.asarray(src).astype(int); h, w = a.shape[:2]
    r = render(svg, w, h).astype(int)
    ok = np.abs(a - r).max(axis=2) <= TOL
    return dict(overlap=round(float(ok.mean()), 4),
                paths=len(re.findall(r"<(?:path|rect)\b", svg)),
                nodes=len(re.findall(r"[MLCQHVmlcqhv]", svg)),
                bytes=len(svg.encode()))

def main():
    rows = []
    for kind, mk in SET.items():
        src = mk().convert("RGB")
        src.save(OUT / f"src_{kind}.png")
        for name, fn in TRACERS.items():
            if name == "own_pixel_exact" and kind != "sprite": continue
            t0 = time.perf_counter()
            try: svg = fn(src, kind)
            except Exception as e:
                rows.append(dict(image=kind, tracer=name, error=str(e))); continue
            dt = time.perf_counter() - t0
            (OUT / f"{name}_{kind}.svg").write_text(svg)
            rows.append(dict(image=kind, tracer=name, seconds=round(dt, 3), **score(src, svg)))
            print(rows[-1], flush=True)
    (OUT / "results.json").write_text(json.dumps(rows, indent=1))
    md = ["| image | tracer | overlap | paths | nodes | bytes | s |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['image']} | {r['tracer']} | {r.get('overlap','err')} | {r.get('paths','')} | {r.get('nodes','')} | {r.get('bytes','')} | {r.get('seconds','')} |" for r in rows]
    (OUT / "results.md").write_text("\n".join(md) + f"\n\nOverlap = share of pixels within {TOL} (max channel) after render-back with the bake-off's own rasterizer.\n")

if __name__ == "__main__":
    main()
