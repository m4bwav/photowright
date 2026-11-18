"""Proof bars for phw batch 2: select, mask, cutout, layers (blend modes), open/save (PSD, ORA).

Run: python -m unittest discover -s tests            (all rungs)
     PHW_RUNG_MAX=1 python -m unittest discover -s tests   (rung 2 hidden)
GIMP 3 check runs when gimp-console is found (set PHW_SKIP_GIMP=1 to skip, it takes ~30 s per file).
"""
import json
import math
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import phw  # noqa: E402

RUNG_MAX = phw.rung_max()
warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def mask_of(path):
    return np.asarray(Image.open(path).convert("L"), np.float32) / 255.0


# ---------------------------------------------------------------- independent scalar references
def r_dodge(b, s):
    return 0.0 if b == 0 else 1.0 if s == 1 else min(1.0, b / (1 - s))


def r_burn(b, s):
    return 1.0 if b == 1 else 0.0 if s == 0 else 1 - min(1.0, (1 - b) / s)


def r_hard(b, s):
    return b * 2 * s if s <= 0.5 else 1 - (1 - b) * (1 - (2 * s - 1))


def r_soft(b, s):
    if s <= 0.5:
        return b - (1 - 2 * s) * b * (1 - b)
    d = ((16 * b - 12) * b + 4) * b if b <= 0.25 else math.sqrt(b)
    return b + (2 * s - 1) * (d - b)


SCALAR = {
    "normal": lambda b, s: s,
    "multiply": lambda b, s: b * s,
    "screen": lambda b, s: 1 - (1 - b) * (1 - s),
    "overlay": lambda b, s: r_hard(s, b),
    "darken": min, "lighten": max,
    "color-dodge": r_dodge, "color-burn": r_burn,
    "hard-light": r_hard, "soft-light": r_soft,
    "difference": lambda b, s: abs(b - s),
    "exclusion": lambda b, s: b + s - 2 * b * s,
    "linear-burn": lambda b, s: max(0.0, b + s - 1),
    "linear-dodge": lambda b, s: min(1.0, b + s),
    "subtract": lambda b, s: max(0.0, b - s),
    "divide": lambda b, s: (0.0 if b == 0 else 1.0) if s == 0 else min(1.0, b / s),
    "linear-light": lambda b, s: min(1.0, max(0.0, b + 2 * s - 1)),
    "vivid-light": lambda b, s: r_burn(b, 2 * s) if s <= 0.5 else r_dodge(b, 2 * (s - 0.5)),
    "pin-light": lambda b, s: min(b, 2 * s) if s <= 0.5 else max(b, 2 * s - 1),
    "hard-mix": lambda b, s: 1.0 if b + s >= 1 else 0.0,
}


def r_lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


def r_clip(c):
    l, n, x = r_lum(c), min(c), max(c)
    if n < 0:
        c = [l + (v - l) * l / (l - n) for v in c]
    if x > 1:
        c = [l + (v - l) * (1 - l) / (x - l) for v in c]
    return c


def r_setlum(c, l):
    d = l - r_lum(c)
    return r_clip([v + d for v in c])


def r_sat(c):
    return max(c) - min(c)


def r_setsat(c, s):
    idx = sorted(range(3), key=lambda i: c[i])
    mn, md, mx = idx
    out = [0.0, 0.0, 0.0]
    if c[mx] > c[mn]:
        out[md] = (c[md] - c[mn]) * s / (c[mx] - c[mn])
        out[mx] = s
    return out


NONSEP = {
    "hue": lambda b, s: r_setlum(r_setsat(s, r_sat(b)), r_lum(b)),
    "saturation": lambda b, s: r_setlum(r_setsat(b, r_sat(s)), r_lum(b)),
    "color": lambda b, s: r_setlum(s, r_lum(b)),
    "luminosity": lambda b, s: r_setlum(b, r_lum(s)),
    "darker-color": lambda b, s: s if r_lum(s) < r_lum(b) else b,
    "lighter-color": lambda b, s: s if r_lum(s) > r_lum(b) else b,
}


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def png(self, a, name, mode=None):
        p = self.d / name
        Image.fromarray(a, mode).save(p)
        return p

    def recipe(self, r, name="l.json"):
        p = self.d / name
        p.write_text(json.dumps(r), encoding="utf-8")
        return p


