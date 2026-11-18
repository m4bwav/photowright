"""Retouch: heal, clone, fill (content-aware), remove, restore.

Every op here changes only the pixels of its region; the rest come back bit-identical (the
result is composited through a hard mask at the end). Rungs:
  heal   1 own Poisson (gradient-domain) solver, conjugate gradients in NumPy  | 2 OpenCV seamlessClone
  clone  1 copy from an offset, optional own Poisson blend
  fill   1 own multi-scale PatchMatch exemplar fill (Barnes et al. 2009, Wexler et al. 2007)
         1 own membrane (Laplace) fill for thin regions | 2 OpenCV inpaint Telea/NS | 3 LaMa (big-lama) via ComfyUI, falls back
  remove = region (mask or shape, grown) + fill
  restore red eye, dust and scratches (median-threshold), old-photo pass (scratch detect + fill + denoise)
Seam carving (content-aware scale) is left out on purpose: Adobe patent flag, see references/transform-merge.md s4.
"""
import time
from pathlib import Path

import numpy as np

from . import core
from .core import OPS, Used, load, probe, save, out_for, floats
from .masks import draw_shape, morph, read_mask

# ---------------------------------------------------------------- region
def region_mask(p, shape, base_dir=None):
    """Boolean hole from params: region (mask PNG path) and/or rect/ellipse/polygon, then grow px."""
    h, w = shape
    m = np.zeros((h, w), np.float32)
    if p.get("region"):
        f = Path(p["region"])
        if base_dir and not f.is_absolute():
            f = Path(base_dir) / f
        m = np.maximum(m, read_mask(f, (h, w)))
    for kind in ("rect", "ellipse"):
        if p.get(kind):
            m = np.maximum(m, draw_shape((h, w), kind, {"box": p[kind]}))
    if p.get("polygon"):
        m = np.maximum(m, draw_shape((h, w), "polygon", {"points": p["polygon"]}))
    hole = m > 0.5
    if p.get("grow"):
        hole = morph(hole.astype(np.float32), float(p["grow"]), True) > 0.5
    if not hole.any():
        raise ValueError("the region is empty: give --mask or --rect/--ellipse/--polygon")
    if hole.all():
        raise ValueError("the region covers the whole image: nothing to sample from")
    return hole


def composite(img, new_color, hole):
    """Only hole pixels take the new colour; every other pixel is the original, bit for bit."""
    c = img.color()
    out = np.where(hole[..., None], np.clip(new_color, 0, 1).astype(np.float32), c)
    return img.with_color(out)


def seam_score(color, hole, ring=4):
    """Mean |step| across the region border against mean |step| between neighbours just outside.
    ratio near 1 = no visible seam. Returns dict (border, around, ratio)."""
    lum = color.mean(axis=2) if color.ndim == 3 else color
    b, a = [], []
    outside_ring = (morph(hole.astype(np.float32), ring + 1, True) > 0.5) & ~hole
    for dy, dx in ((0, 1), (1, 0)):
        p = lum[:lum.shape[0] - dy, :lum.shape[1] - dx]
        q = lum[dy:, dx:]
        hp = hole[:hole.shape[0] - dy, :hole.shape[1] - dx]
        hq = hole[dy:, dx:]
        rp = outside_ring[:hole.shape[0] - dy, :hole.shape[1] - dx]
        rq = outside_ring[dy:, dx:]
        d = np.abs(p - q)
        b.append(d[hp != hq])
        a.append(d[rp & rq])
    b, a = np.concatenate(b), np.concatenate(a)
    bm, am = float(b.mean()) if b.size else 0.0, float(a.mean()) if a.size else 0.0
    return {"border": round(bm, 5), "around": round(am, 5), "ratio": round(bm / am, 3) if am > 1e-9 else None}


