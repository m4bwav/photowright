"""Batch 19 (0.20.0): the rung 2 rows of the coverage table (ai-docs/notes/coverage-gaps-2026-11-17.md).

Formats Pillow cannot read alone, probed at run time and refused with the install line when absent:
  HEIC/HEIF  pillow-heif (BSD-3; libheif LGPL, called as a wheel, never bundled)
  JPEG XL    pillow-jxl-plugin (GPL-3.0: optional, probed, never bundled; libjxl BSD-3)
  camera raw rawpy (MIT; LibRaw LGPL/CDDL, called as a wheel): demosaic to 16-bit sRGB, camera white balance
camraw:      the Camera Raw Basic panel as one rung 1 command: temperature, tint, exposure, contrast,
             highlights, shadows, whites, blacks, texture, clarity, dehaze, vibrance, saturation, in
             Adobe's slider ranges, built from the plugin's own ops in Camera Raw's order.
c2pa verify: `inspect --c2pa-verify` hands the file to c2patool (rung 2, MIT/Apache-2.0) when on PATH.
"""
import json
import sys
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from . import core
from .core import OPS, edit_command, probe, to_enc, to_lin

HEIF_EXT = {".heic", ".heif", ".hif"}
JXL_EXT = {".jxl"}
RAW_EXT = {".dng", ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf", ".orf", ".rw2", ".pef",
           ".srw", ".3fr", ".iiq", ".erf", ".kdc", ".mrw", ".x3f", ".rwl"}
PLUGINS = {"heif": ("pillow_heif", "pip install pillow-heif", "HEIC/HEIF"),
           "jxl": ("pillow_jxl", "pip install pillow-jxl-plugin", "JPEG XL"),
           "raw": ("rawpy", "pip install rawpy", "camera raw")}


def kind_of(path):
    s = Path(path).suffix.lower()
    return "heif" if s in HEIF_EXT else "jxl" if s in JXL_EXT else "raw" if s in RAW_EXT else None


def need(kind):
    """The rung 2 module for a format, or SystemExit naming the package (never a silent fallback)."""
    mod_name, pip, label = PLUGINS[kind]
    mod = probe(mod_name)
    if mod is None:
        why = "PHW_RUNG_MAX is below 2" if core.rung_max() < 2 else f"{mod_name} is not installed"
        raise SystemExit(f"{label} files need {mod_name} (rung 2): {why}. Install with: {pip}")
    if kind == "heif" and hasattr(mod, "register_heif_opener"):
        mod.register_heif_opener()
    return mod


def open_plugin_format(path, used=None):
    """Register the opener for HEIC/JXL so Pillow can read the file; returns the kind or None."""
    k = kind_of(path)
    if k in ("heif", "jxl"):
        need(k)
        if used:
            used.add("load", 2, PLUGINS[k][0])
    return k


def load_raw(path, used=None, rawpy=None):
    """Demosaic with LibRaw through rawpy: camera white balance, sRGB primaries and curve, 16 bits."""
    rawpy = rawpy or need("raw")
    with rawpy.imread(str(path)) as r:
        rgb = r.postprocess(use_camera_wb=True, output_bps=16, no_auto_bright=True)
    px = np.asarray(rgb, np.float32) / 65535.0
    if used:
        used.add("load", 2, "rawpy (LibRaw)")
    notes = ["camera raw demosaiced by LibRaw: camera white balance, sRGB, 16 bits, no auto brightening"]
    return core.Img(px, False, core.srgb_icc() if core.ImageCms else None, None, None, 16, "RAW", notes)


def load_hook(path, used=None):
    k = kind_of(path)
    if k == "raw":
        return load_raw(path, used)
    if k:
        open_plugin_format(path, used)
    return None


core.LOAD_HOOKS.append(load_hook)

_orig_inspect = core.cmd_inspect


