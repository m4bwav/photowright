"""Transform and merge: warp, perspective, upscale, stitch, stack.

Rungs:
  warp         1 own mesh/grid warp, bilinear sampling in linear light   | 2 OpenCV remap
  perspective  1 own 4-point homography (DLT) + bilinear sampling        | 2 OpenCV warpPerspective
  upscale      1 Lanczos in linear light (invents no detail)             | 3 Real-ESRGAN: stub only
  stitch       2 OpenCV Stitcher; rung 1 refuses (no own feature matcher and bundle adjuster)
  stack        1 own Laplacian pyramids: exposure fusion (Mertens 2007) and focus stacking
               2 OpenCV createMergeMertens on request
Seam carving (content-aware scale) is not here: Adobe patent flag, references/transform-merge.md s4.
"""
import time
from pathlib import Path

import numpy as np

from . import core
from .core import OPS, Used, load, probe, save, out_for, floats, to_lin, to_enc

ESRGAN_ROUTE = ("upscale --method realesrgan is rung 3 and not built: run Real-ESRGAN (BSD-3-Clause, "
                "https://github.com/xinntao/Real-ESRGAN) through comfyui-gen's ComfyUI upscale-model nodes; phw "
                "downloads nothing. A model invents detail: record the step with invented_detail: true (as for "
                "generative fill) and flag text and faces in its output. Rung 1 Lanczos invents none (invented_detail: false).")
STITCH_REFUSAL = ("stitch needs OpenCV (rung 2: pip install opencv-python). There is no rung 1 stitcher: feature "
                  "matching, bundle adjustment and seam finding are not rebuilt in photowright. Hugin (GPL) is the "
                  "free app route.")


# ---------------------------------------------------------------- sampling
def bilinear(arr, X, Y, fill):
    """Sample arr (HxWxC) at float coords X, Y; outside -> fill. Returns (out, inside mask)."""
    h, w = arr.shape[:2]
    inside = (X >= -0.5) & (Y >= -0.5) & (X <= w - 0.5) & (Y <= h - 0.5)
    Xc, Yc = np.clip(X, 0, w - 1), np.clip(Y, 0, h - 1)
    x0, y0 = np.floor(Xc).astype(np.int64), np.floor(Yc).astype(np.int64)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (Xc - x0)[..., None], (Yc - y0)[..., None]
    out = (arr[y0, x0] * (1 - fx) * (1 - fy) + arr[y0, x1] * fx * (1 - fy)
           + arr[y1, x0] * (1 - fx) * fy + arr[y1, x1] * fx * fy)
    out = np.where(inside[..., None], out, np.asarray(fill, np.float32))
    return out.astype(np.float32), inside


def shrink_map(X, Y):
    """Per output pixel, how many source pixels one output step spans (largest axis of the Jacobian)."""
    if X.shape[0] < 2 or X.shape[1] < 2:
        return np.ones(X.shape, np.float64)
    Xy, Xx = np.gradient(X)
    Yy, Yx = np.gradient(Y)
    return np.sqrt(np.maximum(Xx ** 2 + Yx ** 2, Xy ** 2 + Yy ** 2))


def mip_sample(arr, X, Y, f, s):
    """Prefiltered sampling: a Gaussian pyramid of arr, each output pixel read (bilinear) from the two
    levels around log2 of its local shrink and blended (trilinear mip-mapping)."""
    lev = np.clip(np.log2(np.maximum(s, 1.0)), 0, None)
    n = int(np.ceil(lev.max())) + 1
    n = max(1, min(n, int(np.log2(max(min(arr.shape[:2]), 1))) + 1))
    lev = np.minimum(lev, n - 1)
    pyr = gauss_pyr(arr, n)
    k0 = np.floor(lev).astype(np.int64)
    fr = (lev - k0)[..., None].astype(np.float32)
    out = np.zeros(X.shape + (arr.shape[2],), np.float32)
    inside = None
    for k in range(n):
        sel0, sel1 = k0 == k, (k0 + 1 == k) & (fr[..., 0] > 0)
        if not (sel0.any() or sel1.any()):
            continue
        sc = 2.0 ** k
        r, ins = bilinear(pyr[k], (X + 0.5) / sc - 0.5, (Y + 0.5) / sc - 0.5, f)
        if k == 0:
            inside = ins
        out += np.where(sel0[..., None], r * (1 - fr), 0) + np.where(sel1[..., None], r * fr, 0)
    if inside is None:
        inside = (X >= -0.5) & (Y >= -0.5) & (X <= arr.shape[1] - 0.5) & (Y <= arr.shape[0] - 0.5)
    return np.where(inside[..., None], out, np.asarray(f, np.float32)).astype(np.float32)