# ---------------------------------------------------------------- Poisson (rung 1)
def _shift(a, dy, dx, fill=0):
    """out[y, x] = a[y+dy, x+dx], fill outside."""
    out = np.full_like(a, fill)
    h, w = a.shape[:2]
    ys, yd = (slice(dy, h), slice(0, h - dy)) if dy >= 0 else (slice(0, h + dy), slice(-dy, h))
    xs, xd = (slice(dx, w), slice(0, w - dx)) if dx >= 0 else (slice(0, w + dx), slice(-dx, w))
    out[yd, xd] = a[ys, xs]
    return out


DIRS = ((0, 1), (0, -1), (1, 0), (-1, 0))


def poisson_solve(target, guide, hole, mixed=False, iters=3000, tol=1e-5):
    """Gradient-domain blend (Perez et al. 2003): inside `hole` find f with the gradients of
    `guide` (or the stronger of guide/target per edge when mixed) and f = target on the border.
    Discrete Poisson equation solved by conjugate gradients, one channel at a time.
    guide=None gives the membrane (Laplace) fill: smooth interpolation of the border."""
    h, w, nc = target.shape
    inside = hole.astype(np.float64)
    valid = [_shift(np.ones((h, w)), dy, dx) for dy, dx in DIRS]
    nb_in = [_shift(inside, dy, dx) for dy, dx in DIRS]
    deg = sum(valid)
    out = target.astype(np.float64).copy()
    stats = []
    for c in range(nc):
        t = target[..., c].astype(np.float64)
        g = guide[..., c].astype(np.float64) if guide is not None else None
        b = np.zeros((h, w))
        for k, (dy, dx) in enumerate(DIRS):
            tq = _shift(t, dy, dx)
            b += valid[k] * (1 - nb_in[k]) * tq          # known border neighbours
            if g is not None:
                v = g - _shift(g, dy, dx)
                if mixed:
                    vt = t - tq
                    v = np.where(np.abs(vt) > np.abs(v), vt, v)
                b += valid[k] * v
        b *= inside

        def A(x):
            r = deg * x
            for k, (dy, dx) in enumerate(DIRS):
                r -= valid[k] * nb_in[k] * _shift(x, dy, dx)
            return r * inside

        if g is not None:  # warm start: guide moved to the border's mean level
            ring = (morph(hole.astype(np.float32), 1, True) > 0.5) & ~hole
            x = (g + (t[ring].mean() - g[ring].mean() if ring.any() else 0.0)) * inside
        else:
            x = np.full((h, w), t[~hole].mean()) * inside
        r = b - A(x)
        p = r.copy()
        rs = float((r * r).sum())
        b2 = max(float((b * b).sum()), 1e-20)
        n = 0
        while n < iters and rs / b2 > tol * tol:
            Ap = A(p)
            alpha = rs / max(float((p * Ap).sum()), 1e-30)
            x += alpha * p
            r -= alpha * Ap
            rs_new = float((r * r).sum())
            p = r + (rs_new / rs) * p
            rs = rs_new
            n += 1
        out[..., c] = np.where(hole, x, t)
        stats.append(n)
    return out.astype(np.float32), stats


# ---------------------------------------------------------------- source search for heal
def auto_offset(color, hole, used=None):
    """Pick the source offset whose surroundings best match the hole's surroundings."""
    h, w = hole.shape
    ys, xs = np.nonzero(hole)
    bh, bw = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
    ring = (morph(hole.astype(np.float32), 3, True) > 0.5) & ~hole
    keep = morph(hole.astype(np.float32), 4, True) > 0.5
    ry, rx = np.nonzero(ring)
    best = None
    step = max(bh, bw) + 4
    for k in (1, 1.5, 2, 3):
        for ay, ax in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            dy, dx = int(round(ay * step * k)), int(round(ax * step * k))
            sy, sx = ys + dy, xs + dx
            if sy.min() < 0 or sx.min() < 0 or sy.max() >= h or sx.max() >= w:
                continue
            if keep[sy, sx].any():
                continue
            qy, qx = ry + dy, rx + dx
            ok = (qy >= 0) & (qx >= 0) & (qy < h) & (qx < w)
            if ok.mean() < 0.9:
                continue
            d = float(((color[ry[ok], rx[ok]] - color[qy[ok], qx[ok]]) ** 2).mean())
            if best is None or d < best[0]:
                best = (d, dy, dx)
    if best is None:
        raise ValueError("heal: no clean source area of the region's size fits in the image; give --offset dx,dy")
    return best[2], best[1]


