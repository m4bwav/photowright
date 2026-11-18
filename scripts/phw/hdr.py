"""Batch 17 (0.18.0): the next rung 1 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

hdrmerge:  Merge to HDR: Debevec-Malik weighted radiance from bracketed sRGB exposures with known
           exposure times (hat weight on the encoded value), then tone mapped (Reinhard) or scaled.
hdrtone:   HDR Toning: Reinhard photographic tone map on luminance (key, white point) with an optional
           local detail boost (log-luminance base/detail split, Durand-Dorsey style).
autoalign: Auto-Align Layers (translation): phase correlation of each image to the first; writes the
           aligned copies and reports the shifts.
lasso:     Magnetic Lasso: intelligent scissors (Mortensen-Barrett): the cheapest path between
           successive anchors over an edge cost, closed and filled into a mask.
widefix:   Adaptive Wide Angle (whole-frame): fisheye (equidistant, equisolid, stereographic or
           orthographic) to rectilinear, so straight lines come out straight.
vpclone:   Vanishing Point clone: copy a quad on a plane to another quad on the same plane through
           the homography between them; pixels outside the destination quad never change.
Own NumPy and Pillow only.
"""
import heapq
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import core, masks
from .core import OPS, floats, to_enc, to_lin
from .grading import with_mask
from .transform import bilinear, homography, load_others, multi, pts, remap

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def lum(lin):
    return lin[..., 0] if lin.shape[2] == 1 else lin[..., :3] @ LUMA


# ---------------------------------------------------------------- tone mapping
def reinhard(lin, key=0.18, white=None, detail=0.0, sigma=8.0):
    """Reinhard et al. 2002 on luminance; colours keep their ratios. detail > 0 boosts the log
    luminance detail layer (log L minus its Gaussian blur) by (1 + detail) before mapping."""
    L = np.maximum(lum(lin), 1e-6).astype(np.float32)
    if detail:
        lg = np.log(L)
        base = core.gaussian_blur(lg, sigma)
        L2 = np.exp(base + (lg - base) * (1.0 + detail)).astype(np.float32)
    else:
        L2 = L
    lavg = float(np.exp(np.mean(np.log(L2))))
    Ls = key / lavg * L2
    if white is None:
        Ld = Ls / (1 + Ls)
    else:
        Ld = Ls * (1 + Ls / (white * white)) / (1 + Ls)
    return np.clip(lin * (Ld / L)[..., None], 0, 1).astype(np.float32)


def op_hdrtone(img, p, used):
    lin = to_lin(img.color())
    out = reinhard(lin, p.get("key", 0.18), p.get("white"), p.get("detail", 0.0), p.get("sigma", 8.0))
    used.add("hdrtone", 1, "own Reinhard tone map" + (" + log-detail boost" if p.get("detail") else ""))
    return img.with_color(to_enc(out))


# ---------------------------------------------------------------- merge to HDR
def debevec(imgs, times):
    """Radiance (linear, relative) from encoded images and exposure times: sum w(z) lin(z)/t / sum w(z),
    w = hat on the encoded value. A pixel clipped in every frame takes the shortest (bright) or the
    longest (dark) frame alone."""
    num = np.zeros_like(imgs[0], np.float64)
    den = np.zeros_like(imgs[0], np.float64)
    for z, t in zip(imgs, times):
        w = np.minimum(z, 1 - z).astype(np.float64)
        num += w * to_lin(z) / t
        den += w
    order = np.argsort(times)
    short, long_ = imgs[order[0]], imgs[order[-1]]
    fallback = np.where(short > 0.5, to_lin(short) / times[order[0]], to_lin(long_) / times[order[-1]])
    return np.where(den > 1e-6, num / np.maximum(den, 1e-12), fallback).astype(np.float32)