# ---------------------------------------------------------------- blend modes
class TestBlend(Base):
    def test_separable_modes_match_formula_on_grid(self):
        g = np.linspace(0, 1, 17, dtype=np.float32)
        cb, cs = np.meshgrid(g, g, indexing="ij")
        cb3, cs3 = np.repeat(cb[..., None], 3, 2), np.repeat(cs[..., None], 3, 2)
        for mode, fn in SCALAR.items():
            got = phw.blend(mode, cb3, cs3)[..., 0]
            ref = np.vectorize(lambda b, s: fn(float(b), float(s)))(cb, cs)
            self.assertLess(float(np.abs(got - ref).max()), 1e-5, mode)

    def test_nonseparable_modes_match_formula(self):
        rng = np.random.default_rng(3)
        cb = rng.uniform(0, 1, (12, 12, 3)).astype(np.float32)
        cs = rng.uniform(0, 1, (12, 12, 3)).astype(np.float32)
        cs[0, 0] = [0.5, 0.5, 0.5]  # grey: zero saturation
        cb[1, 1] = [0.2, 0.2, 0.9]  # ties
        for mode, fn in NONSEP.items():
            got = phw.blend(mode, cb, cs)
            ref = np.array([[fn(list(map(float, cb[i, j])), list(map(float, cs[i, j]))) for j in range(12)]
                            for i in range(12)])
            self.assertLess(float(np.abs(got - ref).max()), 1e-5, mode)

    def test_alpha_compositing_formula(self):
        cb, cs = np.full((1, 1, 3), 0.8, np.float32), np.full((1, 1, 3), 0.4, np.float32)
        ab, as_ = np.full((1, 1, 1), 0.5, np.float32), np.full((1, 1, 1), 0.25, np.float32)
        c, a = phw.composite_over(cb, ab, cs, as_, "multiply")
        b = 0.8 * 0.4
        cs2 = (1 - 0.5) * 0.4 + 0.5 * b
        ao = 0.25 + 0.5 * 0.75
        self.assertAlmostEqual(float(a[0, 0, 0]), ao, 6)
        self.assertAlmostEqual(float(c[0, 0, 0]), (0.25 * cs2 + 0.5 * 0.8 * 0.75) / ao, 6)

    def test_layers_command_8bit_matches_formula(self):
        g = (np.linspace(0, 255, 16).round()).astype(np.uint8)
        b8 = np.repeat(np.repeat(g[:, None], 16, 1)[..., None], 3, 2)
        s8 = np.repeat(np.repeat(g[None, :], 16, 0)[..., None], 3, 2)
        self.png(b8, "b.png", "RGB")
        self.png(s8, "s.png", "RGB")
        for mode in ("multiply", "screen", "overlay", "soft-light", "color-dodge", "difference", "linear-light",
                     "hard-mix", "color", "luminosity"):
            rp = self.recipe({"version": 1, "kind": "layers", "canvas": {"width": 16, "height": 16},
                              "layers": [{"file": "b.png"}, {"file": "s.png", "blend": mode}]}, f"{mode}.json")
            out = np.asarray(Image.open(run("layers", rp)["output"]).convert("RGB"), np.float32) / 255
            fn = SCALAR.get(mode)
            if fn:
                ref = np.vectorize(lambda b, s: fn(float(b), float(s)))(b8[..., 0] / 255.0, s8[..., 0] / 255.0)
            else:
                ref = np.array([[NONSEP[mode]([b8[i, j, 0] / 255.0] * 3, [s8[i, j, 0] / 255.0] * 3)[0]
                                 for j in range(16)] for i in range(16)])
            self.assertLessEqual(float(np.abs(out[..., 0] - ref).max()), 0.5 / 255 + 1e-6, mode)

    def test_linear_space_option(self):
        self.png(np.zeros((4, 4, 3), np.uint8), "k.png", "RGB")
        self.png(np.full((4, 4, 3), 255, np.uint8), "w.png", "RGB")
        out = {}
        for space in ("gamma", "linear"):
            rp = self.recipe({"version": 1, "kind": "layers", "space": space, "canvas": {"width": 4, "height": 4},
                              "layers": [{"file": "k.png"}, {"file": "w.png", "opacity": 0.5}]}, f"{space}.json")
            out[space] = np.asarray(Image.open(run("layers", rp)["output"]))[0, 0, 0]
        self.assertIn(int(out["gamma"]), (127, 128))
        self.assertEqual(int(out["linear"]), round(float(phw.to_enc(np.float32(0.5))) * 255))  # 188

    def test_unknown_mode_refused(self):
        with self.assertRaises(ValueError):
            phw.blend("dissolve", np.zeros((1, 1, 3)), np.zeros((1, 1, 3)))


