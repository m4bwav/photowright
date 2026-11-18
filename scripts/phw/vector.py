"""Vector side: one internal model, SVG read/write, render-back, curve fitting, vcheck, simplify, export.

Model: a document is {"width", "height", "shapes"}; a shape is {"fill": (r,g,b)|None, "stroke": (r,g,b)|None,
"width": float, "rule": "evenodd"|"nonzero", "subs": [sub]}; a sub is {"start": (x,y), "segs": [("L", p) |
("C", c1, c2, p)], "closed": bool}. Coordinates are pixels, y down.

Rungs:
  render-back  1 own winding-number scanline fill at 16x supersampling (both fill rules, strokes as
               unions of quads and discs), grown from the bake-off rasterizer (ai-docs/notes/bakeoff)
  fitting      1 own: corners by turning angle, least-squares cubic Bezier fit with Newton
               reparameterization (Schneider, Graphics Gems 1990, from the paper's description)
  export       1 own writers: plain SVG subset, PDF 1.4, EPS 3.0, DXF R12 POLYLINE (cutter-safe)
  inkscape     2 external (GPL, never bundled): opens exports to prove them, optional trace backend
"""
import math
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

from . import core
from .core import free_path, rung_max

TOL = 24            # overlap: max channel difference counted as a match (bake-off value)
SS = 16             # render-back supersampling
NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

# Bars and budgets per kind: 2x the bake-off VTracer counts on its 256x256 images, scaled by
# sqrt(area / 256^2). Nodes are path commands (M, L, C) recounted with this parser: results.md's regex
# also matched letters inside attribute names, so it read 109/137/734/13553 for 56/93/522/9372.
# Pixel: 2x the own pixel-exact count (338 nodes for 16x16 cells) per cell.
BARS = {"logo": 0.97, "icon": 0.97, "line": 0.94, "photo": 0.80, "pixel": 0.999, "centreline": None}
BUDGET = {"logo": (112, 12, 12), "icon": (186, 10, 10), "line": (1044, 74, 64),
          "photo": (18744, 1560, 1558), "centreline": (2000, 400, 8)}
PIXEL_NODES_PER_CELL = 676 / 256


# ---------------------------------------------------------------- SVG read
def parse_color(s):
    s = (s or "").strip().lower()
    if not s or s == "none" or s.startswith("url("):
        return None
    named = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0),
             "blue": (0, 0, 255), "yellow": (255, 255, 0), "gray": (128, 128, 128), "grey": (128, 128, 128)}
    if s in named:
        return named[s]
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r"rgb\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)", s)
    return tuple(int(v) for v in m.groups()) if m else (0, 0, 0)


def parse_transform(s):
    M = np.eye(3)
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.findall(NUM, args)]
        T = np.eye(3)
        if name == "translate":
            T[0, 2], T[1, 2] = v[0], (v[1] if len(v) > 1 else 0)
        elif name == "scale":
            T[0, 0], T[1, 1] = v[0], (v[1] if len(v) > 1 else v[0])
        elif name == "matrix":
            T[:2] = np.array(v[:6]).reshape(3, 2).T
        elif name == "rotate":
            a = math.radians(v[0])
            R = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
            if len(v) == 3:
                A, B = np.eye(3), np.eye(3)
                A[:2, 2], B[:2, 2] = v[1:], [-v[1], -v[2]]
                R = A @ R @ B
            T = R
        M = M @ T
    return M


def arc_cubics(p0, rx, ry, phi, large, sweep, p1):
    """SVG elliptical arc (endpoint form, SVG 1.1 F.6) as cubic segments, at most 90 degrees each."""
    if np.allclose(p0, p1):
        return []
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-12 or ry < 1e-12:
        return [("L", p1)]
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / (rx * rx * y1 * y1 + ry * ry * x1 * x1)))
    if bool(large) == bool(sweep):
        k = -k
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    cx, cy = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2, s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2
    t1 = math.atan2((y1 - cy1) / ry, (x1 - cx1) / rx)
    t2 = math.atan2((-y1 - cy1) / ry, (-x1 - cx1) / rx)
    dt = t2 - t1
    if sweep and dt < 0:
        dt += 2 * math.pi
    elif not sweep and dt > 0:
        dt -= 2 * math.pi
    n = max(1, math.ceil(abs(dt) / (math.pi / 2) - 1e-9))
    h = dt / n
    al = 4 / 3 * math.tan(h / 4)

    def pt(t):
        x, y = rx * math.cos(t), ry * math.sin(t)
        return (c * x - s * y + cx, s * x + c * y + cy)

    def dv(t):
        x, y = -rx * math.sin(t), ry * math.cos(t)
        return (c * x - s * y, s * x + c * y)

    out = []
    for j in range(n):
        a, b = t1 + j * h, t1 + (j + 1) * h
        pa, pb, da, db = pt(a), pt(b), dv(a), dv(b)
        end = p1 if j == n - 1 else pb
        out.append(("C", (pa[0] + al * da[0], pa[1] + al * da[1]), (pb[0] - al * db[0], pb[1] - al * db[1]), end))
    return out