def shifted_source(color, dx, dy):
    """src[y, x] = color[y+dy, x+dx] (edge-clamped)."""
    h, w = color.shape[:2]
    yy = np.clip(np.arange(h) + dy, 0, h - 1)
    xx = np.clip(np.arange(w) + dx, 0, w - 1)
    return color[yy][:, xx]


def op_heal(img, p, used):
    c = img.color()
    hole = region_mask(p, c.shape[:2])
    if p.get("offset"):
        dx, dy = (int(v) for v in p["offset"])
    else:
        dx, dy = auto_offset(c, hole, used)
        p["offset"] = [dx, dy]
    src = shifted_source(c, dx, dy)
    method = p.get("method", "auto")
    cv2 = probe("cv2") if method in ("auto", "opencv") else None
    if method == "opencv" and cv2 is None:
        raise SystemExit("heal --method opencv needs OpenCV (rung 2); --method poisson is rung 1")
    # seamlessClone treats the mask's own edge oddly (a full-box mask changes almost nothing), so it
    # gets the region grown by 3 px and the result is composited back through the exact region
    big = morph(hole.astype(np.float32), 3, True) > 0.5
    if cv2 is not None and c.shape[2] == 3 and not big[[0, -1], :].any() and not big[:, [0, -1]].any():
        ys, xs = np.nonzero(big)
        cy, cx = ys.min() + (ys.max() - ys.min() + 1) // 2, xs.min() + (xs.max() - xs.min() + 1) // 2
        u8 = lambda a: np.ascontiguousarray(np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)[..., ::-1])
        m8 = (big * 255).astype(np.uint8)
        try:
            r = cv2.seamlessClone(u8(src), u8(c), m8, (int(cx), int(cy)),
                                  cv2.MIXED_CLONE if p.get("mixed") else cv2.NORMAL_CLONE)
            used.add("heal", 2, "OpenCV seamlessClone")
            if img.bits > 8:
                img.notes.append("seamlessClone ran on 8-bit data")
            return composite(img, r[..., ::-1].astype(np.float32) / 255.0, hole)
        except Exception as e:  # odd masks: fall back to rung 1
            img.notes.append(f"seamlessClone failed ({e.__class__.__name__}); used the own solver")
    res, its = poisson_solve(c, src, hole, bool(p.get("mixed")))
    used.add("heal", 1, f"own Poisson CG ({max(its)} iterations)")
    return composite(img, res, hole)


def op_clone(img, p, used):
    c = img.color()
    hole = region_mask(p, c.shape[:2])
    dx, dy = (int(v) for v in p["offset"])
    src = shifted_source(c, dx, dy)
    if p.get("poisson"):
        res, its = poisson_solve(c, src, hole, bool(p.get("mixed")))
        used.add("clone", 1, f"copy + own Poisson CG ({max(its)} iterations)")
        return composite(img, res, hole)
    used.add("clone", 1, "NumPy copy from offset")
    return composite(img, src, hole)


# ---------------------------------------------------------------- PatchMatch fill (rung 1)
def _down(a):
    h, w = a.shape[:2]
    h2, w2 = (h + 1) // 2, (w + 1) // 2
    pad = [(0, h2 * 2 - h), (0, w2 * 2 - w)] + [(0, 0)] * (a.ndim - 2)
    a = np.pad(a, pad, mode="edge")
    return a.reshape(h2, 2, w2, 2, *a.shape[2:])


