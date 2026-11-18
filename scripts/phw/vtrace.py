"""Raster to vector: trace --kind logo|icon|line|photo|pixel|centreline.

Rungs:
  pixel        1 own pixel-exact tracer: grid detection, boundary loops on the pixel-corner lattice,
                 collinear runs merged; exact squares, one even-odd path per colour
  logo, icon,  2 VTracer (MIT, pip install vtracer), always in a SUBPROCESS: the 0.6.15 binding
  line, photo    segfaults with colormode=binary and mode=none (Windows, Python 3.14)
               1 own region tracer with holes: palette or k-means labels, lattice boundary loops
                 (outer and hole loops, hierarchy by orientation), even-odd fill, corner split and
                 least-squares cubic fit. Written from published papers (Selinger 2003 describes the
                 lattice walk; Schneider 1990 the fit); GPL Potrace source was never read.
  centreline   1 own Zhang-Suen thinning (1984) | 2 scikit-image skeletonize; then graph walk and fit
  vtracer1     2 VTracer 1.x CLI (MIT, prebuilt, alpha), opt-in --backend vtracer1 via PHW_VTRACER or
                 PATH; photo uses --preset poster (2026-11-17 bake-off: 0.884 vs 0.840 overlap)
  external     potrace CLI (GPL) and Inkscape object-trace (GPL), optional, never bundled
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import core, vector as V
from .core import probe, rung_max

KINDS = ("logo", "icon", "line", "photo", "pixel", "centreline")
VT_CODE = ("import sys,json,vtracer;"
           "vtracer.convert_image_to_svg_py(sys.argv[1],sys.argv[2],**json.loads(sys.argv[3]))")
OWN_K = {"logo": 8, "icon": 12, "line": 4, "photo": 32}   # photo 32: 0.804 (16: 0.783, 24: 0.799, 40: 0.798)


# ---------------------------------------------------------------- lattice boundary loops
def lattice_loops(mask):
    """Boundary loops of a boolean mask on the pixel-corner lattice, interior on the right (y down).
    Returns a list of (n, 2) vertex arrays; outer loops and holes have opposite orientation.
    At a diagonal pinch the walk turns right, so pixels touching only at a corner stay apart."""
    h, w = mask.shape
    P = np.pad(mask, 1)
    ins = P[1:-1, 1:-1]
    E = []  # x0, y0, x1, y1
    for sel, f in ((ins & ~P[:-2, 1:-1], lambda y, x: (x, y, x + 1, y)),
                   (ins & ~P[2:, 1:-1], lambda y, x: (x + 1, y + 1, x, y + 1)),
                   (ins & ~P[1:-1, :-2], lambda y, x: (x, y + 1, x, y)),
                   (ins & ~P[1:-1, 2:], lambda y, x: (x + 1, y, x + 1, y + 1))):
        ys, xs = np.nonzero(sel)
        if len(ys):
            E.append(np.stack(f(ys, xs), 1))
    if not E:
        return []
    E = np.vstack(E).astype(np.int64)
    W1 = w + 1
    sk = E[:, 1] * W1 + E[:, 0]
    ek = E[:, 3] * W1 + E[:, 2]
    order = np.argsort(sk, kind="stable")
    sks = sk[order]
    lo = np.searchsorted(sks, ek, "left")
    hi = np.searchsorted(sks, ek, "right")
    nxt = order[np.minimum(lo, len(order) - 1)].copy()
    amb = np.nonzero(hi - lo > 1)[0]
    if len(amb):
        d = E[:, 2:] - E[:, :2]
        for e in amb:
            right = (-d[e, 1], d[e, 0])
            cands = order[lo[e]:hi[e]]
            pick = [c for c in cands if tuple(d[c]) == right]
            nxt[e] = pick[0] if pick else cands[0]
    seen = np.zeros(len(E), bool)
    loops = []
    for s in range(len(E)):
        if seen[s]:
            continue
        cyc = []
        e = s
        while not seen[e]:
            seen[e] = True
            cyc.append(e)
            e = nxt[e]
        loops.append(E[cyc, :2].astype(float))
    return loops


def merge_collinear(L):
    """Drop lattice vertices where the direction does not change."""
    d = np.roll(L, -1, axis=0) - L
    dp = L - np.roll(L, 1, axis=0)
    turn = (d[:, 0] * dp[:, 1] - d[:, 1] * dp[:, 0]) != 0
    return L[turn]


# ---------------------------------------------------------------- pixel tracer
def pixel_grid(a):
    """Pixel-art cell size: gcd of every run boundary in x and y (and of the size)."""
    h, w = a.shape[:2]
    dx = np.any(a[:, 1:] != a[:, :-1], axis=2).any(axis=0)
    dy = np.any(a[1:] != a[:-1], axis=2).any(axis=1)
    edges = np.concatenate([np.flatnonzero(dx) + 1, np.flatnonzero(dy) + 1, [w, h]])
    return int(np.gcd.reduce(edges.astype(np.int64)))


def trace_pixel(img, used):
    """Exact squares: one even-odd path per colour from lattice loops, collinear runs merged."""
    im = img.convert("RGBA")
    a = np.asarray(im)
    h, w = a.shape[:2]
    g = pixel_grid(a)
    small = a[::g, ::g]
    sh_, sw_ = small.shape[:2]
    key = (small[..., 0].astype(np.int64) << 24) | (small[..., 1].astype(np.int64) << 16) | \
          (small[..., 2].astype(np.int64) << 8) | small[..., 3].astype(np.int64)
    vals, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    inv = inv.reshape(sh_, sw_)
    shapes, holes = [], 0
    for i in np.argsort(-cnt):
        v = int(vals[i])
        if (v & 255) == 0:
            continue
        subs = []
        for L in lattice_loops(inv == i):
            Lm = merge_collinear(L) * g
            if V.signed_area(Lm) < 0:
                holes += 1
            subs.append({"start": tuple(Lm[0]), "segs": [("L", tuple(p)) for p in Lm[1:]], "closed": True})
        shapes.append({"fill": ((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255), "stroke": None, "width": 0,
                       "rule": "evenodd", "subs": subs})
        if (v & 255) < 255:
            shapes[-1]["opacity"] = (v & 255) / 255.0
    used.add("trace", 1, "own pixel-exact tracer (lattice loops, merged runs)")
    partial = int(((a[..., 3] > 0) & (a[..., 3] < 255)).sum())
    notes = [f"grid {g} px: {sw_}x{sh_} cells"]
    if partial:
        notes.append(f"{partial} semi-transparent pixels kept as fill-opacity")
    return {"width": w, "height": h, "shapes": shapes, "notes": notes}, {"grid": g, "cells": sh_ * sw_, "holes": holes}


# ---------------------------------------------------------------- colour labels
def kmeans(X, k, iters=12, seed=0):
    rng = np.random.default_rng(seed)
    S = X[rng.choice(len(X), min(len(X), 20000), replace=False)] if len(X) > 20000 else X
    C = [S[0]]
    d = ((S - C[0]) ** 2).sum(1)
    for _ in range(1, k):
        C.append(S[int(np.argmax(d))])
        d = np.minimum(d, ((S - C[-1]) ** 2).sum(1))
    C = np.array(C, np.float32)
    for _ in range(iters):
        lab = np.argmin(((S[:, None] - C[None]) ** 2).sum(2), 1)
        for j in range(k):
            m = lab == j
            if m.any():
                C[j] = S[m].mean(0)
    return C


def assign(X, C):
    out = np.empty(len(X), np.int64)
    for i in range(0, len(X), 65536):
        out[i:i + 65536] = np.argmin(((X[i:i + 65536, None] - C[None]) ** 2).sum(2), 1)
    return out


def palette_labels(a, kind):
    """Flat art: the dominant exact colours are the palette; else k-means. Returns labels, colours, method."""
    h, w = a.shape[:2]
    X = a.reshape(-1, 3).astype(np.float32)
    k = OWN_K.get(kind, 8)
    method = "kmeans"
    C = None
    if kind != "photo":
        key = (a[..., 0].astype(np.int64) << 16) | (a[..., 1].astype(np.int64) << 8) | a[..., 2]
        vals, cnt = np.unique(key, return_counts=True)
        pal = []
        for i in np.argsort(-cnt):
            if cnt[i] < max(8, 0.002 * h * w) or len(pal) >= k:
                break
            c = np.array([(vals[i] >> 16) & 255, (vals[i] >> 8) & 255, vals[i] & 255], np.float32)
            if all(np.abs(c - p).max() > 40 for p in pal):
                pal.append(c)
        if len(pal) >= 2:
            P = np.array(pal)
            near = np.abs(X[:, None] - P[None]).max(2).min(1) <= V.TOL
            if near.mean() >= 0.85:
                C, method = P, "dominant colours"
    if C is None:
        C = kmeans(X, k)
    lab = assign(X, C).reshape(h, w)
    if method == "kmeans":
        C = np.array([X[lab.ravel() == j].mean(0) if (lab == j).any() else C[j] for j in range(len(C))])
    return lab, np.rint(C).astype(int), method


def mode_filter(lab, k):
    """3x3 majority vote (removes one-pixel speckle before tracing)."""
    P = np.pad(lab, 1, mode="edge")
    h, w = lab.shape
    best, bestc = lab.copy(), np.zeros(lab.shape, np.int32)
    for j in range(k):
        m = (P == j).astype(np.int32)
        c = sum(m[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3))
        upd = c > bestc
        best[upd], bestc[upd] = j, c[upd]
    return best


# ---------------------------------------------------------------- own region tracer
def _bad(sub):
    P = V.flatten(sub, per_px=3.0, nmax=16)
    if np.allclose(P[0], P[-1]):
        P = P[:-1]
    if len(P) < 3 or abs(V.signed_area(P)) < 0.5:
        return "stray"
    return "cross" if len(P) <= 4000 and V.self_crossings(P) else None


def safe_fit(L, tol, corner):
    """Fit one lattice loop: smoothed edge midpoints -> curves; if the fit crosses itself, an RDP polygon of
    the midpoints; if that crosses too, the exact lattice polygon (which never crosses). None = too small."""
    M = (L + np.roll(L, -1, axis=0)) / 2       # edge midpoints: a smooth sample of the boundary
    sub = V.fit_path(M, True, tol, corner, smooth=2)
    why = _bad(sub)
    if why is None:
        return sub
    if why == "stray":
        return None
    Q = V.rdp(np.vstack([M, M[:1]]), tol)[:-1]
    if len(Q) >= 3:
        sub = {"start": tuple(Q[0]), "segs": [("L", tuple(p)) for p in Q[1:]], "closed": True}
        if _bad(sub) is None:
            return sub
    Lm = merge_collinear(L)
    return {"start": tuple(Lm[0]), "segs": [("L", tuple(p)) for p in Lm[1:]], "closed": True}


def brightness_bands(a, scans):
    """Inkscape's brightness steps without its off-by-one: exactly `scans` thresholds evenly spaced in
    (0, 256), so exactly `scans` layers; band 0 is the darkest, band `scans` (the brightest) is the page."""
    g = (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114)
    T = [round(256 * (i + 1) / (scans + 1)) for i in range(scans)]
    lab = np.digitize(g, T)
    C = np.array([[int(round(g[lab == j].mean())) if (lab == j).any() else 255] * 3 for j in range(scans + 1)])
    return lab, C, T


def trace_region(img, kind, used, tol=0.6, speckle=4.0, corner=50.0, stack=False, background=True, scans=None):
    """Own region tracer with holes: labels, lattice loops (outer + hole), even-odd fill, fitted curves.
    The most common colour becomes a full-canvas rectangle underneath (stacked), so fitted seams never
    show the empty page; background=False drops it (Inkscape's remove background).
    stack=True: each layer also covers every layer drawn above it (no seam gaps, Inkscape's stack scans);
    stack=False: layers do not overlap. scans=N: N brightness steps instead of colours (always stacked).
    Closed loops under `speckle` px^2 are dropped (Inkscape's suppress speckles)."""
    a = V.source_rgb(img)
    h, w = a.shape[:2]
    info_extra = {}
    if scans:
        lab, C, T = brightness_bands(a, int(scans))
        method = f"{scans} brightness steps"
        order = list(range(int(scans), -1, -1))           # brightest (page) first, darkest on top
        stack = True
        info_extra = {"thresholds": T, "scans": int(scans)}
    else:
        lab, C, method = palette_labels(a, kind)
        if kind == "photo":
            lab = mode_filter(lab, len(C))
        cnt = np.bincount(lab.ravel(), minlength=len(C))
        order = [int(j) for j in np.argsort(-cnt) if cnt[j]]
    bg = order[0]
    shapes = []
    if background:
        shapes.append({"fill": tuple(C[bg]), "stroke": None, "width": 0, "rule": "nonzero",
                       "subs": [{"start": (0.0, 0.0), "segs": [("L", (w, 0.0)), ("L", (w, h)), ("L", (0.0, h))],
                                 "closed": True}]})
    holes = outers = dropped = 0
    for pos, j in enumerate(order[1:], 1):
        subs = []
        mask = np.isin(lab, order[pos:]) if stack else lab == j
        for L in lattice_loops(mask):
            ar = V.signed_area(L)
            if abs(ar) < speckle:
                dropped += 1
                continue
            if ar < 0:
                holes += 1
            else:
                outers += 1
            sub = safe_fit(L, tol, corner)
            if sub is None:
                dropped += 1
                continue
            subs.append(sub)
        if subs:
            shapes.append({"fill": tuple(C[j]), "stroke": None, "width": 0, "rule": "evenodd", "subs": subs})
    used.add("trace", 1, "own region tracer (lattice loops with holes, even-odd, cubic fit)")
    return ({"width": w, "height": h, "shapes": shapes, "notes": [f"labels: {method}, {len(order)} colours"]},
            dict({"outer_loops": outers, "hole_loops": holes, "speckles_dropped": dropped, "labels": method,
                  "stacked": bool(stack), "background": bool(background)}, **info_extra))


# ---------------------------------------------------------------- centreline
def otsu(gray):
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    p = hist / hist.sum()
    om, mu = np.cumsum(p), np.cumsum(p * np.arange(256))
    sb = (mu[-1] * om - mu) ** 2 / np.maximum(om * (1 - om), 1e-12)
    return int(np.argmax(sb))


def zhang_suen(m):
    """Zhang and Suen (1984) parallel thinning, vectorised."""
    m = np.pad(m.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            P2, P3, P4 = m[:-2, 1:-1], m[:-2, 2:], m[1:-1, 2:]
            P5, P6, P7 = m[2:, 2:], m[2:, 1:-1], m[2:, :-2]
            P8, P9 = m[1:-1, :-2], m[:-2, :-2]
            nb = [P2, P3, P4, P5, P6, P7, P8, P9]
            B = sum(nb)
            A = sum(((nb[i] == 0) & (nb[(i + 1) % 8] == 1)).astype(np.uint8) for i in range(8))
            c = m[1:-1, 1:-1] == 1
            if step == 0:
                cond = (P2 * P4 * P6 == 0) & (P4 * P6 * P8 == 0)
            else:
                cond = (P2 * P4 * P8 == 0) & (P2 * P6 * P8 == 0)
            rm = c & (B >= 2) & (B <= 6) & (A == 1) & cond
            if rm.any():
                m[1:-1, 1:-1][rm] = 0
                changed = True
        if not changed:
            return staircase(m[1:-1, 1:-1].astype(bool))


def staircase(sk):
    """Remove Zhang-Suen's leftover staircase corners: a pixel whose two perpendicular 4-neighbours make
    an L, that is simple (Yokoi 8-connectivity number 1, Yokoi 1973) and not an end. One orientation per pass."""
    m = np.pad(sk.astype(np.uint8), 1)
    for _ in range(4):
        changed = False
        for a, b in (("N", "E"), ("E", "S"), ("S", "W"), ("W", "N")):
            x = {"E": m[1:-1, 2:], "NE": m[:-2, 2:], "N": m[:-2, 1:-1], "NW": m[:-2, :-2],
                 "W": m[1:-1, :-2], "SW": m[2:, :-2], "S": m[2:, 1:-1], "SE": m[2:, 2:]}
            ring = [x[k] for k in ("E", "NE", "N", "NW", "W", "SW", "S", "SE")]
            c = [1 - r for r in ring]
            n8 = sum(c[k] - c[k] * c[(k + 1) % 8] * c[(k + 2) % 8] for k in (0, 2, 4, 6))
            rm = (m[1:-1, 1:-1] == 1) & (x[a] == 1) & (x[b] == 1) & (n8 == 1) & (sum(ring) >= 2)
            if rm.any():
                m[1:-1, 1:-1][rm] = 0
                changed = True
        if not changed:
            break
    return m[1:-1, 1:-1].astype(bool)


def skeleton_paths(sk):
    """Walk the 8-connected skeleton graph into polylines between ends and junctions (plus closed loops)."""
    h, w = sk.shape
    pts = set(zip(*np.nonzero(sk)))
    N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def nbrs(p):
        return [(p[0] + dy, p[1] + dx) for dy, dx in N8 if (p[0] + dy, p[1] + dx) in pts]
    deg = {p: len(nbrs(p)) for p in pts}
    nodes = {p for p, d in deg.items() if d != 2}
    used_e, paths = set(), []

    def walk(a, b):
        path = [a, b]
        used_e.add((a, b))
        used_e.add((b, a))
        prev, cur = a, b
        while cur not in nodes:
            nx = [q for q in nbrs(cur) if q != prev and (cur, q) not in used_e]
            if not nx:
                break
            prev, cur = cur, nx[0]
            used_e.add((prev, cur))
            used_e.add((cur, prev))
            path.append(cur)
            if cur == path[0]:
                break
        return path
    for n in sorted(nodes):
        for q in nbrs(n):
            if (n, q) not in used_e:
                paths.append(walk(n, q))
    for p in sorted(pts):
        if p not in nodes:
            for q in nbrs(p):
                if (p, q) not in used_e:
                    paths.append(walk(p, q))
    return [np.array([(x + 0.5, y + 0.5) for y, x in pth], float) for pth in paths if len(pth) >= 2]


def trace_centreline(img, used, tol=0.8, min_len=3.0):
    a = V.source_rgb(img)
    h, w = a.shape[:2]
    gray = np.rint(a @ [0.2126, 0.7152, 0.0722]).astype(np.uint8)
    t = otsu(gray)
    ink = gray <= t
    sk_mod = probe("skimage.morphology")
    if sk_mod is not None:
        sk = sk_mod.skeletonize(ink)
        used.add("trace", 2, "scikit-image skeletonize")
    else:
        sk = zhang_suen(ink)
        used.add("trace", 1, "own Zhang-Suen thinning")
    polys = skeleton_paths(sk)
    length = sum(float(np.hypot(*np.diff(P, axis=0).T).sum()) for P in polys) or 1.0
    width = float(max(1.0, ink.sum() / length))
    col = tuple(int(v) for v in np.rint(a[ink].mean(0))) if ink.any() else (0, 0, 0)
    subs = []
    for P in polys:
        if float(np.hypot(*np.diff(P, axis=0).T).sum()) < min_len:
            continue
        closed = len(P) > 3 and np.hypot(*(P[0] - P[-1])) < 1.5
        subs.append(V.fit_path(P[:-1] if closed else P, closed, tol, smooth=2))
    used.add("trace", 1, "own skeleton graph walk + cubic fit")
    doc = {"width": w, "height": h, "notes": [f"ink threshold {t} (Otsu), stroke width {width:.2f} px (area / length)"],
           "shapes": [{"fill": None, "stroke": col, "width": round(width, 2), "rule": "nonzero", "subs": subs}]}
    return doc, {"strokes": len(subs), "stroke_width": round(width, 2), "threshold": t}


# ---------------------------------------------------------------- external and rung 2 tracers
def vtracer_ok():
    return rung_max() >= 2 and importlib.util.find_spec("vtracer") is not None


def run_vtracer(img, opts, timeout=180):
    """VTracer in its own process. Returns (doc, None) or (None, reason)."""
    with tempfile.TemporaryDirectory() as td:
        pin, pout = Path(td) / "in.png", Path(td) / "out.svg"
        img.convert("RGBA").save(pin)
        try:
            r = subprocess.run([sys.executable, "-c", VT_CODE, str(pin), str(pout), json.dumps(opts)],
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, f"vtracer timed out after {timeout} s"
        if r.returncode or not pout.exists():
            return None, f"vtracer exited {r.returncode} (the binding crashed; options {opts})"
        doc = V.read_svg(pout)
    return doc, None


VT1_PRESET = {"photo": ["--preset", "poster"]}  # 2026-11-17 bake-off: 0.884 vs 0.840 overlap on photo


def find_vtracer1():
    """VTracer 1.x CLI (MIT, prebuilt at github.com/visioncortex/vtracer/releases): PHW_VTRACER or PATH."""
    if rung_max() < 2:
        return None
    exe = os.environ.get("PHW_VTRACER") or shutil.which("vtracer")
    if not exe or not Path(exe).exists():
        return None
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe if re.search(r"\b1\.\d", v) else None


def run_vtracer1(img, kind, timeout=180):
    """VTracer 1.x CLI in its own process. Returns (doc, None) or (None, reason)."""
    exe = find_vtracer1()
    if exe is None:
        return None, "VTracer 1.x CLI not found (set PHW_VTRACER or put vtracer 1.x on PATH)"
    with tempfile.TemporaryDirectory() as td:
        pin, pout = Path(td) / "in.png", Path(td) / "out.svg"
        img.convert("RGBA").save(pin)
        try:
            r = subprocess.run([exe, *VT1_PRESET.get(kind, []), str(pin), str(pout)],
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, f"vtracer 1.x timed out after {timeout} s"
        if r.returncode or not pout.exists():
            return None, f"vtracer 1.x exited {r.returncode}: {(r.stderr or '')[-200:]}"
        doc = V.read_svg(pout)
    return doc, None


def find_potrace():
    if rung_max() < 2:
        return None
    return shutil.which("potrace")


def run_potrace(img, tol):
    exe = find_potrace()
    if exe is None:
        raise SystemExit("trace --backend potrace: potrace not found on PATH. It is GPL, so photowright never "
                         "bundles it; install it from https://potrace.sourceforge.net/ if you want it.")
    a = V.source_rgb(img)
    gray = np.rint(a @ [0.2126, 0.7152, 0.0722]).astype(np.uint8)
    with tempfile.TemporaryDirectory() as td:
        pbm, svg = Path(td) / "in.pbm", Path(td) / "out.svg"
        Image.fromarray(np.where(gray <= otsu(gray), 0, 255).astype(np.uint8)).convert("1").save(pbm)
        r = subprocess.run([exe, str(pbm), "-s", "-o", str(svg), "--opttolerance", str(tol)],
                           capture_output=True, text=True, timeout=180)
        if r.returncode:
            raise RuntimeError("potrace failed: " + r.stderr[-300:])
        doc = V.read_svg(svg)
    doc["width"], doc["height"] = a.shape[1], a.shape[0]
    return doc


def run_inkscape_trace(img, scans=8):
    exe = V.inkscape()
    if exe is None:
        raise SystemExit("trace --backend inkscape: Inkscape not found (or hidden at rung 1). It is GPL and "
                         "external only; install it from https://inkscape.org/ if you want this backend.")
    with tempfile.TemporaryDirectory() as td:
        pin, pout = Path(td) / "in.png", Path(td) / "out.svg"
        img.convert("RGB").save(pin)
        act = f"select-all;object-trace:{scans},true,true,false,2,1.0,0.2;export-filename:{pout.as_posix()};export-plain-svg;export-do"
        r = subprocess.run([exe, str(pin), f"--actions={act}"], capture_output=True, text=True, timeout=300)
        if r.returncode or not pout.exists():
            raise RuntimeError("inkscape trace failed: " + (r.stderr or r.stdout)[-300:])
        doc = V.read_svg(pout)
    return doc


# ---------------------------------------------------------------- command
def trace(img, kind, backend="auto", tol=None, vt_opts=None, speckle=None, blur=0.0, stack=False,
          background=True, scans=None):
    """Trace a PIL image. Returns (doc, info, used). speckle, stack, background and scans are own region
    tracer options (they force it); blur pre-blurs the input (halftone screens) for every backend."""
    used = core.Used()
    info, notes = {}, []
    if blur:
        from PIL import ImageFilter
        img = img.convert("RGB").filter(ImageFilter.GaussianBlur(blur))
        used.add("pre-blur", 1, f"Pillow Gaussian blur r={blur}")
    if kind in ("logo", "icon", "line", "photo") and (speckle is not None or stack or not background or scans):
        backend = "own"
    if kind == "pixel":
        doc, info = trace_pixel(img, used)
    elif kind == "centreline":
        doc, info = trace_centreline(img, used, tol or 0.8)
    else:
        doc = None
        if backend == "potrace":
            doc = run_potrace(img, tol or 0.2)
            used.add("trace", 2, "potrace CLI (GPL, external)")
        elif backend == "inkscape":
            doc = run_inkscape_trace(img)
            used.add("trace", 2, "Inkscape object-trace (GPL, external)")
        elif backend == "vtracer1":
            doc, err = run_vtracer1(img, kind)
            if doc is not None:
                used.add("trace", 2, "VTracer 1.x CLI (MIT, external)" + (" --preset poster" if kind in VT1_PRESET else ""))
            else:
                notes.append(err + "; own region tracer used")
        elif backend in ("auto", "vtracer"):
            if vtracer_ok():
                doc, err = run_vtracer(img, vt_opts or {})
                if doc is not None:
                    used.add("trace", 2, "VTracer (MIT) in a subprocess")
                else:
                    notes.append(err + "; fell back to the own region tracer")
            elif backend == "vtracer":
                notes.append("vtracer not installed (pip install vtracer) or hidden at rung 1; own region tracer used")
        if doc is None:
            sp = speckle if speckle is not None else (2.0 if kind == "photo" else 4.0)
            doc, info = trace_region(img, kind, used, tol or 0.6, speckle=sp, stack=stack, background=background,
                                     scans=scans)
    doc["notes"] = notes + doc.get("notes", [])
    return doc, info, used


def cmd_trace(a):
    t0 = time.time()
    img = Image.open(a.input)
    img.load()
    opts = json.loads(a.vt_opts) if a.vt_opts else None
    doc, info, used = trace(img, a.kind, a.backend, a.tolerance, opts, speckle=a.speckle, blur=a.blur or 0.0,
                            stack=a.stack, background=not a.no_background, scans=a.scans)
    out = V.write_out(core.out_for(a.input, a.output, f"trace-{a.kind}", ".svg"), V.to_svg(doc))
    r = {"command": "trace", "input": str(a.input), "output": str(out), "kind": a.kind, "rung": used.rung(),
         "tool": used.tool(), "used": used.items, "info": info, "seconds": round(time.time() - t0, 3)}
    if not a.no_check:
        chk = V.vcheck(V.read_svg(out), img, a.kind, info.get("cells"))
        r.update(overlap=chk.get("overlap"), counts=chk["counts"], structure=chk["structure"],
                 bar=chk.get("overlap_bar"), budget=chk.get("budget"), pass_=chk["pass"], fails=chk["fails"])
        r["pass"] = r.pop("pass_")
    r["notes"] = doc.get("notes", [])
    return r


def add_commands(sub, edit):
    p = sub.add_parser("trace", help="raster to vector SVG: --kind logo|icon|line|photo|pixel|centreline")
    p.add_argument("input")
    p.add_argument("-o", "--output", help="SVG path (never overwritten: name-NNN)")
    p.add_argument("--kind", choices=KINDS, default="logo")
    p.add_argument("--backend", choices=("auto", "vtracer", "vtracer1", "own", "potrace", "inkscape"), default="auto",
                   help="logo/icon/line/photo: auto = VTracer in a subprocess, else the own region tracer")
    p.add_argument("--tolerance", type=float, help="curve fit tolerance in px (own tracers)")
    p.add_argument("--vt-opts", help="JSON options passed to vtracer (run in its own process)")
    p.add_argument("--speckle", type=float, help="own tracer: drop closed loops under this area in px^2 "
                   "(default 4, photo 2)")
    p.add_argument("--blur", type=float, help="Gaussian pre-blur radius in px (halftone or screened prints)")
    p.add_argument("--stack", action="store_true", help="own tracer: each colour also covers the ones above it")
    p.add_argument("--no-background", action="store_true", help="own tracer: leave out the bottom (page) layer")
    p.add_argument("--scans", type=int, help="own tracer: exactly N brightness steps (grey levels) instead of colours")
    p.add_argument("--no-check", action="store_true", help="skip the render-back check")
    p.set_defaults(fn=cmd_trace)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "trace pixel": (1, "own pixel-exact tracer"),
    "trace logo/icon/line/photo": (2, "VTracer in a subprocess") if vtracer_ok() else (1, "own region tracer with holes"),
    "trace centreline": (2, "scikit-image skeletonize") if probe("skimage.morphology") else (1, "own Zhang-Suen thinning"),
    "trace --backend vtracer1": (2, "VTracer 1.x CLI") if find_vtracer1() else (0, "VTracer 1.x CLI not found (optional, alpha)"),
    "trace --backend potrace": (2, "potrace CLI") if find_potrace() else (0, "potrace not installed (optional, GPL)"),
    "trace --backend inkscape": (2, "Inkscape object-trace") if V.inkscape() else (0, "Inkscape not found (optional, GPL)"),
})