def parse_d(d):
    """Path data to subs (absolute, cubic only): implicit repeats, H/V, S/T reflections, arcs as cubics.
    The second value counts arcs (0.22.0: converted exactly to cubics, no longer read as lines)."""
    toks = re.findall(r"[MmLlHhVvCcSsQqTtZzAa]|" + NUM, d or "")
    subs, cur, start, sub, i, cmd, lastc, lastq, arcs = [], (0.0, 0.0), (0.0, 0.0), None, 0, None, None, None, 0

    def nums(k):
        nonlocal i
        v = [float(t) for t in toks[i:i + k]]
        if len(v) < k:
            raise ValueError("path data ends early")
        i += k
        return v

    def seg(s):
        nonlocal sub
        if sub is None or sub["closed"]:
            sub = {"start": cur, "segs": [], "closed": False}
            subs.append(sub)
        sub["segs"].append(s)

    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if sub is not None:
                    sub["closed"] = True
                cur, lastc, lastq = start, None, None
                continue
        elif cmd is None:
            raise ValueError("path data must start with M")
        c, rel = cmd.upper(), cmd.islower()
        ox, oy = cur if rel else (0.0, 0.0)
        pc, pq = lastc, lastq
        lastc = lastq = None
        if c == "M":
            x, y = nums(2)
            cur = start = (x + ox, y + oy)
            sub = {"start": cur, "segs": [], "closed": False}
            subs.append(sub)
            cmd = "l" if rel else "L"
        elif c in "LHV":
            if c == "L":
                x, y = nums(2)
                p = (x + ox, y + oy)
            elif c == "H":
                p = (nums(1)[0] + ox, cur[1])
            else:
                p = (cur[0], nums(1)[0] + oy)
            seg(("L", p))
            cur = p
        elif c in "CS":
            if c == "C":
                v = nums(6)
                c1 = (v[0] + ox, v[1] + oy)
                v = v[2:]
            else:
                v = nums(4)
                c1 = (2 * cur[0] - pc[0], 2 * cur[1] - pc[1]) if pc else cur
            c2, p = (v[0] + ox, v[1] + oy), (v[2] + ox, v[3] + oy)
            seg(("C", c1, c2, p))
            cur, lastc = p, c2
        elif c in "QT":
            if c == "Q":
                v = nums(4)
                q = (v[0] + ox, v[1] + oy)
                v = v[2:]
            else:
                v = nums(2)
                q = (2 * cur[0] - pq[0], 2 * cur[1] - pq[1]) if pq else cur
            p = (v[0] + ox, v[1] + oy)
            c1 = (cur[0] + 2 / 3 * (q[0] - cur[0]), cur[1] + 2 / 3 * (q[1] - cur[1]))
            c2 = (p[0] + 2 / 3 * (q[0] - p[0]), p[1] + 2 / 3 * (q[1] - p[1]))
            seg(("C", c1, c2, p))
            cur, lastq = p, q
        elif c == "A":
            v = nums(7)
            p = (v[5] + ox, v[6] + oy)
            for g in arc_cubics(cur, v[0], v[1], v[2], v[3], v[4], p):
                seg(g)
            cur = p
            arcs += 1
    return subs, arcs


def transform_subs(subs, M):
    if np.allclose(M, np.eye(3)):
        return subs

    def tp(p):
        return (M[0, 0] * p[0] + M[0, 1] * p[1] + M[0, 2], M[1, 0] * p[0] + M[1, 1] * p[1] + M[1, 2])
    return [{"start": tp(s["start"]), "closed": s["closed"],
             "segs": [(g[0],) + tuple(tp(p) for p in g[1:]) for g in s["segs"]]} for s in subs]


def ellipse_subs(cx, cy, rx, ry):
    k = 0.5522847498
    P = [(cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry)]
    T = [(0, ry), (-rx, 0), (0, -ry), (rx, 0)]
    segs = []
    for j in range(4):
        a, b = P[j], P[(j + 1) % 4]
        ta, tb = T[j], T[(j + 1) % 4]
        segs.append(("C", (a[0] + k * ta[0], a[1] + k * ta[1]), (b[0] - k * tb[0], b[1] - k * tb[1]), b))
    return [{"start": P[0], "segs": segs, "closed": True}]


def _len(v):
    m = re.match(r"\s*(" + NUM + r")\s*(px|mm|cm|in|pt)?", v or "")
    if not m:
        return None
    f = {"px": 1, None: 1, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96, "pt": 96 / 72}[m.group(2)]
    return float(m.group(1)) * f


def parse_svg(text):
    if "<!ENTITY" in text:
        raise ValueError("SVG with XML entities refused")
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    vb = [float(x) for x in re.findall(NUM, root.get("viewBox", ""))]
    W, H = (vb[2], vb[3]) if len(vb) == 4 else (_len(root.get("width")) or 0, _len(root.get("height")) or 0)
    base = np.eye(3)
    if len(vb) == 4:
        base[:2, 2] = [-vb[0], -vb[1]]
    doc = {"width": W, "height": H, "shapes": [], "notes": []}
    skipped = {}

    def attrs(el, inh):
        a = dict(inh)
        for k in ("fill", "stroke", "stroke-width", "fill-rule", "fill-opacity"):
            if el.get(k) is not None:
                a[k] = el.get(k)
        for kv in (el.get("style") or "").split(";"):
            if ":" in kv:
                k, v = kv.split(":", 1)
                if k.strip() in ("fill", "stroke", "stroke-width", "fill-rule", "fill-opacity"):
                    a[k.strip()] = v.strip()
        return a

    def walk(el, inh, M):
        tag = el.tag.split("}")[-1]
        if tag in ("defs", "clipPath", "mask", "metadata", "title", "desc", "style", "pattern", "symbol"):
            return
        a = attrs(el, inh)
        M = M @ parse_transform(el.get("transform"))
        if tag in ("svg", "g", "a"):
            for ch in el:
                walk(ch, a, M)
            return
        subs, arcs = [], 0
        if tag == "path":
            subs, arcs = parse_d(el.get("d"))
        elif tag == "rect":
            x, y, w, h = (float(el.get(k, 0) or 0) for k in ("x", "y", "width", "height"))
            subs = [{"start": (x, y), "segs": [("L", (x + w, y)), ("L", (x + w, y + h)), ("L", (x, y + h))],
                     "closed": True}]
        elif tag in ("polygon", "polyline"):
            v = [float(t) for t in re.findall(NUM, el.get("points", ""))]
            pts = list(zip(v[0::2], v[1::2]))
            if pts:
                subs = [{"start": pts[0], "segs": [("L", p) for p in pts[1:]], "closed": tag == "polygon"}]
        elif tag in ("circle", "ellipse"):
            cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
            rx = float(el.get("r") or el.get("rx") or 0)
            ry = float(el.get("r") or el.get("ry") or 0)
            subs = ellipse_subs(cx, cy, rx, ry)
        elif tag == "line":
            subs = [{"start": (float(el.get("x1", 0)), float(el.get("y1", 0))),
                     "segs": [("L", (float(el.get("x2", 0)), float(el.get("y2", 0))))], "closed": False}]
        else:
            skipped[tag] = skipped.get(tag, 0) + 1
            return
        if el.get("clip-path") or "clip-path" in (el.get("style") or ""):
            doc["notes"].append(f"{tag}: clip-path ignored (drawn unclipped; no polygon boolean at rung 1)")
        fill = parse_color(a.get("fill", "#000000"))
        stroke = parse_color(a.get("stroke"))
        if tag in ("polyline", "line"):
            fill = None if "fill" not in a else fill
        if not subs or (fill is None and stroke is None):
            return
        scale = math.sqrt(abs(np.linalg.det(M[:2, :2]))) or 1.0
        doc["shapes"].append({"fill": fill, "stroke": stroke, "width": (_len(a.get("stroke-width")) or 1.0) * scale,
                              "rule": "evenodd" if a.get("fill-rule") == "evenodd" else "nonzero",
                              "subs": transform_subs(subs, M)})
        fo = float(a.get("fill-opacity", 1))
        if fill is not None and fo < 1:
            doc["shapes"][-1]["opacity"] = max(0.0, fo)

    walk(root, {}, base)
    if skipped:
        doc["notes"].append("ignored elements: " + ", ".join(f"{k} x{v}" for k, v in sorted(skipped.items())))
    return doc