# ---------------------------------------------------------------- masks
class TestMasks(Base):
    def setUp(self):
        super().setUp()
        self.used = phw.Used()

    def steps(self, *st, img=None, mask=None, shape=(40, 50)):
        return phw.apply_mask_steps(img, mask, [{"op": f"mask.{o}", "params": p} for o, p in st], self.used,
                                    shape=shape if img is None and mask is None else None)

    def test_shapes_exact(self):
        m = self.steps(("rect", {"box": [5, 6, 10, 8]}))
        self.assertEqual(m.sum(), 80)
        self.assertEqual(m[6:14, 5:15].min(), 1)
        e = self.steps(("ellipse", {"box": [0, 0, 41, 31]}))
        self.assertLess(abs(e.sum() - math.pi * 20.5 * 15.5) / (math.pi * 20.5 * 15.5), 0.03)
        self.assertTrue(np.array_equal(e[:, :41], e[:, :41][:, ::-1]))
        t = self.steps(("polygon", {"points": [[0, 0], [20, 0], [0, 20]]}))
        self.assertLess(abs(t.sum() - 231), 25)  # 21*22/2 lattice points

    def test_grow_shrink_numeric(self):
        m = self.steps(("rect", {"box": [15, 12, 10, 8]}))
        g = self.steps(("grow", {"px": 3}), mask=m)
        yy, xx = np.mgrid[:40, :50]
        dx = np.maximum(0, np.maximum(15 - xx, xx - 24))
        dy = np.maximum(0, np.maximum(12 - yy, yy - 19))
        self.assertTrue(np.array_equal(g, (dx * dx + dy * dy <= 9 + 3).astype(np.float32)))
        self.assertTrue(np.array_equal(self.steps(("shrink", {"px": 3}), mask=g), m))  # closing of a box
        s = self.steps(("shrink", {"px": 2}), mask=m)
        self.assertEqual(s.sum(), 6 * 4)
        full = np.ones((10, 10), np.float32)
        self.assertEqual(self.steps(("shrink", {"px": 3}), mask=full).min(), 1)  # border stays selected

    def test_morph_rungs_agree(self):
        if phw.probe("cv2") is None:
            self.skipTest("OpenCV absent or hidden: one rung only")
        rng = np.random.default_rng(5)
        m = (rng.uniform(0, 1, (30, 30)) > 0.8).astype(np.float32)
        a = phw.morph(m, 2, True)
        old = os.environ.get("PHW_RUNG_MAX")
        os.environ["PHW_RUNG_MAX"] = "1"
        try:
            b = phw.morph(m, 2, True)
            self.assertTrue(np.array_equal(a, b))
            self.assertTrue(np.array_equal(phw.morph(1 - m, 2, False), 1 - b))
        finally:
            if old is None:
                os.environ.pop("PHW_RUNG_MAX")
            else:
                os.environ["PHW_RUNG_MAX"] = old

    def test_feather_invert_combine(self):
        a = self.steps(("rect", {"box": [0, 0, 30, 40]}))
        b = self.steps(("rect", {"box": [20, 0, 30, 40]}))
        add = self.steps(("rect", {"box": [0, 0, 30, 40]}), ("rect", {"box": [20, 0, 30, 40], "mode": "add"}))
        sub = self.steps(("rect", {"box": [0, 0, 30, 40]}), ("rect", {"box": [20, 0, 30, 40], "mode": "subtract"}))
        its = self.steps(("rect", {"box": [0, 0, 30, 40]}), ("rect", {"box": [20, 0, 30, 40], "mode": "intersect"}))
        self.assertEqual((add.sum(), sub.sum(), its.sum()), (50 * 40, 20 * 40, 10 * 40))
        self.assertTrue(np.array_equal(add, np.maximum(a, b)))
        inv = self.steps(("invert", {}), mask=a)
        self.assertTrue(np.array_equal(inv + a, np.ones_like(a)))
        f = self.steps(("feather", {"sigma": 2}), mask=a)
        self.assertLess(abs(f.sum() - a.sum()) / a.sum(), 0.01)  # blur keeps the area (reflect edges)
        self.assertTrue(0.4 < f[20, 29] < 0.6 and f[20, 35] < 0.05 and f[20, 10] > 0.99)

    def test_colour_luma_flood_edge(self):
        a = np.zeros((20, 30, 3), np.uint8)
        a[:, :] = (20, 40, 200)
        a[:, 10:12] = (250, 250, 250)  # wall splits two blue regions
        a[5:9, 20:25] = (200, 30, 30)
        img = phw.load(self.png(a, "c.png", "RGB"))
        blue = self.steps(("color", {"color": [20 / 255, 40 / 255, 200 / 255], "tol": 5}), img=img)
        self.assertEqual(blue.sum(), 20 * 28 - 20)
        pick = self.steps(("color", {"pick": [22, 6], "tol": 5}), img=img)
        self.assertEqual(pick.sum(), 20)
        flood = self.steps(("flood", {"seed": [2, 2], "tol": 5}), img=img)
        self.assertEqual(flood.sum(), 20 * 10)
        luma = self.steps(("luma", {"range": [0.9, 1.0]}), img=img)
        self.assertEqual(luma.sum(), 40)
        edge = self.steps(("edge", {"threshold": 0.3}), img=img)
        self.assertEqual(edge[:, 2:8].sum(), 0)
        self.assertTrue(edge[:, 9:13].sum() > 0)

    def test_select_cli_recipe_replay_and_no_overwrite(self):
        a = np.zeros((20, 30, 3), np.uint8)
        a[5:15, 5:25] = 255
        src = self.png(a, "s.png", "RGB")
        rec = self.d / "m" / "recipe.json"
        r = run("select", src, "--luma", "0.5,1", "--grow", "1", "--feather", "0.8", "--recipe", rec)
        self.assertEqual(Image.open(r["output"]).mode, "L")
        r2 = run("select", src, "--luma", "0.5,1")
        self.assertNotEqual(r["output"], r2["output"])
        rr = run("run", rec)
        self.assertEqual(rr["kind"], "mask")
        self.assertTrue(np.array_equal(mask_of(rr["output"]), mask_of(r["output"])))
        m = run("mask", r2["output"], "--rect", "0,0,3,3", "--invert")
        mm = mask_of(m["output"])
        self.assertEqual(mm[0, 0], 0)
        self.assertEqual(mm[10, 10], 0)
        self.assertEqual(mm[18, 28], 1)
        new = run("mask", "--size", "8,6", "--ellipse", "0,0,8,6")
        self.assertEqual(mask_of(new["output"]).shape, (6, 8))
        os.remove(new["output"])

    def test_nothing_outside_mask_changes(self):
        rng = np.random.default_rng(2)
        a = (rng.uniform(0, 1, (24, 32, 3)) * 255).astype(np.uint8)
        src = self.png(a, "p.png", "RGB")
        mk = run("select", src, "--ellipse", "4,4,20,14", "--feather", "1.5")["output"]
        out = np.asarray(Image.open(run("adjust", src, "--exposure", "1", "--mask", mk)["output"]))
        zero = mask_of(mk) == 0
        self.assertTrue(np.array_equal(out[zero], a[zero]))
        self.assertFalse(np.array_equal(out[~zero], a[~zero]))