def _pyramid(color, hole, r, min_side):
    imgs, holes = [color], [hole]
    while True:
        c, hl = imgs[-1], holes[-1]
        if min(c.shape[:2]) // 2 < min_side:
            break
        ys, xs = np.nonzero(hl)
        if max(ys.max() - ys.min(), xs.max() - xs.min()) + 1 <= 2 * r + 1:
            break
        known = (~hl).astype(np.float32)
        kb = _down(known[..., None])
        cb = _down(c * known[..., None])
        ksum = kb.sum(axis=(1, 3))
        nc = cb.sum(axis=(1, 3)) / np.maximum(ksum, 1e-6)
        nh = _down(hl).any(axis=(1, 3))
        if nh.all():
            break
        imgs.append(nc.astype(np.float32))
        holes.append(nh)
    return imgs, holes


def _patch_offsets(r):
    return [(dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1)]


def _pdist(P, ty, tx, sy, sx, offs, r):
    d = np.zeros(ty.shape, np.float32)
    for dy, dx in offs:
        e = P[ty + dy + r, tx + dx + r] - P[sy + dy + r, sx + dx + r]
        d += (e * e).sum(-1)
    return d


def patchmatch_fill(color, hole, patch=7, seed=0, em_iters=(6, 3), pm_iters=4, notes=None):
    """Multi-scale exemplar completion: at each level, PatchMatch finds for every patch touching
    the hole its nearest known patch (random init, propagation, random search), then each hole
    pixel becomes the weighted vote of the overlapping patches; repeat, upsample, refine."""
    rng = np.random.default_rng(seed)
    r = patch // 2
    offs = _patch_offsets(r)
    imgs, holes = _pyramid(color, hole, r, 4 * r + 2)
    L = len(imgs) - 1
    I = None
    nnf = None
    for lev in range(L, -1, -1):
        orig, hl = imgs[lev], holes[lev]
        h, w = hl.shape
        if I is None:
            I, _ = poisson_solve(orig, None, hl)             # coarsest: membrane start
        else:
            up = np.repeat(np.repeat(I, 2, 0), 2, 1)[:h, :w]
            I = np.where(hl[..., None], up, orig).astype(np.float32)
        # valid source centres: patch fully known and inside
        bad = morph(hl.astype(np.float32), r, True) > 0.5
        valid = ~bad
        valid[:r] = valid[-r:] = False
        valid[:, :r] = valid[:, -r:] = False
        if not valid.any():
            raise ValueError("fill: the region leaves no whole known patch to copy from (shrink the region or --patch)")
        vy, vx = np.nonzero(valid)
        tmask = morph(hl.astype(np.float32), r, True) > 0.5
        ty, tx = np.nonzero(tmask)
        n = ty.size
        NY = np.zeros((h, w), np.int64)
        NX = np.zeros((h, w), np.int64)
        if nnf is not None:
            py, px = nnf
            cy = np.clip(2 * py[ty // 2, tx // 2] + ty % 2, 0, h - 1)
            cx = np.clip(2 * px[ty // 2, tx // 2] + tx % 2, 0, w - 1)
            ok = valid[cy, cx]
            k = rng.integers(0, vy.size, n)
            NY[ty, tx] = np.where(ok, cy, vy[k])
            NX[ty, tx] = np.where(ok, cx, vx[k])
        else:
            k = rng.integers(0, vy.size, n)
            NY[ty, tx], NX[ty, tx] = vy[k], vx[k]
        for em in range(em_iters[0] if lev == L else em_iters[1]):
            P = np.pad(I, ((r, r), (r, r), (0, 0)), mode="reflect")
            sy, sx = NY[ty, tx], NX[ty, tx]
            D = _pdist(P, ty, tx, sy, sx, offs, r)

            def consider(cy, cx):
                nonlocal sy, sx, D
                ok = (cy >= 0) & (cx >= 0) & (cy < h) & (cx < w)
                cy, cx = np.where(ok, cy, 0), np.where(ok, cx, 0)
                ok &= valid[cy, cx]
                if not ok.any():
                    return
                d = np.full(n, np.inf, np.float32)
                d[ok] = _pdist(P, ty[ok], tx[ok], cy[ok], cx[ok], offs, r)
                better = d < D
                sy, sx, D = np.where(better, cy, sy), np.where(better, cx, sx), np.where(better, d, D)

            for it in range(pm_iters):
                NY[ty, tx], NX[ty, tx] = sy, sx
                for dy, dx in (DIRS if it % 2 == 0 else DIRS[::-1]):
                    qy, qx = np.clip(ty + dy, 0, h - 1), np.clip(tx + dx, 0, w - 1)
                    inT = tmask[qy, qx]
                    cy = np.where(inT, NY[qy, qx] - dy, -1)
                    cx = np.where(inT, NX[qy, qx] - dx, -1)
                    consider(cy, cx)
                    NY[ty, tx], NX[ty, tx] = sy, sx
                rad = max(h, w)
                while rad >= 1:
                    consider(sy + rng.integers(-rad, rad + 1, n), sx + rng.integers(-rad, rad + 1, n))
                    rad //= 2
                k = rng.integers(0, vy.size, n)   # a few fresh random guesses keep it from sticking
                consider(vy[k], vx[k])
            NY[ty, tx], NX[ty, tx] = sy, sx
            # vote
            sig2 = float(np.median(D)) + 1e-6
            wgt = np.exp(-D / (2 * sig2)).astype(np.float32)
            acc = np.zeros((h * w, I.shape[2]), np.float64)
            ws = np.zeros(h * w, np.float64)
            for dy, dx in offs:
                py, px = ty + dy, tx + dx
                ok = (py >= 0) & (px >= 0) & (py < h) & (px < w)
                ok &= hl[np.clip(py, 0, h - 1), np.clip(px, 0, w - 1)]
                if not ok.any():
                    continue
                idx = py[ok] * w + px[ok]
                vals = I[sy[ok] + dy, sx[ok] + dx]
                ww = wgt[ok]
                ws += np.bincount(idx, ww, h * w)
                for ch in range(I.shape[2]):
                    acc[:, ch] += np.bincount(idx, ww * vals[:, ch], h * w)
            filled = (acc / np.maximum(ws, 1e-12)[:, None]).reshape(h, w, -1)
            I = np.where((hl & (ws.reshape(h, w) > 0))[..., None], filled, I).astype(np.float32)
        nnf = (NY, NX)
    # finest level: copy each hole pixel from its own patch's match instead of the blurred vote,
    # so noise and grain keep their statistics (votes average them away)
    hy, hx = np.nonzero(hole)
    I[hy, hx] = I[NY[hy, hx], NX[hy, hx]]
    if notes is not None:
        notes.append(f"PatchMatch fill: {L + 1} pyramid levels, patch {patch}, seed {seed}")
    return I


def is_thin(hole, r=2):
    """True when the region vanishes under an erosion by r px: scratches, wires, specks."""
    return not (morph(hole.astype(np.float32), r, False) > 0.5).any()


def fill_color(img, c, hole, p, used):
    method = p.get("method", "auto")
    if method == "lama":
        from . import comfy
        try:
            rgb = c[..., :3] if c.shape[2] >= 3 else np.repeat(c, 3, axis=2)
            res, info = comfy.lama_fill(rgb, hole, int(p.get("seed", 0)))
            used.add("fill", 3, f"ComfyUI LaMa ({info['model']})")
            p.update(model=info["model"], seed=info["seed"])
            img.notes.append(f"rung 3 LaMa via {info['server']}: {info['seconds']} s, {info['queued_ahead']} jobs ahead")
            if c.shape[2] == 1:
                res = res.mean(axis=2, keepdims=True)
            elif c.shape[2] > 3:
                res = np.concatenate([res, c[..., 3:]], axis=2)
            return res.astype(np.float32)
        except comfy.Unavailable as e:
            img.notes.append(f"fell back: {e}")
            p["fell_back"] = str(e)
            method = "auto"
    if method == "auto":
        method = "thin" if is_thin(hole) else "patch"
    if method in ("thin", "telea", "ns"):
        cv2 = probe("cv2")
        if cv2 is not None:
            flag = cv2.INPAINT_NS if method == "ns" else cv2.INPAINT_TELEA
            u8 = np.round(np.clip(c, 0, 1) * 255).astype(np.uint8)
            m8 = (hole * 255).astype(np.uint8)
            r = cv2.inpaint(np.ascontiguousarray(u8), m8, float(p.get("radius", 3)), flag)
            if r.ndim == 2:
                r = r[..., None]
            used.add("fill", 2, f"OpenCV inpaint {'NS' if method == 'ns' else 'Telea'}")
            return r.astype(np.float32) / 255.0
        if method in ("telea", "ns"):
            raise SystemExit(f"fill --method {method} needs OpenCV (rung 2); --method membrane or patch is rung 1")
        method = "membrane"
    if method == "membrane":
        res, its = poisson_solve(c, None, hole)
        used.add("fill", 1, f"own membrane (Laplace) fill, CG {max(its)} iterations")
        return res
    if method == "patch":
        res = patchmatch_fill(c, hole, int(p.get("patch", 7)), int(p.get("seed", 0)), notes=img.notes)
        used.add("fill", 1, "own multi-scale PatchMatch exemplar fill")
        return res
    raise ValueError(f"fill: unknown method {method}")


def op_fill(img, p, used):
    c = img.color()
    hole = region_mask(p, c.shape[:2])
    return composite(img, fill_color(img, c, hole, p, used), hole)


OPS["heal"] = op_heal
OPS["clone"] = op_clone
OPS["fill"] = op_fill
OPS["remove"] = op_fill   # remove = a grown region + fill; the step records the grow


# ---------------------------------------------------------------- restore
def _median(ch, r):
    nd = probe("scipy.ndimage")
    if nd is not None:
        return nd.median_filter(ch, size=2 * r + 1, mode="reflect")
    return core.median_filter(ch, r)


def redeye_fix(c, box, thr=1.5):
    x, y, bw, bh = (int(v) for v in box)
    sub = c[y:y + bh, x:x + bw]
    rr, gg, bb = sub[..., 0], sub[..., 1], sub[..., 2]
    red = (rr > thr * (gg + bb) / 2) & (rr > 0.25)
    out = c.copy()
    fixed = sub.copy()
    fixed[..., 0] = np.where(red, (gg + bb) / 2, rr)
    out[y:y + bh, x:x + bw] = fixed
    hole = np.zeros(c.shape[:2], bool)
    hole[y:y + bh, x:x + bw] = red
    return out, hole


def dust_mask(c, radius, threshold):
    lum = c.mean(axis=2)
    med = _median(lum, radius)
    return np.abs(lum - med) > threshold


def op_restore(img, p, used):
    c = img.color()
    out = c.copy()
    changed = np.zeros(c.shape[:2], bool)
    report = {}
    limit = region_mask(p, c.shape[:2]) if any(p.get(k) for k in ("region", "rect", "ellipse", "polygon")) else None
    for box in p.get("redeye") or []:
        if c.shape[2] < 3:
            raise ValueError("restore --redeye needs a colour image")
        out, hl = redeye_fix(out, box, float(p.get("redeye_threshold", 1.5)))
        changed |= hl
        used.add("restore.redeye", 1, "NumPy redness threshold")
    report["redeye_px"] = int(changed.sum())
    if p.get("dust"):
        r, t = int(p.get("radius", 2)), float(p.get("threshold", 0.12))
        dm = dust_mask(out, r, t)
        if limit is not None:
            dm &= limit
        med = np.stack([_median(out[..., i], r) for i in range(out.shape[2])], axis=2)
        out = np.where(dm[..., None], med, out)
        changed |= dm
        report["dust_px"] = int(dm.sum())
        used.add("restore.dust", 1 if probe("scipy.ndimage") is None else 2,
                 "median-threshold (dust and scratches)")
    if p.get("old_photo"):
        r, t = int(p.get("radius", 3)), float(p.get("threshold", 0.1))
        sm = dust_mask(out, r, t)
        if limit is not None:
            sm &= limit
        if sm.any():
            sm = morph(sm.astype(np.float32), 1, True) > 0.5
            if limit is not None:
                sm &= limit
            if not sm.all():
                out = np.where(sm[..., None], fill_color(img, out, sm, {"method": "thin"}, used), out)
        changed |= sm
        report["scratch_px"] = int(sm.sum())
        dn = float(p.get("denoise", 1))
        if dn > 0:
            den = core.op_denoise(img.with_color(out), {"method": "auto", "strength": 6 * dn, "radius": 1}, used)
            out = den.color()
            changed |= limit if limit is not None else np.ones(c.shape[:2], bool)
            report["denoised"] = True
    img.notes.append("restore: " + ", ".join(f"{k} {v}" for k, v in report.items()))
    return composite(img, out, changed)


OPS["restore"] = op_restore


# ---------------------------------------------------------------- commands
def region_params(a):
    p = {}
    if getattr(a, "mask", None):
        p["region"] = str(Path(a.mask).resolve())
    if getattr(a, "rect", None):
        p["rect"] = [float(v) for v in floats(a.rect, 4)]
    if getattr(a, "ellipse", None):
        p["ellipse"] = [float(v) for v in floats(a.ellipse, 4)]
    if getattr(a, "polygon", None):
        p["polygon"] = [floats(q, 2) for q in a.polygon.split()]
    if getattr(a, "grow", None):
        p["grow"] = a.grow
    return p


def region_command(a, tag, p):
    t0 = time.time()
    used = Used()
    img = load(a.input, used)
    step = {"op": tag, "params": p}
    res = OPS[tag](img, step["params"], used)   # the op may fill in chosen values (heal offset)
    out = out_for(a.input, a.output, tag)
    save(res, out, getattr(a, "bits", None), used)
    if a.recipe:
        core.record(a.recipe, a.input, [step], out, used, time.time() - t0)
    r = {"command": tag, "input": str(a.input), "output": str(out), "rung": used.rung(), "tool": used.tool(),
         "used": used.items, "steps": [step], "notes": res.notes}
    if tag != "restore":
        hole = region_mask(p, img.px.shape[:2])
        r["region_px"] = int(hole.sum())
        r["seam"] = seam_score(res.color(), hole)
    return r


def cmd_heal(a):
    p = region_params(a)
    p["method"] = a.method
    if a.offset:
        p["offset"] = [int(v) for v in floats(a.offset, 2)]
    if a.mixed:
        p["mixed"] = True
    return region_command(a, "heal", p)


def cmd_clone(a):
    p = region_params(a)
    p["offset"] = [int(v) for v in floats(a.offset, 2)]
    if a.poisson:
        p["poisson"] = True
    if a.mixed:
        p["mixed"] = True
    return region_command(a, "clone", p)


def cmd_fill(a, tag="fill"):
    p = region_params(a)
    p.update(method=a.method, patch=a.patch, seed=a.seed, radius=a.radius)
    return region_command(a, tag, p)


def cmd_remove(a):
    if a.grow is None:
        a.grow = 2.0
    return cmd_fill(a, "remove")


def cmd_restore(a):
    p = region_params(a)
    if a.redeye:
        p["redeye"] = [[float(v) for v in floats(b, 4)] for b in a.redeye]
    if a.dust:
        p["dust"] = True
    if a.old_photo:
        p["old_photo"] = True
        p["denoise"] = a.denoise
    if a.radius is not None:
        p["radius"] = a.radius
    if a.threshold is not None:
        p["threshold"] = a.threshold
    if not (a.redeye or a.dust or a.old_photo):
        raise SystemExit("restore: give --redeye x,y,w,h and/or --dust and/or --old-photo")
    return region_command(a, "restore", p)


def add_commands(sub, edit):
    def region_flags(p, required=True):
        p.add_argument("--mask", help="region mask PNG (white = region)")
        p.add_argument("--rect", help="x,y,w,h region")
        p.add_argument("--ellipse", help="x,y,w,h region bounding box")
        p.add_argument("--polygon", help="'x,y x,y x,y ...' region")
        p.add_argument("--grow", type=float, help="grow the region by N px first")

    p = edit("heal", cmd_heal, "spot heal: texture from nearby, colour from the border (Poisson)")
    region_flags(p)
    p.add_argument("--offset", help="dx,dy of the source area (default: best matching nearby area)")
    p.add_argument("--method", choices=("auto", "poisson", "opencv"), default="auto",
                   help="auto: OpenCV seamlessClone (rung 2) else own Poisson (rung 1)")
    p.add_argument("--mixed", action="store_true", help="mixed gradients: keep the stronger edge")
    p = edit("clone", cmd_clone, "clone stamp: copy from an offset into the region, optional Poisson blend")
    region_flags(p)
    p.add_argument("--offset", required=True, help="dx,dy of the source relative to the region")
    p.add_argument("--poisson", action="store_true", help="blend the copy in the gradient domain")
    p.add_argument("--mixed", action="store_true")
    for name, fn, help_ in (("fill", cmd_fill, "content-aware fill of a region"),
                            ("remove", cmd_remove, "remove an object: region grown 2 px, then content-aware fill")):
        p = edit(name, fn, help_)
        region_flags(p)
        p.add_argument("--method", "--model", dest="method",
                       choices=("auto", "patch", "membrane", "telea", "ns", "lama"), default="auto",
                       help="lama: rung 3 via the local ComfyUI (falls back to auto); auto: thin regions telea (rung 2) or membrane, else patch (own PatchMatch, rung 1)")
        p.add_argument("--patch", type=int, default=7, help="patch size for --method patch (odd)")
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--radius", type=float, default=3, help="inpaint radius for telea/ns")
    p = edit("restore", cmd_restore, "red eye, dust and scratches, old-photo pass")
    region_flags(p)
    p.add_argument("--redeye", action="append", help="x,y,w,h box around an eye (repeat)")
    p.add_argument("--dust", action="store_true", help="median-threshold dust and scratches filter")
    p.add_argument("--old-photo", action="store_true", help="scratch detection + fill, then denoise")
    p.add_argument("--radius", type=int, help="median radius (dust 2, old-photo 3)")
    p.add_argument("--threshold", type=float, help="luminance difference that counts as a defect (0..1)")
    p.add_argument("--denoise", type=float, default=1.0, help="old-photo denoise strength (0 = off)")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "heal": (2, "OpenCV seamlessClone") if probe("cv2") else (1, "own Poisson CG"),
    "clone": (1, "NumPy copy (+ own Poisson)"),
    "fill/remove (areas)": (1, "own multi-scale PatchMatch"),
    "fill (thin regions)": (2, "OpenCV inpaint Telea") if probe("cv2") else (1, "own membrane fill"),
    "fill --method lama": (3, "ComfyUI inpaint-nodes + big-lama.pt (falls back)"),
    "restore (red eye, dust, old photo)": (1, "NumPy median-threshold + fill"),
    "content-aware scale (seam carving)": (0, "left out: Adobe patent flag (references/transform-merge.md s4)"),
})