def read_svg(path):
    return parse_svg(Path(path).read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------- SVG write (plain subset)
def fnum(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def hexc(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c)


def path_d(subs):
    out = []
    for s in subs:
        out.append(f"M{fnum(s['start'][0])} {fnum(s['start'][1])}")
        for g in s["segs"]:
            out.append(g[0] + " ".join(f"{fnum(p[0])} {fnum(p[1])}" for p in g[1:]))
        if s["closed"]:
            out.append("Z")
    return "".join(out)


def to_svg(doc, units=None, dpi=96.0):
    W, H = doc["width"], doc["height"]
    if units in ("mm", "in"):
        # physical size, and a viewBox in the same unit (1 user unit = 1 mm or 1 in): coordinates are scaled
        k = (25.4 if units == "mm" else 1.0) / dpi
        size = f'width="{fnum(W * k)}{units}" height="{fnum(H * k)}{units}"'
        M = np.diag([k, k, 1.0])
        doc = dict(doc, shapes=[dict(sh, subs=transform_subs(sh["subs"], M), width=sh["width"] * k)
                                for sh in doc["shapes"]])
        W, H = W * k, H * k
    else:
        size = f'width="{fnum(W)}" height="{fnum(H)}"'
    body = []
    for sh in doc["shapes"]:
        a = f'fill="{hexc(sh["fill"])}"' if sh["fill"] else 'fill="none"'
        if sh["fill"] and sh["rule"] == "evenodd":
            a += ' fill-rule="evenodd"'
        if sh["fill"] and sh.get("opacity", 1) < 1:
            a += f' fill-opacity="{sh["opacity"]:.4g}"'
        if sh["stroke"]:
            a += (f' stroke="{hexc(sh["stroke"])}" stroke-width="{fnum(sh["width"])}"'
                  ' stroke-linecap="round" stroke-linejoin="round"')
        body.append(f'<path d="{path_d(sh["subs"])}" {a}/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" {size} viewBox="0 0 {fnum(W)} {fnum(H)}">\n'
            + "\n".join(body) + "\n</svg>\n")


# ---------------------------------------------------------------- geometry
def cubic_pts(p0, c1, c2, p3, n):
    t = np.linspace(0, 1, n + 1)[1:, None]
    p0, c1, c2, p3 = (np.asarray(v, float) for v in (p0, c1, c2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * p3


def flatten(sub, per_px=1.5, nmax=200):
    pts = [np.asarray([sub["start"]], float)]
    cur = sub["start"]
    for g in sub["segs"]:
        if g[0] == "L":
            pts.append(np.asarray([g[1]], float))
        else:
            ln = math.dist(cur, g[1]) + math.dist(g[1], g[2]) + math.dist(g[2], g[3])
            pts.append(cubic_pts(cur, g[1], g[2], g[3], int(min(nmax, max(4, math.ceil(ln / per_px))))))
        cur = g[-1]
    return np.concatenate(pts)


def signed_area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def stroke_polys(P, w, closed):
    """A stroke as same-orientation pieces (quads per segment, discs per joint) for a nonzero union."""
    r = max(w, 0.5) / 2
    if closed:
        P = np.vstack([P, P[:1]])
    polys = []
    ang = np.linspace(0, 2 * np.pi, 13)[:-1]
    disc = np.stack([np.cos(ang), np.sin(ang)], 1) * r
    for a, b in zip(P[:-1], P[1:]):
        d = b - a
        n = np.hypot(*d)
        if n < 1e-9:
            continue
        nv = np.array([-d[1], d[0]]) / n * r
        polys.append(np.array([a + nv, b + nv, b - nv, a - nv]))
    polys += [p + disc for p in P]
    return [q if signed_area(q) > 0 else q[::-1] for q in polys]


# ---------------------------------------------------------------- render-back
def coverage(polys, X0, Y0, Wd, Ht, rule, S):
    """Winding-number fill of polygons (pixel units) on an S-times supersampled box."""
    E = []
    for P in polys:
        Q = np.asarray(P, float) * S
        if len(Q) < 3:
            continue
        E.append(np.hstack([Q, np.roll(Q, -1, axis=0)]))
    if not E:
        return np.zeros((Ht, Wd), bool)
    E = np.vstack(E)
    x0, y0, x1, y1 = E.T
    keep = y0 != y1
    x0, y0, x1, y1 = x0[keep], y0[keep], x1[keep], y1[keep]
    d = np.where(y1 > y0, 1, -1)
    lo, hi = np.minimum(y0, y1), np.maximum(y0, y1)
    r0 = np.maximum(np.ceil(lo - 0.5).astype(np.int64), Y0)
    r1 = np.minimum(np.ceil(hi - 0.5).astype(np.int64), Y0 + Ht)
    cnt = np.maximum(r1 - r0, 0)
    tot = int(cnt.sum())
    if tot == 0:
        return np.zeros((Ht, Wd), bool)
    idx = np.repeat(np.arange(len(cnt)), cnt)
    rows = r0[idx] + (np.arange(tot) - np.repeat(np.cumsum(cnt) - cnt, cnt))
    t = (rows + 0.5 - y0[idx]) / (y1[idx] - y0[idx])
    xc = x0[idx] + t * (x1[idx] - x0[idx])
    col = np.clip(np.ceil(xc - 0.5).astype(np.int64), X0, X0 + Wd) - X0
    flat = (rows - Y0) * (Wd + 1) + col
    acc = np.bincount(flat, weights=d[idx], minlength=Ht * (Wd + 1)).reshape(Ht, Wd + 1)
    wn = np.rint(np.cumsum(acc[:, :Wd], axis=1)).astype(np.int64)
    return (wn % 2 == 1) if rule == "evenodd" else (wn != 0)


def render(doc, w=None, h=None, S=None, bg=(255, 255, 255)):
    """Render a document at w x h pixels (default: its own size), supersampled S times, area-averaged."""
    W, H = doc["width"] or 1, doc["height"] or 1
    w = int(round(w or W))
    h = int(round(h or H))
    if S is None:
        S = max(1, min(SS, int(math.sqrt(64e6 / max(w * h, 1)))))
    sx, sy = w / W, h / H
    can = np.empty((h * S, w * S, 3), np.uint8)
    can[:] = bg
    for sh in doc["shapes"]:
        flat = [flatten(s) * [sx, sy] for s in sh["subs"]]
        jobs = []
        if sh["fill"]:
            jobs.append(([P for P in flat if len(P) >= 3], sh["rule"], sh["fill"], float(sh.get("opacity", 1))))
        if sh["stroke"]:
            sp = []
            for P, s in zip(flat, sh["subs"]):
                sp += stroke_polys(P, sh["width"] * math.sqrt(sx * sy), s["closed"])
            jobs.append((sp, "nonzero", sh["stroke"], 1.0))
        for polys, rule, col, op in jobs:
            if not polys:
                continue
            allp = np.vstack(polys) * S
            X0 = int(max(0, math.floor(allp[:, 0].min())))
            Y0 = int(max(0, math.floor(allp[:, 1].min())))
            X1 = int(min(w * S, math.ceil(allp[:, 0].max()) + 1))
            Y1 = int(min(h * S, math.ceil(allp[:, 1].max()) + 1))
            if X1 <= X0 or Y1 <= Y0:
                continue
            m = coverage(polys, X0, Y0, X1 - X0, Y1 - Y0, rule, S)
            if op >= 1:
                can[Y0:Y1, X0:X1][m] = col
            else:
                sub = can[Y0:Y1, X0:X1]
                sub[m] = np.rint(sub[m] * (1 - op) + np.asarray(col, float) * op).astype(np.uint8)
    out = can.reshape(h, S, w, S, 3).mean(axis=(1, 3))
    return np.rint(out).astype(np.uint8)


def source_rgb(path_or_img):
    im = path_or_img if isinstance(path_or_img, Image.Image) else Image.open(path_or_img)
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    return np.asarray(Image.alpha_composite(bg, im).convert("RGB"))


def aliased_palette(src, kmax=16):
    """The exact colours of a hard-edged source (no anti-aliasing): <= kmax colours, else None."""
    key = (src[..., 0].astype(np.int64) << 16) | (src[..., 1].astype(np.int64) << 8) | src[..., 2]
    vals = np.unique(key)
    if len(vals) > kmax:
        return None
    return np.stack([(vals >> 16) & 255, (vals >> 8) & 255, vals & 255], 1).astype(np.int64)


def snap_to(ren, pal):
    """Each rendered pixel to the nearest palette colour (an aliased render of the same vector)."""
    d = ((ren.astype(np.int64)[..., None, :] - pal[None, None]) ** 2).sum(-1)
    return pal[np.argmin(d, -1)].astype(np.uint8)


def overlap(src, ren, tol=TOL):
    return float((np.abs(src.astype(int) - ren.astype(int)).max(axis=2) <= tol).mean())


# ---------------------------------------------------------------- counts and checks
def counts(doc):
    nodes = sum(1 + len(s["segs"]) for sh in doc["shapes"] for s in sh["subs"])
    cols = {c for sh in doc["shapes"] for c in (sh["fill"], sh["stroke"]) if c}
    return {"paths": len(doc["shapes"]), "subpaths": sum(len(sh["subs"]) for sh in doc["shapes"]),
            "nodes": nodes, "colours": len(cols)}


def self_crossings(P, limit=1):
    """Proper crossings between edges of one closed polygon (touching at a vertex does not count)."""
    A, B = P, np.roll(P, -1, axis=0)
    n, found = len(P), []
    if n < 4:
        return found
    for i0 in range(0, n, 256):
        a, b = A[i0:i0 + 256, None], B[i0:i0 + 256, None]
        c, d = A[None], B[None]

        def cr(o, p, q):
            return (p[..., 0] - o[..., 0]) * (q[..., 1] - o[..., 1]) - (p[..., 1] - o[..., 1]) * (q[..., 0] - o[..., 0])
        d1, d2, d3, d4 = cr(a, b, c), cr(a, b, d), cr(c, d, a), cr(c, d, b)
        eps = 1e-7
        hit = (d1 * d2 < -eps) & (d3 * d4 < -eps)
        ii, jj = np.nonzero(hit)
        for i, j in zip(ii + i0, jj):
            if j > i:
                found.append((round(float(A[i, 0]), 2), round(float(A[i, 1]), 2)))
                if len(found) >= limit:
                    return found
    return found


def structure(doc):
    open_, stray, cross, at = 0, 0, 0, []
    for sh in doc["shapes"]:
        for s in sh["subs"]:
            P = flatten(s, per_px=3.0, nmax=16)
            if sh["fill"] and not sh["stroke"]:
                geo_closed = len(P) > 2 and np.allclose(P[0], P[-1])
                if not s["closed"] and not geo_closed:
                    open_ += 1
                if geo_closed:
                    P = P[:-1]
                span = float((P.max(0) - P.min(0)).max())
                if len(np.unique(np.round(P, 3), axis=0)) < 3 or (abs(signed_area(P)) < 0.5 and span < 2):
                    stray += 1
                    continue
                if len(P) <= 4000:
                    f = self_crossings(P)
                    if f:
                        cross += 1
                        at += f
            elif len(P) < 2 or float(np.sum(np.hypot(*np.diff(P, axis=0).T))) < 0.5:
                stray += 1
    return {"open_paths": open_, "stray_points": stray, "self_intersections": cross, "first_crossings": at[:5]}


def budget(kind, w, h, cells=None):
    if kind == "pixel":
        n = math.ceil(2 * 338 / 256 * (cells or w * h))
        return {"nodes": n, "paths": 64, "colours": 256}
    if kind not in BUDGET:
        return None
    k = max(1.0, math.sqrt(w * h / 65536))
    n, p, c = BUDGET[kind]
    return {"nodes": math.ceil(n * k), "paths": math.ceil(p * k), "colours": c}


def vcheck(doc, source=None, kind=None, cells=None):
    t0 = time.time()
    r = {"counts": counts(doc), "structure": structure(doc), "notes": list(doc.get("notes", []))}
    fails = []
    if source is not None:
        src = source_rgb(source)
        ren = render(doc, src.shape[1], src.shape[0], S=SS if src.size <= 4e6 * 3 else None)
        r["overlap"] = round(overlap(src, ren), 4)
        r["supersampling"] = SS
        pal = aliased_palette(src)
        if pal is not None:
            # a hard-edged source cannot match an anti-aliased render on its edge pixels: compare the
            # render snapped to the source's own colours, and keep the raw figure as overlap_antialiased
            r["overlap_antialiased"] = r["overlap"]
            r["overlap"] = round(overlap(src, snap_to(ren, pal)), 4)
            r["notes"].append(f"aliased source ({len(pal)} colours): overlap measured on the render snapped "
                              "to those colours")
        bar = BARS.get(kind)
        if bar is not None:
            r["overlap_bar"] = bar
            if r["overlap"] < bar:
                fails.append(f"overlap {r['overlap']} < {bar}")
    W, H = doc["width"], doc["height"]
    b = budget(kind, W, H, cells) if kind else None
    if b:
        r["budget"] = b
        for k in ("nodes", "paths", "colours"):
            if r["counts"][k] > b[k]:
                fails.append(f"{k} {r['counts'][k]} > budget {b[k]}")
    st = r["structure"]
    for k in ("open_paths", "stray_points", "self_intersections"):
        if st[k]:
            fails.append(f"{k}: {st[k]}")
    r["fails"] = fails
    r["pass"] = not fails
    r["seconds"] = round(time.time() - t0, 3)
    return r


# ---------------------------------------------------------------- curve fitting
def _unit(v):
    n = float(np.hypot(*v))
    return v / n if n > 1e-12 else np.array([1.0, 0.0])


def _bez(C, u):
    u = u[:, None]
    return (1 - u) ** 3 * C[0] + 3 * (1 - u) ** 2 * u * C[1] + 3 * (1 - u) * u ** 2 * C[2] + u ** 3 * C[3]


def _gen(P, u, t1, t2):
    p0, p3 = P[0], P[-1]
    b0, b1, b2, b3 = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u ** 2 * (1 - u), u ** 3
    A1, A2 = b1[:, None] * t1, b2[:, None] * t2
    tmp = P - (np.outer(b0 + b1, p0) + np.outer(b2 + b3, p3))
    c11, c12, c22 = (A1 * A1).sum(), (A1 * A2).sum(), (A2 * A2).sum()
    x1, x2 = (tmp * A1).sum(), (tmp * A2).sum()
    det = c11 * c22 - c12 * c12
    seg = float(np.hypot(*(p3 - p0)))
    if abs(det) > 1e-12:
        a1, a2 = (x1 * c22 - c12 * x2) / det, (c11 * x2 - c12 * x1) / det
    else:
        a1 = a2 = seg / 3
    if a1 < 1e-6 * seg or a2 < 1e-6 * seg or a1 > 4 * seg + 4 or a2 > 4 * seg + 4:
        a1 = a2 = seg / 3
    return np.array([p0, p0 + t1 * a1, p3 + t2 * a2, p3])


def _chord(P):
    d = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
    return d / d[-1] if d[-1] > 0 else np.linspace(0, 1, len(P))


def _reparam(P, C, u):
    Q = _bez(C, u)
    D1 = np.array([3 * (C[1] - C[0]), 3 * (C[2] - C[1]), 3 * (C[3] - C[2])])
    D2 = np.array([2 * (D1[1] - D1[0]), 2 * (D1[2] - D1[1])])
    uu = u[:, None]
    q1 = (1 - uu) ** 2 * D1[0] + 2 * (1 - uu) * uu * D1[1] + uu ** 2 * D1[2]
    q2 = (1 - uu) * D2[0] + uu * D2[1]
    num = ((Q - P) * q1).sum(1)
    den = (q1 * q1).sum(1) + ((Q - P) * q2).sum(1)
    out = np.where(np.abs(den) > 1e-12, u - num / np.where(den == 0, 1, den), u)
    return np.clip(out, 0, 1)


def fit_cubic(P, t1, t2, tol, depth=0):
    """Least-squares cubic Bezier through P with end tangents t1 (out of P[0]) and t2 (into P[-1], pointing back)."""
    n = len(P)
    if n == 2:
        d = float(np.hypot(*(P[1] - P[0]))) / 3
        return [np.array([P[0], P[0] + t1 * d, P[1] + t2 * d, P[1]])]
    u = _chord(P)
    C = _gen(P, u, t1, t2)
    e = ((_bez(C, u) - P) ** 2).sum(1)
    tol2 = tol * tol
    if e.max() <= tol2:
        return [C]
    if e.max() <= 4 * tol2:
        for _ in range(6):
            u = _reparam(P, C, u)
            C = _gen(P, u, t1, t2)
            e = ((_bez(C, u) - P) ** 2).sum(1)
            if e.max() <= tol2:
                return [C]
    if depth > 40:
        return [C]
    k = int(np.clip(np.argmax(e), 1, n - 2))
    tc = _unit(P[k - 1] - P[k + 1])
    return fit_cubic(P[:k + 1], t1, tc, tol, depth + 1) + fit_cubic(P[k:], -tc, t2, tol, depth + 1)


def resample(P, closed, step=1.0):
    Q = np.vstack([P, P[:1]]) if closed else P
    d = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(Q, axis=0).T))])
    if d[-1] < step * 2:
        return P
    n = max(int(round(d[-1] / step)), 3)
    s = np.linspace(0, d[-1], n + (0 if closed else 1), endpoint=not closed)
    return np.stack([np.interp(s, d, Q[:, 0]), np.interp(s, d, Q[:, 1])], 1)


