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
from .transform import _reduce, bilinear, homography, load_others, multi, pts, remap

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


def gsolve(Z, logt, lam=50.0):
    """Debevec-Malik 1997 response recovery for one channel. Z: (N pixels, P frames) ints 0..255,
    logt: (P,) log exposure times. Returns g (256,) with g(Z) = ln E + ln t, g(128) = 0."""
    n, P = Z.shape
    w = np.minimum(np.arange(256), 255 - np.arange(256)).astype(np.float64) + 1.0
    rows = n * P + 1 + 254
    A = np.zeros((rows, 256 + n))
    b = np.zeros(rows)
    k = 0
    for i in range(n):
        for j in range(P):
            wij = w[Z[i, j]]
            A[k, Z[i, j]] = wij
            A[k, 256 + i] = -wij
            b[k] = wij * logt[j]
            k += 1
    A[k, 128] = 1.0
    k += 1
    for z in range(1, 255):
        A[k, z - 1], A[k, z], A[k, z + 1] = lam * w[z], -2 * lam * w[z], lam * w[z]
        k += 1
    x = np.linalg.lstsq(A, b, rcond=None)[0]
    g = x[:256]
    return np.maximum.accumulate(g)  # a response is monotonic; clamp solver wiggles in sparse bins


def sample_pixels(imgs, n=200, seed=0):
    """Pixel indices spread over the middle frame's brightness (stratified), for gsolve."""
    mid = imgs[len(imgs) // 2]
    v = np.round(mid.mean(axis=2) * 255).astype(int).ravel() if mid.ndim == 3 else np.round(mid * 255).astype(int).ravel()
    rng = np.random.default_rng(seed)
    picks = []
    bins = np.linspace(0, 256, n + 1)
    for lo, hi in zip(bins[:-1], bins[1:]):
        idx = np.flatnonzero((v >= lo) & (v < hi))
        if idx.size:
            picks.append(int(rng.choice(idx)))
    if len(picks) < 50:
        picks = list(rng.choice(v.size, size=min(v.size, n), replace=False))
    return np.asarray(sorted(set(picks)))


def recover_response(imgs, times, lam=50.0, n=200):
    """Per channel g curves (C, 256) from the brackets themselves."""
    logt = np.log(np.asarray(times, np.float64))
    idx = sample_pixels(imgs, n)
    C = imgs[0].shape[2]
    out = []
    for c in range(C):
        Z = np.stack([np.round(np.clip(im[..., c], 0, 1) * 255).astype(int).ravel()[idx] for im in imgs], 1)
        out.append(gsolve(Z, logt, lam))
    g = np.stack(out)
    return g - np.median(g[:, 128])  # one shared scale across channels keeps white neutral


def debevec_curve(imgs, times, g):
    """Radiance through recovered curves g (C, 256)."""
    num = np.zeros(imgs[0].shape, np.float64)
    den = np.zeros(imgs[0].shape, np.float64)
    wz = np.minimum(np.arange(256), 255 - np.arange(256)).astype(np.float64)
    order = np.argsort(times)
    for z, t in zip(imgs, times):
        Zi = np.round(np.clip(z, 0, 1) * 255).astype(int)
        lnE = np.stack([g[c][Zi[..., c]] for c in range(Zi.shape[2])], 2) - np.log(t)
        w = wz[Zi]
        num += w * lnE
        den += w
    short = np.round(np.clip(imgs[order[0]], 0, 1) * 255).astype(int)
    long_ = np.round(np.clip(imgs[order[-1]], 0, 1) * 255).astype(int)
    gs = np.stack([g[c][short[..., c]] for c in range(short.shape[2])], 2) - np.log(times[order[0]])
    gl = np.stack([g[c][long_[..., c]] for c in range(long_.shape[2])], 2) - np.log(times[order[-1]])
    fb = np.where(short > 127, gs, gl)
    lnE = np.where(den > 1e-6, num / np.maximum(den, 1e-12), fb)
    return np.exp(lnE).astype(np.float32)


def op_hdrmerge(img, p, used):
    imgs = load_others(p, img, used)
    times = [float(t) for t in p["exposures"]]
    if len(times) != len(imgs):
        raise ValueError(f"hdrmerge: {len(imgs)} images but {len(times)} exposure times")
    resp = p.get("response", "srgb")
    if resp == "srgb":
        rad = debevec(imgs, times)
        used.add("hdrmerge", 1, "own Debevec-Malik radiance merge (sRGB response)")
    else:
        if resp == "recover":
            g = recover_response(imgs, times, p.get("smooth", 50.0))
            used.add("hdrmerge", 1, "own Debevec-Malik merge with the camera response recovered (gsolve)")
            if p.get("response_out"):
                Path(p["response_out"]).write_text(json.dumps({"g": np.round(g, 6).tolist(),
                                                               "note": "ln exposure per 8-bit code, per channel"}))
        else:
            g = np.asarray(json.loads(Path(resp).read_text())["g"], np.float64)
            used.add("hdrmerge", 1, f"own Debevec-Malik merge with the response curve from {Path(resp).name}")
        if g.shape[0] != imgs[0].shape[2]:
            g = np.repeat(g[:1], imgs[0].shape[2], 0)
        rad = debevec_curve(imgs, times, g)
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


def warp_h(a, H, fill=0.0):
    """Sample a (HxW or HxWxC) at H @ [x, y, 1] for every output pixel (output = ref frame)."""
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    d = H[2, 0] * xx + H[2, 1] * yy + H[2, 2]
    X = (H[0, 0] * xx + H[0, 1] * yy + H[0, 2]) / d
    Y = (H[1, 0] * xx + H[1, 1] * yy + H[1, 2]) / d
    arr = a if a.ndim == 3 else a[..., None]
    out, inside = bilinear(arr.astype(np.float32), X.astype(np.float32), Y.astype(np.float32),
                           [fill] * arr.shape[2])
    return (out if a.ndim == 3 else out[..., 0]), inside, X, Y


def model_h(model, q):
    """3x3 from parameters: translation (tx,ty), rigid (th,tx,ty), similarity (a,b,tx,ty), homography (8)."""
    if model == "translation":
        return np.array([[1, 0, q[0]], [0, 1, q[1]], [0, 0, 1.0]])
    if model == "rigid":
        c, s_ = np.cos(q[0]), np.sin(q[0])
        return np.array([[c, -s_, q[1]], [s_, c, q[2]], [0, 0, 1.0]])
    if model == "similarity":
        return np.array([[q[0], -q[1], q[2]], [q[1], q[0], q[3]], [0, 0, 1.0]])
    return np.append(q, 1.0).reshape(3, 3)


def h_params(model, H):
    H = H / H[2, 2]
    if model == "translation":
        return np.array([H[0, 2], H[1, 2]])
    if model == "rigid":
        return np.array([np.arctan2(H[1, 0], H[0, 0]), H[0, 2], H[1, 2]])
    if model == "similarity":
        return np.array([(H[0, 0] + H[1, 1]) / 2, (H[1, 0] - H[0, 1]) / 2, H[0, 2], H[1, 2]])
    return H.ravel()[:8].copy()


def lk_refine(ref, mov, H, model, iters=40):
    """Gauss-Newton direct alignment (forward additive Lucas-Kanade) of mov onto ref."""
    gy, gx = np.gradient(mov)
    h, w = ref.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    q = h_params(model, H)
    k = q.size
    for _ in range(iters):
        Hq = model_h(model, q)
        m, inside, X, Y = warp_h(mov, Hq)
        if inside.mean() < 0.2:
            break
        ix = warp_h(gx, Hq)[0].astype(np.float64)
        iy = warp_h(gy, Hq)[0].astype(np.float64)
        d = Hq[2, 0] * xx + Hq[2, 1] * yy + 1.0
        z = 0 * xx
        dWu = np.stack([xx / d, yy / d, 1 / d, z, z, z, -X * xx / d, -X * yy / d], -1)
        dWv = np.stack([z, z, z, xx / d, yy / d, 1 / d, -Y * xx / d, -Y * yy / d], -1)
        dH = np.zeros((8, k))
        for i in range(k):  # numeric dH/dq, exact for the linear models
            e = np.zeros(k)
            e[i] = 1e-6
            dH[:, i] = ((model_h(model, q + e) - Hq).ravel()[:8]) / 1e-6
        J = (ix[..., None] * dWu + iy[..., None] * dWv) @ dH
        r = m.astype(np.float64) - ref
        Jm, rm = J[inside], r[inside]
        step = np.linalg.lstsq(Jm.T @ Jm + 1e-9 * np.eye(k), -Jm.T @ rm, rcond=None)[0]
        q = q + step
        if np.abs(step).max() < 1e-6:
            break
    Hq = model_h(model, q)
    m, inside, _, _ = warp_h(mov, Hq)
    return Hq, (float(np.abs(m - ref)[inside].mean()) if inside.mean() > 0.2 else 1e9)


def scale_h(H, s):
    S = np.diag([s, s, 1.0])
    return S @ H @ np.linalg.inv(S)


def log_polar_mag(g, nt=360):
    h, w = g.shape
    win = np.outer(np.hanning(h), np.hanning(w))
    F = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2((g - g.mean()) * win))))
    R = min(h, w) / 2.0
    nr = int(R)
    rho = np.exp(np.linspace(0, np.log(R), nr))
    th = np.linspace(0, np.pi, nt, endpoint=False)
    X = (w / 2 + rho[None, :] * np.cos(th[:, None])).astype(np.float32)
    Y = (h / 2 + rho[None, :] * np.sin(th[:, None])).astype(np.float32)
    out, _ = bilinear(F[..., None].astype(np.float32), X, Y, [0.0])
    return out[..., 0], np.log(R) / (nr - 1), np.pi / nt