# ---------------------------------------------------------------- cutout
class TestCutout(Base):
    def scene(self):
        a = np.zeros((60, 80, 3), np.uint8)
        a[:] = (40, 180, 60)
        yy, xx = np.mgrid[:60, :80]
        disc = (yy - 30) ** 2 + (xx - 40) ** 2 <= 18 ** 2
        a[disc] = (200, 40, 40)
        a[disc & (xx > 40)] = (230, 200, 50)
        return a, disc

    def test_key_cutout(self):
        a, disc = self.scene()
        src = self.png(a, "k.png", "RGB")
        r = run("cutout", src, "--method", "key", "--mask-out", self.d / "km.png")
        out = np.asarray(Image.open(r["output"]))
        self.assertEqual(out.shape[2], 4)
        self.assertTrue(np.array_equal(out[..., :3], a))  # colour untouched, only alpha set
        iou = ((out[..., 3] > 127) & disc).sum() / ((out[..., 3] > 127) | disc).sum()
        self.assertGreater(iou, 0.99)
        self.assertEqual(r["rung"], max(1, r["rung"]))
        self.assertTrue(Path(r["mask_output"]).exists())

    def test_grabcut_cutout(self):
        if phw.probe("cv2") is None:
            self.skipTest("OpenCV absent or hidden (rung 1): GrabCut not available")
        a, disc = self.scene()
        rng = np.random.default_rng(0)
        a = np.clip(a + rng.normal(0, 6, a.shape), 0, 255).astype(np.uint8)
        r = run("cutout", self.png(a, "g.png", "RGB"), "--method", "grabcut")
        self.assertEqual(r["rung"], 2)
        al = np.asarray(Image.open(r["output"]))[..., 3] > 127
        self.assertGreater((al & disc).sum() / (al | disc).sum(), 0.95)

    def test_auto_falls_back_at_rung1(self):
        a, _ = self.scene()
        old = os.environ.get("PHW_RUNG_MAX")
        try:
            r = run("--rung-max", "1", "cutout", self.png(a, "f.png", "RGB"))
        finally:
            if old is None:
                os.environ.pop("PHW_RUNG_MAX", None)
            else:
                os.environ["PHW_RUNG_MAX"] = old
        self.assertIn("colour key + border flood", r["tool"])

    def test_birefnet_falls_back_when_server_down(self):
        import urllib.error
        from unittest import mock
        a, _ = self.scene()
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            r = run("cutout", self.png(a, "b.png", "RGB"), "--method", "birefnet")
        self.assertLess(r["rung"], 3)
        self.assertTrue(any(n.startswith("fell back:") for n in r["notes"]))