def find_corners(P, closed, k=3, deg=50.0):
    n = len(P)
    if n < 2 * k + 1:
        return []
    idx = np.arange(n)
    if closed:
        a, b = P[(idx - k) % n], P[(idx + k) % n]
    else:
        a, b = P[np.clip(idx - k, 0, n - 1)], P[np.clip(idx + k, 0, n - 1)]
    v1, v2 = a - P, b - P
    cosang = (v1 * v2).sum(1) / np.maximum(np.hypot(*v1.T) * np.hypot(*v2.T), 1e-12)
    turn = 180 - np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    if not closed:
        turn[:k] = turn[n - k:] = 0
    out = []
    for i in np.argsort(-turn):
        if turn[i] < deg:
            break
        if all(min(abs(i - j), n - abs(i - j) if closed else n) > k for j in out):
            out.append(int(i))
    return sorted(out)


def _sharpen(P, c, closed, k=4):
    """Move a corner point to the crossing of lines fitted on each side, when that is within 1 px."""
    n = len(P)
    ib = [(c - j) % n if closed else c - j for j in range(1, k + 1)]
    ia = [(c + j) % n if closed else c + j for j in range(1, k + 1)]
    if not closed and (min(ib) < 0 or max(ia) >= n):
        return P[c]
    pb, pa = P[ib], P[ia]
    db, da = _unit(pb[0] - pb[-1]), _unit(pa[-1] - pa[0])
    den = db[0] * da[1] - db[1] * da[0]
    if abs(den) < 0.2:
        return P[c]
    w = pa[0] - pb[0]
    t = (w[0] * da[1] - w[1] * da[0]) / den
    x = pb[0] + t * db
    return x if np.hypot(*(x - P[c])) <= 1.0 else P[c]