def cmd_inspect(a):
    k = kind_of(a.input)
    if k == "raw":
        rawpy = need("raw")
        p = Path(a.input)
        with rawpy.imread(str(p)) as r:
            s = r.sizes
            r_ = {"command": "inspect", "file": str(p), "bytes": p.stat().st_size, "rung": 2, "tool": ["rawpy"],
                  "format": "RAW", "size": [int(s.height), int(s.width)], "raw_size": [int(s.raw_height), int(s.raw_width)],
                  "bit_depth": 16, "colors": int(r.num_colors), "pattern": str(r.raw_pattern.tolist()),
                  "camera_wb": [float(x) for x in r.camera_whitebalance]}
        r_["c2pa"] = core.c2pa_scan(p)
    else:
        if k:
            open_plugin_format(a.input)
        r_ = _orig_inspect(a)
        if k:
            r_["rung"], r_["tool"] = 2, ["Pillow", PLUGINS[k][0]]
    if getattr(a, "c2pa_verify", False):
        r_["c2pa_verify"] = c2pa_verify(a.input)
    return r_


core.cmd_inspect = cmd_inspect


def c2pa_verify(path, tool=None):
    """Validate the manifest with c2patool when present (it checks signatures and hash bindings)."""
    tool = tool or shutil.which("c2patool")
    if not tool or core.rung_max() < 2:
        return {"ran": False, "note": "c2patool not on PATH (rung 2; cargo install c2patool or a release binary "
                                       "from github.com/contentauth/c2pa-rs); detection above is rung 1 only"}
    p = subprocess.run([tool, str(path)], capture_output=True, text=True, timeout=120)
    out = {"ran": True, "tool": tool, "exit": p.returncode}
    try:
        j = json.loads(p.stdout)
        out["validation_status"] = j.get("validation_status") or []
        out["active_manifest"] = j.get("active_manifest")
        out["valid"] = p.returncode == 0 and not out["validation_status"]
    except ValueError:
        out["valid"] = False
        out["stderr"] = (p.stderr or p.stdout)[-400:]
    return out


# ---------------------------------------------------------------- Camera Raw Basic panel
def op_whites_blacks(img, p, used):
    """Whites/Blacks: move the end points of the tone curve, weighted so mid-grey barely moves.
    whites +100 lifts 1 - (1-x)^... : out = x + w * x^3 * 0.25 ; blacks +100: out = x + b * (1-x)^3 * 0.25."""
    w, b = float(p.get("whites", 0)) / 100.0, float(p.get("blacks", 0)) / 100.0
    c = img.color().astype(np.float64)
    out = c + w * 0.25 * c ** 3 + b * 0.25 * (1 - c) ** 3
    used.add("camraw.whites_blacks", 1, "NumPy end-point curve")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def op_contrast_s(img, p, used):
    """Contrast as an S curve about mid-grey in linear-light 0.18 terms: out = m + (x-m) * (1 + k*4x(1-x))."""
    k = float(p.get("amount", 0)) / 100.0
    c = img.color().astype(np.float64)
    m = 0.4613  # sRGB-encoded 18% grey
    out = c + k * (c - m) * 4 * c * (1 - c)
    used.add("camraw.contrast", 1, "NumPy S curve about 18% grey")
    return img.with_color(np.clip(out, 0, 1).astype(np.float32))


def camraw_steps(a):
    """Camera Raw order: white balance, exposure, contrast, highlights/shadows, whites/blacks,
    texture, clarity, dehaze, vibrance, saturation. Zero sliders add no step."""
    s = []
    if a.temp or a.tint:
        t, g = a.temp / 100.0, a.tint / 100.0
        s.append({"op": "adjust.white_balance", "params": {"multipliers": [2 ** (0.5 * t), 2 ** (-0.5 * g), 2 ** (-0.5 * t)]}})
    if a.exposure:
        s.append({"op": "adjust.exposure", "params": {"stops": a.exposure}})
    if a.contrast:
        s.append({"op": "camraw.contrast", "params": {"amount": a.contrast}})
    if a.highlights or a.shadows:
        s.append({"op": "tone.shadows_highlights", "params": {"shadows": max(0.0, a.shadows) / 100.0,
                                                               "highlights": max(0.0, -a.highlights) / 100.0, "radius": 30}})
        if a.shadows < 0 or a.highlights > 0:
            s.append({"op": "camraw.whites_blacks", "params": {"whites": max(0.0, a.highlights) * 0.5,
                                                               "blacks": min(0.0, a.shadows) * 0.5}})
    if a.whites or a.blacks:
        s.append({"op": "camraw.whites_blacks", "params": {"whites": a.whites, "blacks": a.blacks}})
    if a.texture:
        s.append({"op": "detail.clarity", "params": {"amount": a.texture / 100.0, "radius": 3}})
    if a.clarity:
        s.append({"op": "detail.clarity", "params": {"amount": a.clarity / 100.0, "radius": 20}})
    if a.dehaze > 0:
        s.append({"op": "detail.dehaze", "params": {"amount": min(0.95, a.dehaze / 100.0), "radius": 7}})
    elif a.dehaze < 0:
        s.append({"op": "camraw.whites_blacks", "params": {"blacks": -a.dehaze * 0.6, "whites": a.dehaze * 0.3}})
    if a.vibrance:
        s.append({"op": "tone.vibrance", "params": {"amount": a.vibrance / 100.0}})
    if a.saturation:
        s.append({"op": "adjust.hue_sat", "params": {"saturation": 1 + a.saturation / 100.0}})
    return s