# ---------------------------------------------------------------- layers
def base_recipe(layers, w=40, h=30):
    return {"version": 1, "kind": "layers", "canvas": {"width": w, "height": h}, "layers": layers}


class LayerBase(Base):
    def setUp(self):
        super().setUp()
        rng = np.random.default_rng(4)
        self.bg = (rng.uniform(0, 1, (30, 40, 3)) * 255).astype(np.uint8)
        self.png(self.bg, "bg.png", "RGB")
        m = np.zeros((30, 40), np.uint8)
        m[5:20, 8:30] = 255
        m[10:15, 12:20] = 128
        self.png(m, "m.png", "L")
        self.m = m

    def render(self, layers, name="r.json", **kw):
        rp = self.recipe(dict(base_recipe(layers), **kw), name)
        return np.asarray(Image.open(run("layers", rp)["output"]).convert("RGBA"))


class TestLayers(LayerBase):
    def test_layer_mask_changes_nothing_outside(self):
        for mode in ("normal", "multiply", "difference", "hue"):
            out = self.render([{"file": "bg.png"}, {"type": "fill", "color": [1, 0.2, 0.1], "blend": mode,
                                                     "mask": "m.png"}], f"{mode}.json")
            zero = self.m == 0
            self.assertTrue(np.array_equal(out[..., :3][zero], self.bg[zero]), mode)
            self.assertFalse(np.array_equal(out[..., :3][~zero], self.bg[~zero]), mode)

    def test_clipping_and_groups(self):
        clip = self.render([{"type": "shape", "shape": "rect", "box": [10, 10, 10, 10], "fill": [1, 1, 1],
                             "antialias": 1}, {"type": "fill", "color": [1, 0, 0], "clip": True}])
        self.assertEqual(int((clip[..., 3] > 0).sum()), 100)
        self.assertTrue((clip[10:20, 10:20, :3] == [255, 0, 0]).all())
        mul = [{"type": "fill", "color": [0.5, 0.5, 0.5], "blend": "multiply"}]
        flat = self.render([{"file": "bg.png"}] + mul, "a.json")
        passg = self.render([{"file": "bg.png"}, {"type": "group", "layers": mul}], "b.json")
        iso = self.render([{"file": "bg.png"}, {"type": "group", "blend": "normal", "layers": mul}], "c.json")
        self.assertTrue(np.array_equal(flat, passg))  # pass-through = no group
        self.assertTrue((iso[..., :3] == 128).all())  # isolated: multiply had nothing below it
        hid = self.render([{"file": "bg.png"}, {"type": "fill", "color": [0, 0, 0], "visible": False}], "d.json")
        self.assertTrue(np.array_equal(hid[..., :3], self.bg))

    def test_text_shapes_effects(self):
        out = self.render([{"type": "fill", "color": [1, 1, 1]},
                           {"type": "text", "text": "Hi", "size": 16, "x": 2, "y": 2, "color": [0, 0, 0]},
                           {"type": "shape", "shape": "ellipse", "box": [20, 10, 12, 12], "fill": [0, 0, 1],
                            "effects": {"drop_shadow": {"dx": 3, "dy": 3, "blur": 0, "opacity": 1, "blend": "normal",
                                                        "color": [1, 0, 0]},
                                        "stroke": {"size": 1, "color": [0, 1, 0]}}}])
        self.assertLess(out[2:20, 2:20, 0].min(), 100)  # text drew dark pixels
        self.assertTrue((out[16, 26, :3] == [0, 0, 255]).all())
        self.assertEqual(out[24, 29, 0], 255)  # shadow (offset 3,3) visible below-right
        self.assertEqual(out[24, 29, 1], 0)
        self.assertGreater(out[16, 19, 1], 100)  # stroke just outside the left edge

    def test_bad_mode_and_no_overwrite(self):
        with self.assertRaises(ValueError):
            self.render([{"type": "fill", "blend": "dissolve"}])
        rp = self.recipe(base_recipe([{"type": "fill", "color": [1, 0, 0]}]), "x.json")
        a, b = run("layers", rp)["output"], run("layers", rp)["output"]
        self.assertNotEqual(a, b)