def _run_segs(R, tol):
    m = len(R)
    a, b = R[0], R[-1]
    ch = b - a
    L = float(np.hypot(*ch))
    if m <= 2:
        return [("L", tuple(b))]
    if L > 1e-9:
        dist = np.abs((R[:, 0] - a[0]) * ch[1] - (R[:, 1] - a[1]) * ch[0]) / L
        if dist.max() <= tol:
            return [("L", tuple(b))]
    j = min(3, m - 1)
    t1 = _unit(R[1:j + 1].mean(0) - a)
    t2 = _unit(R[-j - 1:-1].mean(0) - b)
    out = []
    for C in fit_cubic(R, t1, t2, tol):
        cl = C[3] - C[0]
        Ln = float(np.hypot(*cl))
        if Ln > 1e-9 and all(abs((q[0] - C[0][0]) * cl[1] - (q[1] - C[0][1]) * cl[0]) / Ln <= tol / 4
                             for q in (C[1], C[2])):
            out.append(("L", tuple(C[3])))
        else:
            out.append(("C", tuple(C[1]), tuple(C[2]), tuple(C[3])))
    return out


def smooth_pts(P, closed, pinned, passes):
    """[1,2,1]/4 smoothing passes; pinned indices (corners, open ends) stay put. Removes lattice staircase."""
    if passes <= 0 or len(P) < 5:
        return P
    pin = np.zeros(len(P), bool)
    pin[list(pinned)] = True
    if not closed:
        pin[0] = pin[-1] = True
    for _ in range(passes):
        if closed:
            Q = (np.roll(P, 1, 0) + 2 * P + np.roll(P, -1, 0)) / 4
        else:
            Q = P.copy()
            Q[1:-1] = (P[:-2] + 2 * P[1:-1] + P[2:]) / 4
        P = np.where(pin[:, None], P, Q)
    return P