# ---------------------------------------------------------------- camraw --match: fit the sliders to a reference
# After PREEN (arXiv:2610.36896): match a reference's look by choosing editor slider values, so the result is a
# short list of named, re-editable settings with a strength knob, not a raw colour remap. Written fresh from the
# paper's idea; the paper trains a network to predict presets, here a direct search fits them to the reference's
# Lab statistics on small copies (no model, no training).
SLIDERS = ("temp", "tint", "exposure", "contrast", "highlights", "shadows", "whites", "blacks", "texture", "clarity",
           "dehaze", "vibrance", "saturation")
FIT_DEFAULT = ("temp", "tint", "exposure", "contrast", "whites", "blacks", "vibrance", "saturation")
FIT_ALLOWED = FIT_DEFAULT + ("highlights", "shadows")
CHROMA = ("temp", "tint", "vibrance", "saturation")   # the sliders --amount scales
PCTS = (5, 25, 50, 75, 95)


def small_copy(img, side=160):
    """Box-filtered float copy with the long side `side` (no 8-bit round trip)."""
    c = img.color()
    h, w = c.shape[:2]
    s = side / max(h, w)
    if s >= 1:
        return img.copy(px=c.copy(), alpha=False)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    ch = [np.asarray(Image.fromarray(c[..., i]).resize(size, Image.BOX), np.float32) for i in range(c.shape[2])]
    return img.copy(px=np.stack(ch, -1), alpha=False)


def lab_signature(c):
    """What the fit matches: Lab mean and std per channel, L at 5/25/50/75/95 %, a and b percentiles at half weight."""
    from .masks import rgb_to_lab
    rgb = np.repeat(c, 3, axis=2) if c.shape[2] == 1 else c[..., :3]
    f = rgb_to_lab(np.clip(rgb, 0, 1)).reshape(-1, 3)
    return np.concatenate([f.mean(0), f.std(0), np.percentile(f[:, 0], PCTS),
                           0.5 * np.percentile(f[:, 1], PCTS), 0.5 * np.percentile(f[:, 2], PCTS)])


def hist_overlap(c1, c2, bins=16):
    """Histogram intersection (0..1) of L alone and of a,b jointly; 1 = identical distributions."""
    from .masks import rgb_to_lab
    def lab(c):
        rgb = np.repeat(c, 3, axis=2) if c.shape[2] == 1 else c[..., :3]
        return rgb_to_lab(np.clip(rgb, 0, 1)).reshape(-1, 3)
    p, q = lab(c1), lab(c2)
    hl = [np.histogram(x[:, 0], bins, (0, 100))[0] / len(x) for x in (p, q)]
    hab = [np.histogram2d(x[:, 1], x[:, 2], bins, [[-80, 80], [-80, 80]])[0] / len(x) for x in (p, q)]
    return float(np.minimum(*hl).sum()), float(np.minimum(*hab).sum())


def _scaled(name):
    return 1.0 if name == "exposure" else 100.0     # search units: sliders /100, exposure in stops


def _render(base, vals, small, used):
    ns = dict(base)
    ns.update(vals)
    return core.apply_steps(small, camraw_steps(_NS(ns)), used).color()


