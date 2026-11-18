"""Batch 18b (0.19.0): Lens profile correction from a lensfun database the user already has.

lensprofile: finds the lens in lensfun XML files (a folder or one file; lensfun's data is
             CC-BY-SA 3.0 so the plugin never ships it: point --db at a lensfun install or a clone
             of github.com/lensfun/lensfun data/db), interpolates the distortion and vignetting
             terms at the focal length (and aperture), and corrects with the plugin's own code.
             The recipe stores the resolved coefficients, so replay needs no database.
Models (lensfun conventions, r = 1 at half the shorter side for distortion, half the diagonal for
vignetting): poly3 Rd = Ru (1 - k1 + k1 Ru^2); poly5 Rd = Ru (1 + k1 Ru^2 + k2 Ru^4);
ptlens Rd = Ru (a Ru^3 + b Ru^2 + c Ru + 1 - a - b - c); vignetting pa Cd = Cs (1 + k1 r^2 + k2 r^4 + k3 r^6).
Own NumPy and Pillow only.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from . import core, transform
from .core import OPS, to_enc, to_lin


def _files(db):
    p = Path(db)
    if p.is_file():
        return [p]
    if not p.exists():
        raise SystemExit(f"lensprofile: {db} not found (point --db at lensfun's data/db folder or one .xml)")
    return sorted(p.rglob("*.xml"))


def find_lens(db, name):
    """(model text, calibration element) of the best match: every word of name in the model text."""
    words = name.lower().split()
    hits = []
    for f in _files(db):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        for lens in root.iter("lens"):
            models = [m.text or "" for m in lens.findall("model")]
            for m in models:
                if all(w in m.lower() for w in words):
                    hits.append((len(m), m, lens))
                    break
    if not hits:
        raise SystemExit(f"lensprofile: no lens matching '{name}' in {db}")
    hits.sort(key=lambda t: t[0])
    return hits[0][1], hits[0][2]


def _interp(entries, key, x):
    """Linear interpolation of entry dicts sorted by key at x (clamped)."""
    entries = sorted(entries, key=lambda e: e[key])
    if x <= entries[0][key]:
        return entries[0]
    if x >= entries[-1][key]:
        return entries[-1]
    for a, b in zip(entries, entries[1:]):
        if a[key] <= x <= b[key]:
            t = (x - a[key]) / (b[key] - a[key]) if b[key] != a[key] else 0.0
            out = dict(a)
            for k in a:
                if k in b and isinstance(a[k], float):
                    out[k] = a[k] + t * (b[k] - a[k])
            return out
    return entries[-1]


def resolve(lens, focal, aperture=None):
    cal = lens.find("calibration")
    if cal is None:
        raise SystemExit("lensprofile: the lens has no calibration block")
    res = {}
    dist = []
    for d in cal.findall("distortion"):
        e = {k: float(v) for k, v in d.attrib.items() if k not in ("model",)}
        e["model"] = d.get("model")
        dist.append(e)
    if dist:
        models = {e["model"] for e in dist}
        if len(models) > 1:
            dist = [e for e in dist if e["model"] == sorted(models)[0]]
        e = _interp(dist, "focal", float(focal))
        res["distortion"] = {k: v for k, v in e.items() if k != "focal"}
    vig = []
    for v in cal.findall("vignetting"):
        e = {k: float(x) for k, x in v.attrib.items() if k not in ("model",)}
        vig.append(e)
    if vig and aperture is not None:
        near = min({e["distance"] for e in vig if "distance" in e} or {0.0}, key=lambda d: -d)
        vig = [e for e in vig if e.get("distance", near) == near]
        fs = sorted({e["focal"] for e in vig}, key=lambda f: abs(f - focal))[:2]
        rows = []
        for f in fs:
            sub = [e for e in vig if e["focal"] == f]
            rows.append(_interp(sub, "aperture", float(aperture)))
        e = _interp(rows, "focal", float(focal)) if len(rows) > 1 else rows[0]
        res["vignetting"] = {"k1": e.get("k1", 0.0), "k2": e.get("k2", 0.0), "k3": e.get("k3", 0.0)}
    return res


def rd_of_ru(model, c, ru):
    if model == "poly3":
        k1 = c.get("k1", 0.0)
        return ru * (1 - k1 + k1 * ru * ru)
    if model == "poly5":
        return ru * (1 + c.get("k1", 0.0) * ru ** 2 + c.get("k2", 0.0) * ru ** 4)
    if model == "ptlens":
        a, b, cc = c.get("a", 0.0), c.get("b", 0.0), c.get("c", 0.0)
        return ru * (a * ru ** 3 + b * ru ** 2 + cc * ru + 1 - a - b - cc)
    raise ValueError(f"lensprofile: distortion model {model} not handled")


def op_lensprofile(img, p, used):
    h, w = img.px.shape[:2]
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    dx, dy = xx - cx, yy - cy
    if p.get("vignetting"):
        v = p["vignetting"]
        r2 = (dx * dx + dy * dy) / (cx * cx + cy * cy)
        gain = 1 + v["k1"] * r2 + v["k2"] * r2 ** 2 + v["k3"] * r2 ** 3
        lin = to_lin(img.color()) / np.maximum(gain, 1e-3)[..., None]
        img = img.with_color(to_enc(np.clip(lin, 0, 1)))
        used.add("lensprofile.vignetting", 1, "own pa vignetting correction (linear light)")
    if p.get("distortion"):
        d = p["distortion"]
        R = min(cx, cy) + 0.5
        ru = np.hypot(dx, dy) / R
        rd = rd_of_ru(d["model"], d, ru)
        s = np.where(ru > 1e-9, rd / np.maximum(ru, 1e-9), 1.0)
        img = transform.remap(img, (cx + dx * s).astype(np.float32), (cy + dy * s).astype(np.float32), used,
                              "lensprofile.distortion")
    used.add("lensprofile", 1, "own lensfun-model correction")
    return img


def cmd_lensprofile(a):
    model, lens = find_lens(a.db, a.lens)
    p = resolve(lens, a.focal, a.aperture)
    if a.no_vignetting:
        p.pop("vignetting", None)
    p["lens"] = model
    p["focal"] = a.focal
    r = core.edit_command(a, "lensprofile", [{"op": "lensprofile", "params": p}])
    r["lens"] = model
    r["profile"] = {k: v for k, v in p.items() if k in ("distortion", "vignetting")}
    return r


OPS["lensprofile"] = op_lensprofile


def add_commands(sub, edit):
    p = edit("lensprofile", cmd_lensprofile,
             "Lens profile correction from a lensfun database you have (distortion, vignetting; rung 1 code)")
    p.add_argument("--db", required=True, help="lensfun data/db folder or one .xml (CC-BY-SA data, never bundled)")
    p.add_argument("--lens", required=True, help="words that all appear in the lens model, e.g. 'EF 24-105'")
    p.add_argument("--focal", type=float, required=True, help="focal length in mm")
    p.add_argument("--aperture", type=float, help="f-number; enables vignetting correction")
    p.add_argument("--no-vignetting", action="store_true")


core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {"lensprofile": (1, "own code; profiles from a lensfun db you point at")})