def fit_path(P, closed, tol=0.5, corner_deg=50.0, k=3, smooth=0):
    """Points to one sub of lines and cubics: corners by turning angle, then a cubic fit per run."""
    P = np.asarray(P, float)
    if closed and len(P) > 1 and np.allclose(P[0], P[-1]):
        P = P[:-1]
    n = len(P)
    if n < 3:
        return {"start": tuple(P[0]), "segs": [("L", tuple(p)) for p in P[1:]], "closed": closed}
    cs = find_corners(P, closed, k, corner_deg)
    if cs:
        P = P.copy()
        for c in cs:
            P[c] = _sharpen(P, c, closed)
    P = smooth_pts(P, closed, cs, smooth)
    if not closed:
        cuts = [0] + [c for c in cs if 0 < c < n - 1] + [n - 1]
        segs = []
        for a, b in zip(cuts, cuts[1:]):
            segs += _run_segs(P[a:b + 1], tol)
        return {"start": tuple(P[0]), "segs": segs, "closed": False}
    if not cs:
        Q = np.vstack([P, P[:1]])
        t = _unit(P[1] - P[-1])
        segs = []
        for C in fit_cubic(Q, t, -t, tol):
            segs.append(("C", tuple(C[1]), tuple(C[2]), tuple(C[3])))
        return {"start": tuple(P[0]), "segs": segs, "closed": True}
    P = np.roll(P, -cs[0], axis=0)
    cs = [c - cs[0] for c in cs] + [n]
    Q = np.vstack([P, P[:1]])
    segs = []
    for a, b in zip(cs, cs[1:]):
        segs += _run_segs(Q[a:b + 1], tol)
    return {"start": tuple(P[0]), "segs": segs, "closed": True}


def rdp(P, eps):
    """Ramer-Douglas-Peucker on an open polyline."""
    if len(P) < 3:
        return P
    keep = np.zeros(len(P), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(P) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ch = P[b] - P[a]
        L = float(np.hypot(*ch))
        seg = P[a + 1:b]
        d = (np.abs((seg[:, 0] - P[a][0]) * ch[1] - (seg[:, 1] - P[a][1]) * ch[0]) / L if L > 1e-12
             else np.hypot(*(seg - P[a]).T))
        i = int(np.argmax(d))
        if d[i] > eps:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return P[keep]


def simplify_doc(doc, tol=0.5, method="fit", corner_deg=50.0):
    out = {"width": doc["width"], "height": doc["height"], "shapes": [], "notes": list(doc.get("notes", []))}
    for sh in doc["shapes"]:
        subs = []
        for s in sh["subs"]:
            P = flatten(s, per_px=0.5)
            closed = s["closed"] or (len(P) > 2 and np.allclose(P[0], P[-1]))
            if closed and np.allclose(P[0], P[-1]):
                P = P[:-1]
            if len(P) < 3:
                subs.append(s)
                continue
            if method == "rdp":
                Q = rdp(np.vstack([P, P[:1]]) if closed else P, tol)
                if closed:
                    Q = Q[:-1]
                if closed and len(Q) < 3:
                    continue
                subs.append({"start": tuple(Q[0]), "segs": [("L", tuple(p)) for p in Q[1:]], "closed": closed})
            else:
                subs.append(fit_path(resample(P, closed, 1.0), closed, tol, corner_deg))
        if subs:
            out["shapes"].append(dict(sh, subs=subs))
    return out


# ---------------------------------------------------------------- export
def _flat_polys(sh, tol_px=0.25):
    for s in sh["subs"]:
        P = flatten(s, per_px=max(tol_px * 4, 0.5))
        closed = s["closed"] or (len(P) > 2 and np.allclose(P[0], P[-1]))
        if closed and len(P) > 2 and np.allclose(P[0], P[-1]):
            P = P[:-1]
        yield P, closed


def _ps_ops(doc, ops):
    """PostScript-style path operators (PDF and EPS share them). ops: dict of operator names."""
    out = []
    for sh in doc["shapes"]:
        for kind in ("fill", "stroke"):
            col = sh[kind]
            if not col:
                continue
            r, g, b = (c / 255 for c in col)
            out.append(f"{r:.4f} {g:.4f} {b:.4f} {ops['rgb_' + kind]}")
            if kind == "stroke":
                out.append(f"{fnum(sh['width'])} {ops['width']} 1 {ops['cap']} 1 {ops['join']}")
            for s in sh["subs"]:
                out.append(f"{fnum(s['start'][0])} {fnum(s['start'][1])} {ops['m']}")
                for gseg in s["segs"]:
                    xy = " ".join(f"{fnum(p[0])} {fnum(p[1])}" for p in gseg[1:])
                    out.append(f"{xy} {ops['l'] if gseg[0] == 'L' else ops['c']}")
                if s["closed"] or kind == "fill":
                    out.append(ops["h"])
            if kind == "fill":
                out.append(ops["eofill"] if sh["rule"] == "evenodd" else ops["fill"])
            else:
                out.append(ops["stroke"])
    return out


def to_pdf(doc, dpi=96.0):
    W, H = doc["width"], doc["height"]
    k = 72.0 / dpi
    ops = {"rgb_fill": "rg", "rgb_stroke": "RG", "width": "w", "cap": "J", "join": "j", "m": "m", "l": "l",
           "c": "c", "h": "h", "fill": "f", "eofill": "f*", "stroke": "S"}
    content = "\n".join([f"{k:.6f} 0 0 {-k:.6f} 0 {H * k:.4f} cm"] + _ps_ops(doc, ops)).encode("ascii")
    z = zlib.compress(content)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {fnum(W * k)} {fnum(H * k)}] /Contents 4 0 R "
            f"/Resources << >> >>".encode(),
            f"<< /Length {len(z)} /Filter /FlateDecode >>\nstream\n".encode() + z + b"\nendstream"]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


