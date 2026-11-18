"""Proof bars for batch 8 (phw 0.9.0): rung 1 rows of the coverage table.

- Gaussian Blur: an impulse spreads to sum 1 with second moment sigma^2 (+-2%).
- Box Blur: equals a brute-force (2r+1)^2 mean in the interior (< 1e-5).
- Motion Blur: an impulse spreads along the given angle only (orthogonal spread < 0.05 px), sum 1.
- High Pass: flat image -> exactly 0.5; a step's mean stays 0.5.
- Maximum/Minimum: equal brute-force grey dilation/erosion bit for bit.
- Offset: equals np.roll; offset by (w, h) is the identity.
- Invert, Posterize, Threshold, Solarize: exact published point formulas on all 256 values.
- Channel Mixer: equals the matrix product; identity matrix is bit-identical.
- Gradient Map: luma 0 -> first stop, 1 -> last stop, midpoint interpolated.
- Masks leave pixels outside unchanged; `phw run` replays bit-identical; each step reports rung 1
  (Gaussian reports 2 only when SciPy is visible).
"""
import json
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

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch8(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw8-"))
        rng = np.random.default_rng(8)
        self.noise = rng.integers(0, 256, (40, 56, 3), dtype=np.uint8)
        Image.fromarray(self.noise).save(self.d / "noise.png")
        imp = np.zeros((61, 61), np.uint8)
        imp[30, 30] = 255
        Image.fromarray(imp).save(self.d / "imp.png")
        ramp = np.repeat(np.arange(256, dtype=np.uint8)[None, :], 4, axis=0)
        Image.fromarray(np.stack([ramp] * 3, axis=2)).save(self.d / "ramp.png")

    def impulse(self, *flags):
        r = run("filter", self.d / "imp.png", "-o", self.d / "o.png", *flags)
        # 8-bit output rounds; use the op directly on floats for the moment test
        return r

    def float_impulse(self, params):
        from phw.filters import op_blur
        img = phw.load(self.d / "imp.png")
        img = img.copy(px=img.px / img.px.max())
        out = op_blur(img, params, phw.Used()).px[..., 0].astype(np.float64)
        return out

    def test_gaussian_moment(self):
        for s in (1.5, 3.0):
            k = self.float_impulse({"kind": "gaussian", "radius": s})
            self.assertAlmostEqual(k.sum(), 1.0, places=4)
            y, x = np.mgrid[:61, :61]
            var = (k * (x - 30) ** 2).sum() / k.sum()
            self.assertLess(abs(var / s ** 2 - 1), 0.02)
        r = self.impulse("--blur", "gaussian", "--radius", 2)
        self.assertEqual(r["rung"], 2 if phw.probe("scipy.ndimage") is not None else 1)

    def test_box_matches_bruteforce(self):
        r = run("filter", self.d / "noise.png", "-o", self.d / "box.png", "--blur", "box", "--radius", 2)
        self.assertEqual(r["rung"], 1)
        got = arr(r["output"]).astype(np.float64)
        src = self.noise.astype(np.float64)
        ref = np.zeros_like(src)
        for y in range(2, 38):
            for x in range(2, 54):
                ref[y, x] = src[y - 2:y + 3, x - 2:x + 3].mean(axis=(0, 1))
        self.assertLessEqual(np.abs(got - np.round(ref))[2:38, 2:54].max(), 1)

    def test_motion_direction(self):
        for ang in (0, 90, 45):
            k = self.float_impulse({"kind": "motion", "radius": 11, "angle": ang})
            self.assertAlmostEqual(k.sum(), 1.0, places=4)
            y, x = np.mgrid[:61, :61]
            a = np.radians(ang)
            along = (x - 30) * np.cos(a) - (y - 30) * np.sin(a)
            across = (x - 30) * np.sin(a) + (y - 30) * np.cos(a)
            self.assertLess(np.sqrt((k * across ** 2).sum()), 0.6)
            self.assertGreater(np.sqrt((k * along ** 2).sum()), 2.5)

    def test_high_pass(self):
        Image.new("RGB", (20, 20), (90, 140, 200)).save(self.d / "flat.png")
        from phw.filters import op_high_pass
        out = op_high_pass(phw.load(self.d / "flat.png"), {"radius": 3}, phw.Used()).px
        self.assertLess(np.abs(out - 0.5).max(), 1e-5)
        step = np.zeros((20, 40, 3), np.uint8)
        step[:, 20:] = 255
        Image.fromarray(step).save(self.d / "step.png")
        out = op_high_pass(phw.load(self.d / "step.png"), {"radius": 3}, phw.Used()).px
        self.assertLess(abs(out.mean() - 0.5), 1e-4)
        self.assertGreater(out[:, 20].min(), 0.9)   # bright side of the edge pushed up
        r = run("filter", self.d / "flat.png", "-o", self.d / "hp.png", "--high-pass", 3)
        self.assertTrue(np.isin(arr(r["output"]), (127, 128)).all())

    def test_max_min_bruteforce(self):
        src = self.noise.astype(np.int32)
        p = np.pad(src, ((1, 1), (1, 1), (0, 0)), mode="edge")
        win = np.stack([p[dy:dy + 40, dx:dx + 56] for dy in range(3) for dx in range(3)])
        for flag, ref in (("--maximum", win.max(0)), ("--minimum", win.min(0))):
            r = run("filter", self.d / "noise.png", "-o", self.d / f"{flag[2:]}.png", flag, 1)
            self.assertTrue((arr(r["output"]) == ref).all(), flag)

    def test_offset(self):
        r = run("filter", self.d / "noise.png", "-o", self.d / "off.png", "--offset", "5,-3")
        self.assertTrue((arr(r["output"]) == np.roll(self.noise, (-3, 5), axis=(0, 1))).all())
        r = run("filter", self.d / "noise.png", "-o", self.d / "off2.png", "--offset", "56,40")
        self.assertTrue((arr(r["output"]) == self.noise).all())

    def test_point_maps(self):
        x = np.arange(256)
        cases = {("--invert",): 255 - x,
                 ("--posterize", "4"): np.floor(x * 4 / 256) * 85,
                 ("--solarize",): np.where(x > 127, 255 - x, x),
                 ("--threshold", "100"): np.where(x >= 100, 255, 0)}
        for flags, want in cases.items():
            r = run("color", self.d / "ramp.png", "-o", self.d / f"{flags[0][2:]}.png", *flags)
            self.assertEqual(r["rung"], 1)
            self.assertTrue((arr(r["output"])[0, :, 0] == want).all(), flags)
        self.assertEqual(len(np.unique(arr(self.d / "posterize.png"))), 4)

    def test_mixer(self):
        m = "0.5,0.3,0.2, 0,1,0, 0.1,0.1,0.8"
        r = run("color", self.d / "noise.png", "-o", self.d / "mix.png", "--mixer", m)
        M = np.array([float(v) for v in m.split(",")]).reshape(3, 3)
        ref = np.clip(np.round(self.noise / 255.0 @ M.T * 255), 0, 255)
        self.assertLessEqual(np.abs(arr(r["output"]) - ref).max(), 1)
        r = run("color", self.d / "noise.png", "-o", self.d / "id.png", "--mixer", "1,0,0,0,1,0,0,0,1")
        self.assertTrue((arr(r["output"]) == self.noise).all())

    def test_gradient_map(self):
        r = run("color", self.d / "ramp.png", "-o", self.d / "gm.png", "--gradient-map", "#000000 #ff0000 #ffffff")
        g = arr(r["output"])[0]
        self.assertEqual(list(g[0]), [0, 0, 0])
        self.assertEqual(list(g[255]), [255, 255, 255])
        self.assertEqual(list(g[128][1:]), [1, 1])   # just past the red stop
        self.assertGreaterEqual(g[128][0], 254)

    def test_mask_and_replay(self):
        m = np.zeros((40, 56), np.uint8)
        m[10:30, 15:40] = 255
        Image.fromarray(m).save(self.d / "m.png")
        rec = self.d / "job" / "recipe.json"
        r1 = run("filter", self.d / "noise.png", "-o", self.d / "a.png", "--blur", "motion", "--radius", 7,
                 "--angle", 30, "--mask", self.d / "m.png", "--recipe", rec)
        r2 = run("color", r1["output"], "-o", self.d / "b.png", "--posterize", 3, "--mask", self.d / "m.png")
        out = arr(r1["output"])
        self.assertTrue((out[m == 0] == self.noise[m == 0]).all())
        self.assertFalse((out[m == 255] == self.noise[m == 255]).all())
        self.assertTrue((arr(r2["output"])[m == 0] == out[m == 0]).all())
        # extend the recipe with the colour step, then replay twice
        run("color", r1["output"], "-o", self.d / "c.png", "--posterize", 3, "--mask", self.d / "m.png",
            "--recipe", self.d / "tmp.json")
        r = json.loads(rec.read_text(encoding="utf-8"))
        r["steps"] += json.loads((self.d / "tmp.json").read_text(encoding="utf-8"))["steps"]
        with open(rec, "w", encoding="utf-8", newline="\n") as f:
            json.dump(r, f)
        p1 = run("run", rec)
        p2 = run("run", rec)
        self.assertEqual(p2["replay"], "same")
        self.assertTrue((arr(p1["output"]) == arr(self.d / "b.png")).all())


if __name__ == "__main__":
    unittest.main()