# ---------------------------------------------------------------- layered files
def sample_recipe():
    return base_recipe([
        {"name": "photo", "file": "bg.png"},
        {"name": "Mult", "type": "fill", "color": [0.9, 0.4, 0.2], "blend": "multiply", "opacity": 0.62,
         "mask": {"file": "m.png"}},
        {"name": "Grüppe", "type": "group", "opacity": 0.8, "layers": [
            {"name": "base", "type": "shape", "shape": "ellipse", "box": [5, 5, 25, 18], "fill": [0.2, 0.7, 0.3],
             "blend": "screen"},
            {"name": "clip", "type": "fill", "color": [0, 0, 1], "clip": True, "blend": "overlay", "opacity": 0.5},
            {"name": "hidden", "type": "fill", "color": [1, 1, 0], "visible": False}]},
        {"name": "iso", "type": "group", "blend": "difference", "mask": "m.png", "layers": [
            {"name": "lum", "type": "fill", "color": [0.3, 0.3, 0.3], "blend": "luminosity"}]},
        {"name": "Text", "type": "text", "text": "A", "size": 14, "x": 28, "y": 10, "color": [1, 1, 1]}])


def tree(doc):
    return [(d, l.name, l.group, l.blend, round(l.opacity * 255), l.visible, l.clip,
             None if l.mask is None else (l.mask_x, l.mask_y, l.mask.shape, round(l.mask_default)))
            for l, d in doc.walk()]