def to_eps(doc, dpi=96.0):
    W, H = doc["width"], doc["height"]
    k = 72.0 / dpi
    ops = {"rgb_fill": "setrgbcolor", "rgb_stroke": "setrgbcolor", "width": "setlinewidth",
           "cap": "setlinecap", "join": "setlinejoin", "m": "moveto", "l": "lineto", "c": "curveto",
           "h": "closepath", "fill": "fill", "eofill": "eofill", "stroke": "stroke"}
    body = []
    for line in _ps_ops(doc, ops):
        if line.endswith(" moveto"):
            body.append("newpath")
        body.append(line)
    hdr = ["%!PS-Adobe-3.0 EPSF-3.0", "%%Creator: photowright", f"%%BoundingBox: 0 0 {math.ceil(W * k)} {math.ceil(H * k)}",
           f"%%HiResBoundingBox: 0 0 {W * k:.3f} {H * k:.3f}", "%%Pages: 1", "%%EndComments",
           "gsave", f"0 {H * k:.4f} translate {k:.6f} {-k:.6f} scale"]
    return "\n".join(hdr + body + ["grestore", "showpage", "%%EOF", ""])


def to_dxf(doc, dpi=96.0, units="mm"):
    """DXF R12 (AC1009): closed POLYLINE/VERTEX/SEQEND only, curves flattened to 0.1 px, y up, mm (or px)."""
    k = 25.4 / dpi if units == "mm" else (1 / dpi if units == "in" else 1.0)
    H = doc["height"]
    L = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$EXTMIN", "10", "0", "20", "0",
         "9", "$EXTMAX", "10", fnum(doc["width"] * k), "20", fnum(H * k), "0", "ENDSEC"]
    layers = []
    ents = []
    for sh in doc["shapes"]:
        col = sh["fill"] or sh["stroke"]
        lay = "C" + hexc(col)[1:].upper()
        if lay not in layers:
            layers.append(lay)
        for P, closed in _flat_polys(sh, 0.1):
            if len(P) < 2:
                continue
            ents += ["0", "POLYLINE", "8", lay, "66", "1", "10", "0", "20", "0", "30", "0", "70", "1" if closed else "0"]
            for x, y in P:
                ents += ["0", "VERTEX", "8", lay, "10", f"{x * k:.4f}", "20", f"{(H - y) * k:.4f}", "30", "0"]
            ents += ["0", "SEQEND", "8", lay]
    L += ["0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", str(len(layers))]
    for lay in layers:
        L += ["0", "LAYER", "2", lay, "70", "0", "62", "7", "6", "CONTINUOUS"]
    L += ["0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"] + ents + ["0", "ENDSEC", "0", "EOF"]
    return "\n".join(L) + "\n"


def read_dxf_entities(text):
    """Entity type names in the ENTITIES section of an ASCII DXF (for the cutter-safety check)."""
    ln = [s.strip() for s in text.splitlines()]
    pairs = list(zip(ln[0::2], ln[1::2]))
    out, inside = [], False
    for i, (code, val) in enumerate(pairs):
        if code == "2" and i and pairs[i - 1] == ("0", "SECTION"):
            inside = val == "ENTITIES"
        elif code == "0" and inside and val not in ("ENDSEC",):
            out.append(val)
    return out


# ---------------------------------------------------------------- inkscape (rung 2, external)
def inkscape():
    if rung_max() < 2:
        return None
    for name in ("inkscape.com", "inkscape"):
        p = shutil.which(name)
        if p:
            return p
    for p in (Path("C:/Program Files/Inkscape/bin/inkscape.com"), Path("C:/Program Files (x86)/Inkscape/bin/inkscape.com"),
              Path("/Applications/Inkscape.app/Contents/MacOS/inkscape"), Path("/usr/bin/inkscape")):
        if p.exists():
            return str(p)
    return None


def inkscape_png(path, out_png, width, height):
    """Open a vector file in Inkscape and export a PNG of the page (proves the file opens)."""
    exe = inkscape()
    if exe is None:
        return None
    r = subprocess.run([exe, str(path), "--export-type=png", f"--export-filename={out_png}",
                        f"--export-width={int(width)}", f"--export-height={int(height)}", "--export-area-page"],
                       capture_output=True, text=True, timeout=180)
    if r.returncode or not Path(out_png).exists():
        raise RuntimeError(f"inkscape could not open {Path(path).name}: {(r.stderr or r.stdout)[-300:]}")
    return out_png