def global_align(ref, mov, model):
    """H mapping ref pixel coords to mov pixel coords: Fourier-Mellin guesses, then pyramid LK."""
    h, w = ref.shape
    c = np.array([[1, 0, w / 2], [0, 1, h / 2], [0, 0, 1.0]])
    ci = np.linalg.inv(c)
    cands = [(0.0, 1.0)]
    if model != "translation":
        a, dr, dt = log_polar_mag(ref)
        b, _, _ = log_polar_mag(mov)
        dti, dri = phase_shift(a, b)
        th = dti * dt
        sc = float(np.exp(dri * dr)) if model != "rigid" else 1.0
        for t_ in (th, -th, th + np.pi, -th + np.pi):
            for s_ in ((sc, 1 / sc) if sc != 1.0 else (1.0,)):
                cands.append((t_, s_))
    levels = max(1, min(4, int(np.log2(min(h, w) / 32)) + 1))
    pr, pm = [ref], [mov]
    for _ in range(levels - 1):
        pr.append(_reduce(pr[-1]))
        pm.append(_reduce(pm[-1]))
    best = None
    for t_, s_ in cands:
        Rm = np.array([[s_ * np.cos(t_), -s_ * np.sin(t_), 0], [s_ * np.sin(t_), s_ * np.cos(t_), 0], [0, 0, 1.0]])
        Hc = c @ Rm @ ci
        m = warp_h(mov, Hc)[0]
        dy, dx = phase_shift(ref, m)
        Hl = scale_h(Hc @ np.array([[1, 0, -dx], [0, 1, -dy], [0, 0, 1.0]]), 0.5 ** (levels - 1))
        coarse = "similarity" if model == "homography" else model
        for lv in range(levels - 1, -1, -1):
            Hl, err = lk_refine(pr[lv], pm[lv], Hl, model if lv == 0 else coarse, iters=15 if lv else 40)
            if lv:
                Hl = scale_h(Hl, 2.0)
        if best is None or err < best[1]:
            best = (Hl, err)
    return best