class TestLayeredFiles(LayerBase):
    def build(self):
        rp = self.recipe(sample_recipe(), "doc.json")
        used = phw.Used()
        return rp, phw.read_layered(rp, used)

    def check_round_trip(self, ext):
        rp, doc = self.build()
        out = run("save", rp, "-o", self.d / f"doc{ext}")["output"]
        back = phw.read_layered(out, phw.Used())
        self.assertEqual(tree(back), tree(doc))
        if ext == ".psd":  # the own reader, even when psd-tools is installed
            self.assertEqual(tree(phw.read_psd_own(out)), tree(doc))
        for (a, _), (b, _) in zip(doc.walk(), back.walk()):
            if a.mask is not None:
                self.assertLessEqual(float(np.abs(a.mask - b.mask).max()), 0.5 / 255 + 1e-6)
        fa, fb = phw.composite_doc(doc), phw.composite_doc(back)
        self.assertLessEqual(float(np.abs(fa - fb).max()), 2.5 / 255, ext)  # 8-bit layers, 2 quantisations
        return out, doc

    def test_psd_round_trip_own_reader(self):
        out, doc = self.check_round_trip(".psd")
        self.assertEqual(Path(out).read_bytes()[:4], b"8BPS")

    def test_layered_tiff_round_trip(self):
        out, doc = self.check_round_trip(".tif")
        with Image.open(out) as im:  # a plain TIFF reader sees the flat composite
            self.assertEqual(im.size, (doc.width, doc.height))
            self.assertIn(37724, im.tag_v2)
        flat = run("save", self.recipe(sample_recipe(), "d2.json"), "-o", self.d / "flat.tif", "--flat")["output"]
        with Image.open(flat) as im:
            self.assertNotIn(37724, im.tag_v2)

    def test_gimp_opens_layered_tiff(self):
        if os.environ.get("PHW_SKIP_GIMP") or not phw.gimp_console():
            self.skipTest("GIMP 3 (gimp-console) not found or PHW_SKIP_GIMP set: GIMP check skipped")
        rp, doc = self.build()
        out = run("save", rp, "-o", self.d / "g.tif")["output"]
        got = [g["name"] for g in phw.gimp_layers(out) if g["name"] != "Group added by GIMP"]
        want = [l.name for l, _ in doc.walk()]
        self.assertGreaterEqual(len(set(got) & set(want)), len(want) - 1, (got, want))

    def test_ora_round_trip(self):
        out, _ = self.check_round_trip(".ora")
        import zipfile
        with zipfile.ZipFile(out) as z:
            first = z.infolist()[0]
            self.assertEqual((first.filename, first.compress_type), ("mimetype", zipfile.ZIP_STORED))
            self.assertIn("mergedimage.png", z.namelist())

    def test_psd_raw_compression_and_packbits(self):
        rng = np.random.default_rng(9)
        for row in (rng.integers(0, 256, 300), np.r_[np.zeros(200), rng.integers(0, 3, 100), np.full(5, 7)],
                    np.array([1, 1, 2]), np.full(1, 4)):
            row = row.astype(np.uint8)
            self.assertEqual(phw.unpackbits(phw.packbits(row), len(row)), row.tobytes())
        rp, doc = self.build()
        out = run("save", rp, "-o", self.d / "raw.psd", "--psd-compression", "raw")["output"]
        self.assertEqual(tree(phw.read_psd_own(out)), tree(doc))

    def test_psd_tools_reads_phw_psd(self):
        if phw.probe("psd_tools") is None:
            self.skipTest("psd-tools not installed (rung 2): own reader covers phw's files")
        rp, doc = self.build()
        out = run("save", rp, "-o", self.d / "pt.psd")["output"]
        used = phw.Used()
        back = phw.read_layered(out, used)
        self.assertEqual(used.rung(), 2)
        self.assertEqual(tree(back), tree(doc))

    def test_open_extract_and_resave(self):
        rp, doc = self.build()
        psd = run("save", rp, "-o", self.d / "e.psd")["output"]
        r = run("open", psd, "--extract", self.d / "ex")
        self.assertEqual(r["count"], 9)
        again = run("save", r["recipe"], "-o", self.d / "e2.ora")["output"]
        self.assertEqual(tree(phw.read_layered(again, phw.Used())), tree(doc))
        before = Path(psd).read_bytes()
        self.assertNotEqual(run("save", rp, "-o", psd)["output"], psd)  # never overwritten
        self.assertEqual(Path(psd).read_bytes(), before)

    def test_gimp_opens_psd_and_ora(self):
        if os.environ.get("PHW_SKIP_GIMP") or not phw.gimp_console():
            self.skipTest("GIMP 3 (gimp-console) not found or PHW_SKIP_GIMP set: GIMP check skipped")
        rp, doc = self.build()
        want = [(l.name, round(l.opacity * 100, 1), l.group) for l, _ in doc.walk()]
        for ext in (".psd", ".ora"):
            out = run("save", rp, "-o", self.d / f"g{ext}")["output"]
            got = phw.gimp_layers(out)
            got = [g for g in got if g["name"] != "Group added by GIMP"]  # GIMP wraps PSD clipping in a group
            self.assertEqual(sorted((g["name"], round(g["opacity"], 0), g["group"]) for g in got),
                             sorted((n, round(o, 0), gr) for n, o, gr in want), ext)
            modes = {g["name"]: g["mode"] for g in got}
            self.assertEqual(modes["Mult"], "multiply")
            self.assertEqual(modes["clip"], "overlay")
            if ext == ".psd":
                masks = {g["name"]: g["mask"] for g in got}
                self.assertTrue(masks["Mult"] and masks["iso"])
                self.assertEqual(modes["Grüppe"], "pass-through")
                self.assertEqual(modes["iso"], "difference")


if __name__ == "__main__":
    unittest.main()