def remap(img, X, Y, used, op, fill=None, prefilter=False):
    """Resample img at X, Y in linear light (premultiplied when alpha). Outside: transparent when
    the image has alpha, else the fill colour (default black). prefilter: where the map shrinks the
    image by more than 2x, sample a Gaussian pyramid instead (inverse mapping alone aliases)."""
    col = to_lin(img.color())
    nc = col.shape[2]
    if img.alpha:
        a = img.px[..., -1:]
        arr = np.concatenate([col * a, a], axis=2)
        f = [0.0] * (nc + 1)
    else:
        arr = col
        f = to_lin(np.asarray(fill if fill is not None else [0.0] * nc, np.float32)).tolist()
    s = shrink_map(X, Y) if prefilter else None
    cv2 = probe("cv2")
    if s is not None and float(s.max()) > 2.0:
        r = mip_sample(arr, X, Y, f, s)
        used.add(op, 1, f"own mip-mapped sampling in linear light (prefiltered, max shrink {float(s.max()):.1f}x)")
    elif cv2 is not None and arr.shape[2] <= 4:
        r = cv2.remap(arr, X.astype(np.float32), Y.astype(np.float32), cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(f) + (0,) * (4 - len(f)))
        if r.ndim == 2:
            r = r[..., None]
        used.add(op, 2, "OpenCV remap (bilinear, linear light)")
    else:
        r, _ = bilinear(arr, X, Y, f)
        used.add(op, 1, "own bilinear sampling in linear light")
    if img.alpha:
        a2 = np.clip(r[..., -1:], 0, 1)
        c2 = np.where(a2 > 1e-6, r[..., :-1] / np.maximum(a2, 1e-6), 0)
        px = np.concatenate([to_enc(c2), a2], axis=2)
    else:
        px = to_enc(r)
    return img.copy(px=np.clip(px, 0, 1).astype(np.float32))


# ---------------------------------------------------------------- warp
def mesh_field(shape, grid, moves):
    """Displacement field from a (rows+1) x (cols+1) control grid, bilinear inside each cell."""
    h, w = shape
    cols, rows = grid
    D = np.zeros((rows + 1, cols + 1, 2), np.float64)
    for i, j, dx, dy in moves:
        D[int(j), int(i)] = (dx, dy)
    gx = np.linspace(0, cols, w) if w > 1 else np.zeros(1)
    gy = np.linspace(0, rows, h) if h > 1 else np.zeros(1)
    GX, GY = np.meshgrid(gx, gy)
    return bilinear(D.astype(np.float32), GX, GY, [0, 0])[0]


def op_warp(img, p, used):
    h, w = img.px.shape[:2]
    if not any(abs(m[2]) + abs(m[3]) > 0 for m in p.get("moves", [])):
        used.add("warp", 1, "identity (no control point moved)")
        return img.copy()
    D = mesh_field((h, w), p["grid"], p["moves"])
    yy, xx = np.mgrid[:h, :w].astype(np.float64)
    # backward map: the output pixel at p shows the source at p - D(p)
    return remap(img, xx - D[..., 0], yy - D[..., 1], used, "warp", p.get("fill"), p.get("prefilter", False))