# ---------------------------------------------------------------- commands
def load_doc(path):
    doc = read_svg(path)
    if not doc["width"] or not doc["height"]:
        raise ValueError("the SVG has no size (width/height or viewBox)")
    return doc


def write_out(path, data):
    path = free_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8", newline="\n")
    return path


def cmd_vcheck(a):
    doc = load_doc(a.input)
    r = vcheck(doc, a.source, a.kind, a.cells)
    r.update(command="vcheck", input=str(a.input), source=a.source, kind=a.kind, rung=1,
             tool=["own render-back (winding fill, 16x supersampling)"])
    return r


def cmd_simplify(a):
    doc = load_doc(a.input)
    before = counts(doc)
    t0 = time.time()
    new = simplify_doc(doc, a.tolerance, a.method, a.corner)
    out = write_out(core.out_for(a.input, a.output, "simple", ".svg"), to_svg(new))
    W, H = int(round(doc["width"])), int(round(doc["height"]))
    fid = round(overlap(render(doc, W, H), render(new, W, H)), 4)
    return {"command": "simplify", "input": str(a.input), "output": str(out), "method": a.method,
            "tolerance": a.tolerance, "before": before, "after": counts(new), "fidelity": fid,
            "fidelity_note": "share of pixels within 24 between renders of the input and the output",
            "seconds": round(time.time() - t0, 3), "rung": 1,
            "tool": ["own " + ("RDP" if a.method == "rdp" else "corner split + least-squares cubic fit")]}


EXPORTERS = {"svg": (".svg", lambda d, a: to_svg(d, a.units if a.units != "px" else None, a.dpi)),
             "pdf": (".pdf", lambda d, a: to_pdf(d, a.dpi)),
             "eps": (".eps", lambda d, a: to_eps(d, a.dpi)),
             "dxf": (".dxf", lambda d, a: to_dxf(d, a.dpi, a.units if a.units != "px" else "px"))}


def cmd_export(a):
    doc = load_doc(a.input)
    fmt = a.format or (Path(a.output).suffix.lstrip(".").lower() if a.output else "svg")
    if fmt not in EXPORTERS:
        raise SystemExit(f"export: unknown format {fmt} (svg, pdf, eps, dxf)")
    ext, fn = EXPORTERS[fmt]
    dropped = 0
    if getattr(a, "drop", None):
        gone = {c.strip().lstrip("#").lower() for c in a.drop.split(",") if c.strip()}
        keep = [sh for sh in doc["shapes"] if hexc(sh["fill"] or sh["stroke"])[1:] not in gone]
        dropped = len(doc["shapes"]) - len(keep)
        doc = dict(doc, shapes=keep)
    out = write_out(core.out_for(a.input, a.output, "export", ext), fn(doc, a))
    r = {"command": "export", "input": str(a.input), "output": str(out), "format": fmt, "counts": counts(doc),
         "rung": 1, "tool": [f"own {fmt.upper()} writer"], "notes": list(doc.get("notes", []))}
    if getattr(a, "drop", None):
        r["dropped_shapes"] = dropped
    if fmt == "dxf":
        r["notes"].append("DXF R12: closed POLYLINE entities only, curves flattened to 0.1 px; "
                          "stacked colours overlap, so a cutter cuts every layer in full")
        r["entities"] = sorted(set(read_dxf_entities(out.read_text())))
    if a.check:
        exe = inkscape()
        if exe is None:
            r["inkscape"] = "not found (or hidden at rung 1): open check skipped"
        elif fmt in ("svg", "pdf"):
            with tempfile.TemporaryDirectory() as td:
                png = inkscape_png(out, Path(td) / "ink.png", doc["width"], doc["height"])
                ink = source_rgb(png)
                r["inkscape"] = {"opened": True, "overlap_vs_own_render": round(overlap(ink, render(doc)), 4)}
        elif fmt == "dxf":
            with tempfile.TemporaryDirectory() as td:
                svg = Path(td) / "dxf.svg"
                pr = subprocess.run([exe, str(out), "--export-type=svg", f"--export-filename={svg}"],
                                    capture_output=True, text=True, timeout=180)
                if pr.returncode or not svg.exists():
                    raise RuntimeError("inkscape could not open the DXF: " + (pr.stderr or "")[-300:])
                r["inkscape"] = {"opened": True, "paths_read": svg.read_text(encoding="utf-8").count("<path")}
        else:
            r["inkscape"] = "EPS import in Inkscape needs Ghostscript (not checked here)"
    return r


def add_commands(sub, edit):
    p = sub.add_parser("vcheck", help="vector bars: render-back overlap, node/path/colour budgets, structure")
    p.add_argument("input", help="SVG")
    p.add_argument("--source", help="the raster it was traced from (for overlap)")
    p.add_argument("--kind", choices=sorted(BARS), help="bars and budgets for this kind")
    p.add_argument("--cells", type=int, help="pixel kind: number of pixel-art cells (default: image area)")
    p.set_defaults(fn=cmd_vcheck)
    p = sub.add_parser("simplify", help="path simplification: refit curves (default) or RDP polylines")
    p.add_argument("input", help="SVG")
    p.add_argument("-o", "--output")
    p.add_argument("--tolerance", type=float, default=0.5, help="max deviation in px")
    p.add_argument("--method", choices=("fit", "rdp"), default="fit")
    p.add_argument("--corner", type=float, default=50.0, help="turning angle (deg) that makes a corner")
    p.set_defaults(fn=cmd_simplify)
    p = sub.add_parser("export", help="SVG (plain subset), PDF, EPS or DXF R12 from an SVG")
    p.add_argument("input", help="SVG")
    p.add_argument("-o", "--output")
    p.add_argument("--format", choices=sorted(EXPORTERS))
    p.add_argument("--units", choices=("px", "mm", "in"), default="px", help="svg size units; dxf units (default px; mm for cutters)")
    p.add_argument("--dpi", type=float, default=96.0)
    p.add_argument("--check", action="store_true", help="open the export in Inkscape (svg, pdf) and compare")
    p.add_argument("--drop", help="leave out shapes of these colours, e.g. ffffff (a white background is not a cut)")
    p.set_defaults(fn=cmd_export)


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "vcheck, simplify, export": (1, "own render-back, curve fit, SVG/PDF/EPS/DXF writers"),
    "export --check (inkscape)": (2, "Inkscape CLI") if inkscape() else (0, "Inkscape not found: check skipped"),
})