def op_hdrmerge(img, p, used):
    imgs = load_others(p, img, used)
    times = [float(t) for t in p["exposures"]]
    if len(times) != len(imgs):
        raise ValueError(f"hdrmerge: {len(imgs)} images but {len(times)} exposure times")
    rad = debevec(imgs, times)
    used.add("hdrmerge", 1, "own Debevec-Malik radiance merge (sRGB response)")
    img.notes.append(f"radiance max {float(rad.max()):.4g}, min {float(rad.min()):.4g} (relative units)")
    if p.get("tonemap", "reinhard") == "none":
        out = rad / max(float(rad.max()), 1e-12)
        used.add("hdrmerge.scale", 1, "linear scale to the brightest pixel")
    else:
        out = reinhard(rad, p.get("key", 0.18), p.get("white"), p.get("detail", 0.0))
        used.add("hdrmerge.tonemap", 1, "own Reinhard tone map")
    if p.get("radiance"):
        np.save(p["radiance"], rad)
    return img.with_color(to_enc(out))


# ---------------------------------------------------------------- auto-align (translation)
def phase_shift(ref, mov):
    """Integer (dy, dx) such that mov shifted by it lines up with ref (np.roll convention)."""
    F = np.fft.fft2(ref) * np.conj(np.fft.fft2(mov))
    r = np.fft.ifft2(F / np.maximum(np.abs(F), 1e-12)).real
    dy, dx = np.unravel_index(int(np.argmax(r)), r.shape)
    h, w = r.shape
    return (int(dy - h if dy > h // 2 else dy), int(dx - w if dx > w // 2 else dx))


def shift_fill(a, dy, dx):
    """Shift without wrap; uncovered pixels transparent (alpha 0) or edge-free zeros."""
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = a[ys, xs]
    return out


def cmd_autoalign(a):
    t0 = time.time()
    used = core.Used()
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ref = core.load(a.inputs[0], used)
    g0 = lum(to_lin(ref.color())) if ref.nc >= 3 else ref.color()[..., 0]
    res = []
    for f in a.inputs:
        im = core.load(f, used)
        if im.px.shape[:2] != ref.px.shape[:2]:
            raise SystemExit(f"autoalign: {f} differs in size from {a.inputs[0]}")
        g = lum(to_lin(im.color())) if im.nc >= 3 else im.color()[..., 0]
        dy, dx = phase_shift(g0, g)
        px = im.px if im.alpha else np.concatenate([im.px, np.ones(im.px.shape[:2] + (1,), np.float32)], 2)
        moved = shift_fill(px, dy, dx)
        out = core.out_for(f, str(outdir / (Path(f).stem + "-aligned.png")), "aligned", ".png")
        core.save(im.copy(px=moved, alpha=True), out, None, used)
        res.append({"input": str(f), "output": str(out), "shift": [dx, dy]})
    used.add("autoalign", 1, "own FFT phase correlation (translation)")
    return {"command": "autoalign", "outputs": res, "seconds": round(time.time() - t0, 3),
            "rung": used.rung(), "tool": used.tool(), "used": used.items}


# ---------------------------------------------------------------- magnetic lasso
def edge_cost(gray):
    gy, gx = np.gradient(gray.astype(np.float64))
    g = np.hypot(gx, gy)
    return (1.0 - g / max(float(g.max()), 1e-12)) + 0.02


def live_wire(cost, a, b, margin):
    """Dijkstra from a to b (x, y) on 8-neighbour moves, restricted to their box plus margin."""
    h, w = cost.shape
    x0, x1 = max(0, min(a[0], b[0]) - margin), min(w - 1, max(a[0], b[0]) + margin)
    y0, y1 = max(0, min(a[1], b[1]) - margin), min(h - 1, max(a[1], b[1]) + margin)
    dist = {a: 0.0}
    prev = {}
    pq = [(0.0, a)]
    nb = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
    while pq:
        d, (x, y) = heapq.heappop(pq)
        if (x, y) == b:
            break
        if d > dist.get((x, y), 1e300):
            continue
        for ddx, ddy in nb:
            nx, ny = x + ddx, y + ddy
            if x0 <= nx <= x1 and y0 <= ny <= y1:
                nd = d + cost[ny, nx] * (1.41421356 if ddx and ddy else 1.0)
                if nd < dist.get((nx, ny), 1e300):
                    dist[(nx, ny)] = nd
                    prev[(nx, ny)] = (x, y)
                    heapq.heappush(pq, (nd, (nx, ny)))
    path, q = [b], b
    while q != a:
        q = prev[q]
        path.append(q)
    return path[::-1]


def magnetic_path(gray, anchors, margin=12):
    cost = edge_cost(gray)
    pts_ = [(int(round(x)), int(round(y))) for x, y in anchors]
    path = []
    for i in range(len(pts_)):
        seg = live_wire(cost, pts_[i], pts_[(i + 1) % len(pts_)], margin)
        path.extend(seg[:-1])
    return path


def poly_mask(shape, path):
    h, w = shape
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon([(float(x), float(y)) for x, y in path], fill=255, outline=255)
    return np.asarray(m, np.float32) / 255.0


def cmd_lasso(a):
    t0 = time.time()
    used = core.Used()
    img = core.load(a.input, used)
    anchors = [floats(q, 2) for q in a.points.split()]
    if len(anchors) < 3:
        raise SystemExit("lasso: give at least 3 anchor points 'x,y x,y x,y'")
    c = img.color()
    gray = lum(to_lin(c)) if img.nc >= 3 else c[..., 0]
    if a.polygon:
        path = [(x, y) for x, y in anchors]
        used.add("lasso", 1, "own polygon lasso")
    else:
        path = magnetic_path(gray, anchors, a.margin)
        used.add("lasso", 1, "own intelligent scissors (Dijkstra on gradient cost)")
    m = poly_mask(gray.shape, path)
    out = core.out_for(a.input, a.output, "lasso-mask", ".png")
    masks.save_mask(m, out, used)
    if a.path_json:
        Path(a.path_json).write_text(json.dumps([[int(x), int(y)] for x, y in path]))
    return {"command": "lasso", "input": str(a.input), "output": str(out), "path_points": len(path),
            "coverage": round(float(m.mean()), 4), "seconds": round(time.time() - t0, 3),
            "rung": used.rung(), "tool": used.tool(), "used": used.items}


# ---------------------------------------------------------------- vanishing point clone
def op_vpclone(img, p, used):
    src, dst = p["src"], p["dst"]
    c = img.color()
    h, w = c.shape[:2]
    H = homography(dst, src)  # destination pixel -> source position
    inside = poly_mask((h, w), [tuple(q) for q in dst]) > 0.5
    ys, xs = np.nonzero(inside)
    if len(ys) == 0:
        raise ValueError("vpclone: the destination quad covers no pixels")
    P = H @ np.stack([xs, ys, np.ones_like(xs)]).astype(np.float64)
    X, Y = (P[0] / P[2]).astype(np.float32), (P[1] / P[2]).astype(np.float32)
    vals, _ = bilinear(c, X[None], Y[None], [0.0] * c.shape[2])
    out = c.copy()
    out[ys, xs] = vals[0]
    used.add("vpclone", 1, "own homography clone (bilinear)")
    return img.with_color(out)


# ---------------------------------------------------------------- adaptive wide angle
FISHEYE = {"equidistant": (lambda t: t, lambda r: r),
           "equisolid": (lambda t: 2 * np.sin(t / 2), lambda r: 2 * np.arcsin(np.clip(r / 2, -1, 1))),
           "stereographic": (lambda t: 2 * np.tan(t / 2), lambda r: 2 * np.arctan(r / 2)),
           "orthographic": (lambda t: np.sin(t), lambda r: np.arcsin(np.clip(r, -1, 1)))}


def fisheye_focals(w, h, fov, out_fov, model):
    half = np.hypot(w, h) / 2
    g, _ = FISHEYE[model]
    ff = half / float(g(np.radians(fov) / 2))
    fo = half / np.tan(np.radians(out_fov) / 2)
    return ff, fo


def op_widefix(img, p, used):
    h, w = img.px.shape[:2]
    model = p.get("model", "equidistant")
    fov = float(p["fov"])
    out_fov = float(p.get("out_fov") or min(fov, 120.0))
    if out_fov >= 179:
        raise ValueError("widefix: a rectilinear output needs --out-fov below 179 degrees")
    ff, fo = fisheye_focals(w, h, fov, out_fov, model)
    g, _ = FISHEYE[model]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    dx, dy = xx - cx, yy - cy
    ro = np.hypot(dx, dy)
    theta = np.arctan(ro / fo)
    rf = ff * g(theta)
    s = np.where(ro > 1e-9, rf / np.maximum(ro, 1e-9), ff / fo)
    X, Y = (cx + dx * s).astype(np.float32), (cy + dy * s).astype(np.float32)
    out = remap(img, X, Y, used, "widefix", p.get("fill"), prefilter=True)
    used.add("widefix", 1, f"own {model} fisheye to rectilinear")
    return out


def cmd_widefix(a):
    p = {"fov": a.fov, "out_fov": a.out_fov, "model": a.model}
    return core.edit_command(a, "widefix", [{"op": "widefix", "params": p}])


def cmd_vpclone(a):
    p = {"src": pts(a.src), "dst": pts(a.dst)}
    return core.edit_command(a, "vpclone", with_mask(a, [{"op": "vpclone", "params": p}]))


def cmd_hdrtone(a):
    p = {"key": a.key, "white": a.white, "detail": a.detail, "sigma": a.sigma}
    return core.edit_command(a, "hdrtone", with_mask(a, [{"op": "hdrtone", "params": p}]))


def cmd_hdrmerge(a):
    times = floats(a.exposures)
    p = {"exposures": times, "tonemap": a.tonemap, "key": a.key, "white": a.white, "detail": a.detail}
    if a.radiance:
        p["radiance"] = str(Path(a.radiance).resolve())
    return multi(a, "hdrmerge", p)


OPS.update({"widefix": op_widefix, "hdrtone": op_hdrtone, "hdrmerge": op_hdrmerge, "vpclone": op_vpclone})


def add_commands(sub, edit):
    p = edit("hdrtone", cmd_hdrtone, "HDR Toning: Reinhard tone map with optional local detail (rung 1)")
    p.add_argument("--key", type=float, default=0.18, help="target mean (log) luminance")
    p.add_argument("--white", type=float, help="scaled luminance that maps to white (default: none, L/(1+L))")
    p.add_argument("--detail", type=float, default=0.0, help="local detail boost, 0 = global")
    p.add_argument("--sigma", type=float, default=8.0, help="detail base blur in px")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("vpclone", cmd_vpclone, "Vanishing Point: clone a quad onto another quad of the same plane (rung 1)")
    p.add_argument("--src", required=True, help="'x,y x,y x,y x,y' source quad (TL TR BR BL)")
    p.add_argument("--dst", required=True, help="destination quad, same corner order")
    p.add_argument("--mask", help="8-bit mask PNG: edit applies where white")
    p = edit("widefix", cmd_widefix, "Adaptive Wide Angle: fisheye to rectilinear, straight lines straight (rung 1)")
    p.add_argument("--fov", type=float, required=True, help="diagonal field of view of the fisheye, degrees")
    p.add_argument("--out-fov", type=float, help="diagonal field of view of the result (default min(fov, 120))")
    p.add_argument("--model", choices=tuple(FISHEYE), default="equidistant")
    p = sub.add_parser("hdrmerge", help="Merge to HDR: Debevec radiance from brackets, tone mapped (rung 1)")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--exposures", required=True, help="exposure times, one per image, e.g. 0.25,1,4")
    p.add_argument("--tonemap", choices=("reinhard", "none"), default="reinhard")
    p.add_argument("--key", type=float, default=0.18)
    p.add_argument("--white", type=float)
    p.add_argument("--detail", type=float, default=0.0)
    p.add_argument("--radiance", help="also save the float32 radiance map as .npy")
    p.add_argument("-o", "--output")
    p.add_argument("--recipe")
    p.add_argument("--bits", type=int, choices=(8, 16))
    p.set_defaults(fn=cmd_hdrmerge)
    p = sub.add_parser("autoalign", help="Auto-Align Layers: translate each image onto the first (rung 1)")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--outdir", required=True)
    p.set_defaults(fn=cmd_autoalign)
    p = sub.add_parser("lasso", help="Magnetic Lasso: edge-snapping path through anchors to a mask (rung 1)")
    p.add_argument("input")
    p.add_argument("--points", required=True, help="'x,y x,y x,y ...' anchors around the object")
    p.add_argument("--polygon", action="store_true", help="straight polygon lasso instead of magnetic")
    p.add_argument("--margin", type=int, default=12, help="search margin around each segment, px")
    p.add_argument("--path-json", help="also write the path points as JSON")
    p.add_argument("-o", "--output")
    p.set_defaults(fn=cmd_lasso)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {"hdrmerge, hdrtone, autoalign, lasso, vpclone, widefix": (1, "own NumPy + Pillow")})