# ---------------------------------------------------------------- perspective
def homography(src, dst):
    """3x3 H with dst ~ H src from 4 point pairs (direct linear transform, h33 = 1)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    A = np.asarray(A, np.float64)
    if abs(np.linalg.det(A)) < 1e-12:
        raise ValueError("perspective: the 4 points are degenerate (three on a line?)")
    hvec = np.linalg.solve(A, np.asarray(b, np.float64))
    return np.append(hvec, 1.0).reshape(3, 3)


def keystone_points(w, h, v=0.0, hz=0.0):
    """Correct converging lines: v > 0 means the top edge is narrower by v*w in the photo
    (camera tilted up); hz > 0 means the left edge is shorter by hz*h. Maps that quad to the frame."""
    dv, dh = abs(v) * w / 2, abs(hz) * h / 2
    src = [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]]  # TL TR BR BL
    if v > 0:      # top narrower
        src[0][0] += dv; src[1][0] -= dv
    elif v < 0:    # bottom narrower
        src[3][0] += dv; src[2][0] -= dv
    if hz > 0:     # left edge shorter
        src[0][1] += dh; src[3][1] -= dh
    elif hz < 0:   # right edge shorter
        src[1][1] += dh; src[2][1] -= dh
    dst = [[0, 0], [w, 0], [w, h], [0, h]]
    return src, dst


def op_perspective(img, p, used):
    h, w = img.px.shape[:2]
    src, dst = p["src"], p["dst"]
    H = homography(src, dst)
    ow, oh = p.get("size") or [w, h]
    Hi = np.linalg.inv(H)
    yy, xx = np.mgrid[:oh, :ow].astype(np.float64)
    den = Hi[2, 0] * xx + Hi[2, 1] * yy + Hi[2, 2]
    X = (Hi[0, 0] * xx + Hi[0, 1] * yy + Hi[0, 2]) / den
    Y = (Hi[1, 0] * xx + Hi[1, 1] * yy + Hi[1, 2]) / den
    p["homography"] = [[round(float(v), 9) for v in row] for row in H]
    return remap(img, X, Y, used, "perspective", p.get("fill"), p.get("prefilter", False))


# ---------------------------------------------------------------- upscale
def op_upscale(img, p, used):
    if p.get("method") == "realesrgan":
        raise SystemExit("upscale: " + ESRGAN_ROUTE)
    r = core.op_resize(img, {"width": p["width"], "height": p["height"], "filter": "lanczos"}, used)
    r.notes.append("Lanczos in linear light: no detail invented. A rung 3 model would invent detail; flag text and faces then.")
    p["invented_detail"] = False
    return r


# ---------------------------------------------------------------- pyramids (own, rung 1)
_K = np.array([1, 4, 6, 4, 1], np.float32) / 16


def _blur5(a):
    out = a
    for axis in (0, 1):
        pad = [(2, 2) if i == axis else (0, 0) for i in range(a.ndim)]
        pp = np.pad(out, pad, mode="reflect" if min(a.shape[:2]) > 2 else "edge")
        n = out.shape[axis]
        acc = np.zeros_like(out)
        for i, k in enumerate(_K):
            acc += k * (pp[i:i + n] if axis == 0 else pp[:, i:i + n])
        out = acc
    return out


def _reduce(a):
    return _blur5(a)[::2, ::2]


def _expand(a, shape):
    up = np.zeros(shape[:2] + a.shape[2:], np.float32)
    up[::2, ::2] = a
    return _blur5(up) * 4


def gauss_pyr(a, n):
    g = [a]
    for _ in range(n - 1):
        g.append(_reduce(g[-1]))
    return g


def lap_pyr(a, n):
    g = gauss_pyr(a, n)
    return [g[i] - _expand(g[i + 1], g[i].shape) for i in range(n - 1)] + [g[-1]]


def collapse(lp):
    a = lp[-1]
    for l in lp[-2::-1]:
        a = l + _expand(a, l.shape)
    return a


def levels_for(shape):
    return max(1, int(np.floor(np.log2(min(shape[:2])))) - 2)


def _laplacian_abs(gray):
    p = np.pad(gray, 1, mode="reflect")
    return np.abs(p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] - 4 * gray)


def mertens(images, wc=1.0, ws=1.0, we=1.0):
    """Exposure fusion (Mertens, Kautz, Van Reeth 2007) on encoded values 0..1."""
    W = []
    for im in images:
        gray = im.mean(axis=2)
        C = _laplacian_abs(gray)
        S = im.std(axis=2)
        E = np.prod(np.exp(-((im - 0.5) ** 2) / (2 * 0.2 ** 2)), axis=2)
        W.append((C ** wc) * (S ** ws) * (E ** we) + 1e-12)
    W = np.stack(W)
    W /= W.sum(axis=0)
    n = int(np.floor(np.log2(min(images[0].shape[:2])))) + 1   # full depth, as OpenCV
    acc = None
    for im, w in zip(images, W):
        gw = gauss_pyr(w[..., None].astype(np.float32), n)
        li = lap_pyr(im.astype(np.float32), n)
        part = [g * l for g, l in zip(gw, li)]
        acc = part if acc is None else [a + b for a, b in zip(acc, part)]
    return np.clip(collapse(acc), 0, 1)


def focus_stack(images):
    """Focus stacking: per pyramid level keep the coefficient with the largest magnitude (summed
    over channels); the low-pass top level is averaged."""
    n = levels_for(images[0].shape)
    pyrs = [lap_pyr(im.astype(np.float32), n) for im in images]
    out = []
    for lev in range(n):
        stack = np.stack([pp[lev] for pp in pyrs])
        if lev == n - 1:
            out.append(stack.mean(axis=0))
            continue
        e = np.abs(stack).sum(axis=-1)
        e = np.stack([_blur5(x) for x in e])   # smooth the choice a little: fewer speckles
        k = e.argmax(axis=0)
        out.append(np.take_along_axis(stack, k[None, ..., None], axis=0)[0])
    return np.clip(collapse(out), 0, 1)


def load_others(p, img, used):
    imgs = [img.color()]
    for f in p["others"]:
        o = load(f, used)
        if o.px.shape[:2] != img.px.shape[:2] or o.nc != img.nc:
            raise ValueError(f"stack: {f} is {o.px.shape[1]}x{o.px.shape[0]}x{o.nc}, the first is "
                             f"{img.px.shape[1]}x{img.px.shape[0]}x{img.nc}; align and crop them first")
        imgs.append(o.color())
    return imgs


def op_stack(img, p, used):
    imgs = load_others(p, img, used)
    mode = p.get("mode", "exposure")
    if mode == "exposure":
        if p.get("method") == "opencv":
            cv2 = probe("cv2")
            if cv2 is None:
                raise SystemExit("stack --method opencv needs OpenCV (rung 2); --method own is rung 1")
            u8 = [np.ascontiguousarray(np.round(i * 255).astype(np.uint8)[..., ::-1]) for i in imgs]
            r = cv2.createMergeMertens().process(u8)[..., ::-1]
            used.add("stack.exposure", 2, "OpenCV MergeMertens")
            return img.with_color(np.clip(r, 0, 1).astype(np.float32))
        used.add("stack.exposure", 1, "own Mertens exposure fusion (Laplacian pyramid)")
        img.notes.append("inputs are assumed aligned (tripod or aligned beforehand)")
        return img.with_color(mertens(imgs).astype(np.float32))
    if mode == "median":
        used.add("stack.median", 1, "NumPy per-pixel median (clean plate)")
        img.notes.append("inputs are assumed aligned; the median keeps what most frames agree on")
        return img.with_color(np.median(np.stack(imgs), axis=0).astype(np.float32))
    if mode == "focus":
        used.add("stack.focus", 1, "own Laplacian-pyramid focus stack (max coefficient)")
        img.notes.append("inputs are assumed aligned and of equal magnification")
        return img.with_color(focus_stack(imgs).astype(np.float32))
    raise ValueError(f"stack: unknown mode {mode}")


def op_stitch(img, p, used):
    cv2 = probe("cv2")
    if cv2 is None:
        raise SystemExit("stitch: " + STITCH_REFUSAL)
    imgs = [img.color()] + [load(f, used).color() for f in p["others"]]
    u8 = [np.ascontiguousarray(np.round(np.clip(i[..., :3], 0, 1) * 255).astype(np.uint8)[..., ::-1]) for i in imgs]
    mode = cv2.Stitcher_SCANS if p.get("mode") == "scans" else cv2.Stitcher_PANORAMA
    st = cv2.Stitcher_create(mode)
    try:
        status, pano = st.stitch(u8)
    except cv2.error as e:  # OpenCV 5.0 can assert inside the estimator on some inputs
        raise RuntimeError(f"stitch: OpenCV Stitcher raised {str(e).strip().splitlines()[-1]}; try the other --mode")
    if status != 0:
        names = {1: "not enough overlap or features", 2: "homography estimation failed",
                 3: "camera parameter adjustment failed"}
        raise RuntimeError(f"stitch: OpenCV Stitcher status {status} ({names.get(status, 'error')}); "
                           "try --mode scans for flat subjects, or more overlap (30% or more)")
    used.add("stitch", 2, f"OpenCV Stitcher ({'SCANS' if mode == cv2.Stitcher_SCANS else 'PANORAMA'})")
    c = pano[..., ::-1].astype(np.float32) / 255.0
    out = core.Img(c, False, img.icc, img.exif, img.xmp, 8, img.fmt, img.notes)
    return out


OPS["warp"] = op_warp
OPS["perspective"] = op_perspective
OPS["upscale"] = op_upscale
OPS["stack"] = op_stack
OPS["stitch"] = op_stitch


# ---------------------------------------------------------------- commands
def one_step(a, tag, p):
    t0 = time.time()
    used = Used()
    img = load(a.input, used)
    step = {"op": tag, "params": p}
    res = OPS[tag](img, p, used)
    out = out_for(a.input, a.output, tag)
    save(res, out, getattr(a, "bits", None), used)
    if a.recipe:
        core.record(a.recipe, a.input, [step], out, used, time.time() - t0)
    return {"command": tag, "input": str(a.input), "output": str(out), "rung": used.rung(), "tool": used.tool(),
            "used": used.items, "steps": [step], "notes": res.notes,
            "size": [int(res.px.shape[1]), int(res.px.shape[0])]}


def pts(s):
    v = [floats(q, 2) for q in s.split()]
    if len(v) != 4:
        raise SystemExit("give exactly 4 points 'x,y x,y x,y x,y' (top-left, top-right, bottom-right, bottom-left)")
    return v


def cmd_warp(a):
    cols, rows = (int(v) for v in floats(a.grid, 2))
    moves = [floats(m, 4) for m in (a.move or "").replace(";", " ").split()] if a.move else []
    for m in moves:
        if not (0 <= m[0] <= cols and 0 <= m[1] <= rows):
            raise SystemExit(f"warp: control point {int(m[0])},{int(m[1])} is outside the {cols}x{rows} grid")
    p = {"grid": [cols, rows], "moves": moves, "prefilter": not a.no_prefilter}
    if a.fill:
        p["fill"] = floats(a.fill)
    return one_step(a, "warp", p)


def cmd_perspective(a):
    from PIL import Image, ImageOps
    with Image.open(a.input) as im:
        w, h = ImageOps.exif_transpose(im).size
    if a.keystone:
        v, hz = (floats(a.keystone, (1, 2)) + [0.0])[:2]
        src, dst = keystone_points(w, h, v, hz)
    elif a.src:
        src = pts(a.src)
        dst = pts(a.dst) if a.dst else [[0, 0], [w, 0], [w, h], [0, h]]
    else:
        raise SystemExit("perspective: give --src (and --dst) 4 points, or --keystone v[,h]")
    p = {"src": src, "dst": dst, "prefilter": not a.no_prefilter}
    if a.size:
        p["size"] = [int(v) for v in floats(a.size, 2)]
    if a.fill:
        p["fill"] = floats(a.fill)
    return one_step(a, "perspective", p)


def cmd_upscale(a):
    if a.method == "realesrgan":
        raise SystemExit("upscale: " + ESRGAN_ROUTE)
    from PIL import Image, ImageOps
    with Image.open(a.input) as im:
        w, h = ImageOps.exif_transpose(im).size
    if a.width:
        nw = a.width
        nh = a.height or max(1, round(h * a.width / w))
    else:
        nw, nh = max(1, round(w * a.scale)), max(1, round(h * a.scale))
    return one_step(a, "upscale", {"width": nw, "height": nh, "method": "lanczos", "invented_detail": False})


def multi(a, tag, p):
    a.input, others = a.inputs[0], a.inputs[1:]
    if not others:
        raise SystemExit(f"{tag}: give two or more images")
    p["others"] = [str(Path(f).resolve()) for f in others]
    return one_step(a, tag, p)


def cmd_stack(a):
    return multi(a, "stack", {"mode": a.mode, "method": a.method})


def cmd_stitch(a):
    if probe("cv2") is None:
        raise SystemExit("stitch: " + STITCH_REFUSAL)
    return multi(a, "stitch", {"mode": a.mode})


def add_commands(sub, edit):
    p = edit("warp", cmd_warp, "mesh warp: move control points of a grid")
    p.add_argument("--grid", default="4,4", help="cols,rows cells (control points are (cols+1)x(rows+1))")
    p.add_argument("--move", help="'i,j,dx,dy; ...' move control point (column i, row j) by dx,dy px")
    p.add_argument("--fill", help="r,g,b 0..1 for uncovered areas (images without alpha)")
    p.add_argument("--no-prefilter", action="store_true", help="plain inverse mapping even where the image shrinks >2x")
    p = edit("perspective", cmd_perspective, "4-point perspective (homography) or keystone correction")
    p.add_argument("--src", help="'x,y x,y x,y x,y' corners in the photo (TL TR BR BL)")
    p.add_argument("--dst", help="where they go (default: the image frame)")
    p.add_argument("--keystone", help="v[,h]: v>0 = top edge narrower by v x width (camera tilted up)")
    p.add_argument("--size", help="W,H of the output (default: the input size)")
    p.add_argument("--fill", help="r,g,b 0..1 for uncovered areas (images without alpha)")
    p.add_argument("--no-prefilter", action="store_true", help="plain inverse mapping even where the image shrinks >2x")
    p = edit("upscale", cmd_upscale, "upscale: Lanczos in linear light (rung 1); Real-ESRGAN stub (rung 3)")
    p.add_argument("--scale", type=float, default=2.0)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--method", choices=("lanczos", "realesrgan"), default="lanczos")
    for name, fn, help_ in (("stack", cmd_stack, "exposure fusion (Mertens) or focus stack of aligned images"),
                            ("stitch", cmd_stitch, "panorama stitch (OpenCV, rung 2; rung 1 refuses)")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("inputs", nargs="+")
        p.add_argument("-o", "--output", help="output path (never overwritten: name-NNN)")
        p.add_argument("--recipe", help="append the step to this recipe.json and log the run")
        p.add_argument("--bits", type=int, choices=(8, 16))
        p.set_defaults(fn=fn)
        if name == "stack":
            p.add_argument("--mode", choices=("exposure", "focus", "median"), default="exposure")
            p.add_argument("--method", choices=("own", "opencv"), default="own")
        else:
            p.add_argument("--mode", choices=("panorama", "scans"), default="panorama")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "warp, perspective": (2, "OpenCV remap") if probe("cv2") else (1, "own bilinear sampling"),
    "upscale": (1, "Lanczos in linear light"),
    "upscale --method realesrgan": (3, "not built: comfyui-gen route documented"),
    "stitch": (2, "OpenCV Stitcher") if probe("cv2") else (0, "refused at rung 1 (needs OpenCV)"),
    "stack (exposure, focus)": (1, "own Laplacian pyramids"),
})