class _NS:
    def __init__(self, d):
        self.__dict__.update(d)


def fit_sliders(src_small, ref_small, names, base, pull=1.0, tol=0.005, max_evals=1500):
    """Hooke-Jeeves pattern search (deterministic, NumPy only) over the named sliders in search units
    (-1..1, exposure -3..3 stops), minimising the squared Lab-signature distance to the reference plus a small
    L2 pull toward 0 so sliders the reference does not ask for stay put. Returns ({name: value}, loss, evals)."""
    target = lab_signature(ref_small.color())
    used = core.Used()
    lo = np.array([-3.0 if n == "exposure" else -1.0 for n in names])
    hi = -lo
    cache = {}

    def loss(x):
        key = tuple(np.round(x, 6))
        if key not in cache:
            vals = {n: float(v) * _scaled(n) for n, v in zip(names, x)}
            d = lab_signature(_render(base, vals, src_small, used)) - target
            cache[key] = float(d @ d + pull * (x @ x))
        return cache[key]

    def explore(x, fx, step):
        for i in range(len(x)):
            for sgn in (1, -1):
                y = x.copy()
                y[i] = np.clip(y[i] + sgn * step[i], lo[i], hi[i])
                fy = loss(y)
                if fy < fx:
                    x, fx = y, fy
                    break
        return x, fx

    x = np.zeros(len(names))
    fx = loss(x)
    step = np.array([0.5 if n == "exposure" else 0.25 for n in names])
    while step.max() > tol and len(cache) < max_evals:
        y, fy = explore(x, fx, step)
        if fy < fx:
            while len(cache) < max_evals:                  # pattern moves along the improving direction
                z = np.clip(y + (y - x), lo, hi)
                x, fx = y, fy
                y, fy = explore(z, loss(z), step)
                if fy >= fx:
                    break
        else:
            step = step / 2
    return {n: float(v) * _scaled(n) for n, v in zip(names, x)}, fx, len(cache)


def match_sliders(a):
    """Fit, round, scale the chroma sliders by --amount, set them on `a`; returns the match report."""
    names = [s.strip() for s in (a.sliders or ",".join(FIT_DEFAULT)).split(",") if s.strip()]
    bad = [n for n in names if n not in FIT_ALLOWED]
    if bad:
        raise SystemExit(f"--sliders: {', '.join(bad)} cannot be fitted; choose from {', '.join(FIT_ALLOWED)}")
    if not 0 <= a.amount <= 2:
        raise SystemExit("--amount is 0..2 (1 = the fitted look)")
    src, ref = core.load(a.input), core.load(a.match)
    s_small, r_small = small_copy(src, a.fit_size), small_copy(ref, a.fit_size)
    base = {n: getattr(a, n) for n in SLIDERS if n not in names}
    fitted, residual, evals = fit_sliders(s_small, r_small, names, base)
    vals = {}
    for n in names:
        v = fitted[n] * (a.amount if n in CHROMA else 1.0)
        vals[n] = round(v, 2) if n == "exposure" else round(v, 1)
        setattr(a, n, vals[n] + 0.0)
    out_small = _render(base, vals, s_small, core.Used())
    before = hist_overlap(s_small.color(), r_small.color())
    after = hist_overlap(out_small, r_small.color())
    rms = float(np.sqrt(np.mean((lab_signature(out_small) - lab_signature(r_small.color())) ** 2)))
    warn = []
    if rms > SCENE_RMS or after[0] < SCENE_L or after[1] < SCENE_AB:
        warn.append(f"the reference looks like a different scene (Lab signature still {rms:.1f} apart after the "
                    f"fit, a/b histogram overlap {after[1]:.2f}): statistics matching then copies the other "
                    "scene's content, not its grade, and usually looks worse than no edit. Use a reference of "
                    "the same or a similar scene, or lower --amount.")
    return {"reference": str(a.match), "sliders": vals, "amount": a.amount, "fitted_on": a.fit_size,
            "residual_rms_lab": round(rms, 2), "evals": evals,
            "overlap_before": {"L": round(before[0], 3), "ab": round(before[1], 3)},
            "overlap_after": {"L": round(after[0], 3), "ab": round(after[1], 3)}, "warnings": warn}