def cmd_autoalign_h(a):
    t0 = time.time()
    used = core.Used()
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ref = core.load(a.inputs[0], used)
    g0 = (lum(to_lin(ref.color())) if ref.nc >= 3 else ref.color()[..., 0]).astype(np.float64)
    res = []
    for i, f in enumerate(a.inputs):
        im = core.load(f, used)
        g = (lum(to_lin(im.color())) if im.nc >= 3 else im.color()[..., 0]).astype(np.float64)
        if g.shape != g0.shape:
            raise SystemExit(f"autoalign: {f} differs in size from {a.inputs[0]}")
        H, err = (np.eye(3), 0.0) if i == 0 else global_align(g0, g, a.model)
        px = im.px if im.alpha else np.concatenate([im.px, np.ones(im.px.shape[:2] + (1,), np.float32)], 2)
        moved, inside, _, _ = warp_h(px, H)
        moved[~inside] = 0
        out = core.out_for(f, str(outdir / (Path(f).stem + "-aligned.png")), "aligned", ".png")
        core.save(im.copy(px=moved, alpha=True), out, None, used)
        res.append({"input": str(f), "output": str(out), "matrix": np.round(H / H[2, 2], 6).tolist(),
                    "residual": round(err, 5)})
    used.add("autoalign", 1, f"own Fourier-Mellin + pyramid Lucas-Kanade ({a.model})")
    return {"command": "autoalign", "model": a.model, "outputs": res, "seconds": round(time.time() - t0, 3),
            "rung": used.rung(), "tool": used.tool(), "used": used.items}


def cmd_autoalign(a):
    if getattr(a, "model", "translation") != "translation":
        return cmd_autoalign_h(a)
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
    if a.response != "srgb":
        p["response"] = a.response if a.response == "recover" else str(Path(a.response).resolve())
        p["smooth"] = a.smooth
    if a.response_out:
        p["response_out"] = str(Path(a.response_out).resolve())
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
    p.add_argument("--response", default="srgb",
                   help="camera response: srgb (assume the sRGB curve), recover (Debevec gsolve from the brackets) or a JSON file saved by --response-out")
    p.add_argument("--smooth", type=float, default=50.0, help="gsolve smoothness lambda")
    p.add_argument("--response-out", help="with --response recover: save the curves as JSON for reuse")
    p.add_argument("-o", "--output")
    p.add_argument("--recipe")
    p.add_argument("--bits", type=int, choices=(8, 16))
    p.set_defaults(fn=cmd_hdrmerge)
    p = sub.add_parser("autoalign", help="Auto-Align Layers: translate each image onto the first (rung 1)")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--outdir", required=True)
    p.add_argument("--model", choices=("translation", "rigid", "similarity", "homography"), default="translation",
                   help="translation = integer FFT shift (bit-exact); the others add rotation, scale, perspective")
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