SCENE_RMS = 2.5      # Lab units; set from the bake-off in ai-docs/notes/bakeoff/camraw-match-2026-11-20.md
SCENE_AB = 0.5       # a,b histogram overlap after the fit
SCENE_L = 0.5        # L histogram overlap after the fit


def replay_line(a):
    parts = [f"--{n} {getattr(a, n):g}" for n in SLIDERS if getattr(a, n)]
    src = f'"{a.input}"' if " " in str(a.input) else str(a.input)
    return f"phw.py camraw {src} " + " ".join(parts)


def cmd_camraw(a):
    match = None
    if getattr(a, "match", None):
        match = match_sliders(a)
        for w in match["warnings"]:
            print(f"warning: {w}", file=sys.stderr)
    for n in ("temp", "tint", "contrast", "highlights", "shadows", "whites", "blacks", "texture", "clarity",
              "dehaze", "vibrance", "saturation"):
        if not -100 <= getattr(a, n) <= 100:
            raise SystemExit(f"--{n} is a Camera Raw slider: -100 to 100")
    if not -5 <= a.exposure <= 5:
        raise SystemExit("--exposure is in stops: -5 to 5")
    steps = camraw_steps(a)
    if not steps:
        if match:
            raise SystemExit("camraw --match: the fit left every slider at 0; the source already matches")
        raise SystemExit("camraw: every slider is 0; nothing to do")
    if match:   # the fitted values ride along in the recipe; the steps themselves are a plain camraw call
        steps[0]["params"]["camraw"] = {"sliders": {n: getattr(a, n) for n in SLIDERS if getattr(a, n)},
                                        "matched_to": match["reference"], "amount": match["amount"]}
    r = edit_command(a, "camraw", steps)
    r["command"] = "camraw"
    if match:
        r["match"] = match
        r["replay"] = replay_line(a)
    return r


def add_commands(sub, edit=None):
    p = sub.add_parser("camraw", help="Camera Raw Basic panel in one step: temp, tint, exposure, contrast, "
                                      "highlights, shadows, whites, blacks, texture, clarity, dehaze, vibrance, saturation")
    p.add_argument("input")
    for n in ("temp", "tint", "contrast", "highlights", "shadows", "whites", "blacks", "texture", "clarity",
              "dehaze", "vibrance", "saturation"):
        p.add_argument(f"--{n}", type=float, default=0.0, help="-100 to 100")
    p.add_argument("--exposure", type=float, default=0.0, help="stops, -5 to 5")
    p.add_argument("--match", help="reference image: fit the sliders so the result takes on its look "
                                   "(after PREEN, arXiv:2610.36896); the fitted values are printed and recorded")
    p.add_argument("--amount", type=float, default=1.0, help="with --match: scales temp, tint, vibrance, "
                                                              "saturation (0..2, default 1)")
    p.add_argument("--sliders", help="with --match: which sliders to fit, comma separated (default "
                                     + ",".join(FIT_DEFAULT) + "; highlights and shadows also allowed)")
    p.add_argument("--fit-size", type=int, default=160, help="with --match: long side of the copies fitted on")
    p.add_argument("-o", "--output")
    p.add_argument("--recipe")
    p.add_argument("--bits", type=int, choices=(8, 16))
    p.set_defaults(fn=cmd_camraw)


OPS.update({"camraw.whites_blacks": op_whites_blacks, "camraw.contrast": op_contrast_s})
core.EXTRA_COMMANDS.append(add_commands)
core.DOCTOR_GROUPS.append(lambda: {
    "camraw (Camera Raw Basic panel)": (1, "own NumPy"),
    "HEIC/HEIF read": (2, "pillow-heif") if probe("pillow_heif") else (0, "missing: pip install pillow-heif"),
    "JPEG XL read": (2, "pillow-jxl-plugin") if probe("pillow_jxl") else (0, "missing: pip install pillow-jxl-plugin"),
    "camera raw read": (2, "rawpy (LibRaw)") if probe("rawpy") else (0, "missing: pip install rawpy"),
    "C2PA verify": (2, "c2patool") if shutil.which("c2patool") else (0, "missing: c2patool (detection is rung 1)"),
})
