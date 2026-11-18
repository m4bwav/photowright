"""Proof bars for batch 10 (phw 0.11.0) plus the module-shadowing guard.

- Module guard: every module in scripts/phw is a module on the package (not a core function of the
  same name), and no module name equals a public core attribute. Session 24 lost `tone` that way.
- Brightness/Contrast: 0,0 identity; 0 and 255 fixed; monotone over all 256 levels; brightness
  raises the mean; contrast +/- raises/lowers the spread.
- Color Balance: zero identity; +red in shadows moves a dark pixel's red more than a bright one's;
  preserve luminosity keeps luma within 1/255.
- Photo Filter: density 0 identity; warming raises R/B of a grey-ish pixel; luma kept within 1/255.
- Selective Color: reds cyan +1 takes pure red to 0 red; greys and pure blue bit-identical.
- Desaturate: equals (max+min)/2 exactly (within rounding) for every pixel of a random image.
- Dehaze: on synthetic haze (I = J t + A (1 - t), t = 0.5) the RMS to J falls below 40% of the hazy RMS.
- Clarity: flat image unchanged; amount 0 identity; local spread of a soft pattern rises.
- Smart Sharpen: removes a sigma 1.5 Gaussian blur better than unsharp mask (RMS to the sharp
  original < 70% of the blurred RMS and below `sharpen`'s).
- Frequency separation: low + high - 0.5 reconstructs within 2/255.
- Pinch/Twirl: outside the inscribed circle within 1/255; pinch + shrinks a centred disc, - grows it;
  twirl leaves concentric rings within 3/255.
- Polar: rows become rings (pixels at one radius agree within 3/255).
- Skew: a vertical line shifts by H tan(angle) between top and bottom within 1 px.
- Mosaic: each cell equals its source mean within 1/255; cell 1 identity.
- Masks keep outside pixels; `phw run` replays the same.
"""
import importlib
import json
import pkgutil
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
from phw import core  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)
Y709 = np.array([0.2126, 0.7152, 0.0722])


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class ModuleShadowing(unittest.TestCase):
    def test_no_module_shadows_a_core_name(self):
        pkg_dir = Path(phw.__file__).parent
        names = [m.name for m in pkgutil.iter_modules([str(pkg_dir)])]
        self.assertIn("grading", names)
        core_public = {n for n in dir(core) if not n.startswith("_")}
        for n in names:
            if n == "core":
                continue
            self.assertNotIn(n, core_public, f"module phw.{n} shares a name with core.{n}; "
                             "`from .core import *` would shadow it")
            mod = importlib.import_module(f"phw.{n}")
            self.assertTrue(type(getattr(phw, n, mod)).__name__ == "module",
                            f"phw.{n} is not the module (shadowed)")


class Batch10(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw10-"))
        self.rng = np.random.default_rng(10)
        self.noise = self.rng.integers(0, 256, (40, 56, 3), dtype=np.uint8)
        Image.fromarray(self.noise).save(self.d / "noise.png")
        ramp = np.tile(np.arange(256, dtype=np.uint8), (4, 1))
        Image.fromarray(np.stack([ramp] * 3, axis=2)).save(self.d / "ramp.png")
        self.o = 0

    def out(self):
        self.o += 1
        return self.d / f"o{self.o}.png"

    def save(self, name, a):
        Image.fromarray(np.asarray(a, np.uint8)).save(self.d / name)
        return self.d / name

    # ------------------------------------------------------------ brightness/contrast
    def test_brightness_contrast(self):
        r = run("grade", self.d / "ramp.png", "-o", self.out(), "--brightness", 0.5)
        a = arr(r["output"])[0, :, 0]
        self.assertEqual((a[0], a[255]), (0, 255))
        self.assertTrue((np.diff(a) >= 0).all())
        self.assertGreater(a.mean(), 127.5 + 15)
        r = run("grade", self.d / "ramp.png", "-o", self.out(), "--contrast", 0.6)
        b = arr(r["output"])[0, :, 0]
        self.assertEqual((b[0], b[255]), (0, 255))
        self.assertTrue((np.diff(b) >= 0).all())
        self.assertGreater(np.abs(b - 127.5).mean(), np.abs(np.arange(256) - 127.5).mean() + 5)
        r = run("grade", self.d / "ramp.png", "-o", self.out(), "--contrast", -0.6)
        c = arr(r["output"])[0, :, 0]
        self.assertTrue((np.diff(c) >= 0).all())
        self.assertLess(np.abs(c - 127.5)[20:236].mean(), np.abs(np.arange(256) - 127.5)[20:236].mean() - 5)
        self.assertEqual(r["rung"], 1)

    # ------------------------------------------------------------ color balance / photo filter
    def test_color_balance(self):
        im = np.zeros((4, 4, 3), np.uint8)
        im[:2] = 50
        im[2:] = 200
        p = self.save("cb.png", im)
        r = run("grade", p, "-o", self.out(), "--balance-shadows", "0.8,0,0", "--no-preserve")
        a = arr(r["output"])
        self.assertGreater(a[0, 0, 0] - 50, 3 * max(1, a[3, 0, 0] - 200))
        r = run("grade", p, "-o", self.out(), "--balance-midtones", "0.5,-0.3,0.4")
        a = arr(r["output"]).astype(float)
        self.assertLessEqual(np.abs((a * Y709).sum(2) - (im * Y709).sum(2)).max(), 1.0)
        self.assertFalse((a == im).all())

    def test_photo_filter(self):
        im = np.full((4, 4, 3), [120, 125, 130], np.uint8)
        p = self.save("pf.png", im)
        r0 = run("grade", p, "-o", self.out(), "--photo-filter", "warming", "--density", 0.0)
        self.assertTrue((arr(r0["output"]) == im).all())
        r = run("grade", p, "-o", self.out(), "--photo-filter", "warming", "--density", 0.5)
        a = arr(r["output"]).astype(float)
        self.assertGreater(a[0, 0, 0] / a[0, 0, 2], 120 / 130 + 0.2)
        self.assertLessEqual(abs((a[0, 0] * Y709).sum() - (im[0, 0] * Y709).sum()), 1.0)

    def test_selective_and_desaturate(self):
        im = np.array([[[255, 0, 0], [128, 128, 128], [0, 0, 255], [200, 60, 40]]], np.uint8)
        p = self.save("sc.png", im)
        r = run("grade", p, "-o", self.out(), "--selective", "reds=1,0,0,0")
        a = arr(r["output"])
        self.assertEqual(a[0, 0, 0], 0)
        self.assertTrue((a[0, 1] == im[0, 1]).all() and (a[0, 2] == im[0, 2]).all())
        self.assertLess(a[0, 3, 0], 200 - 100)
        r = run("grade", self.d / "noise.png", "-o", self.out(), "--desaturate")
        a = arr(r["output"])
        want = (self.noise.max(2).astype(float) + self.noise.min(2)) / 2
        self.assertLessEqual(np.abs(a[..., 0] - want).max(), 0.5 + 1e-9)
        self.assertTrue((a[..., 0] == a[..., 2]).all())

    # ------------------------------------------------------------ detail
    def test_dehaze(self):
        J = np.ones((76, 64, 3))           # top 12 rows: white sky, the airlight source
        cols = [[0.9, 0.2, 0.0], [0.0, 0.6, 0.3], [0.2, 0.0, 0.8], [0.7, 0.7, 0.0]]
        for i, col in enumerate(cols):
            J[12 + (i // 2) * 32:12 + (i // 2 + 1) * 32, (i % 2) * 32:(i % 2 + 1) * 32] = col
        A, t = 0.92, 0.5
        hazy = J * t + A * (1 - t)
        p = self.save("haze.png", np.round(hazy * 255))
        r = run("detail", p, "-o", self.out(), "--dehaze", 1.0, "--dark-radius", 4)
        out = arr(r["output"]) / 255.0
        inner = (slice(24, -6), slice(6, -6))
        rms_h = np.sqrt(((hazy - J)[inner] ** 2).mean())
        rms_o = np.sqrt(((out - J)[inner] ** 2).mean())
        self.assertLess(rms_o, 0.4 * rms_h, (rms_o, rms_h))

    def test_clarity(self):
        flat = self.save("flat.png", np.full((32, 32, 3), 120))
        r = run("detail", flat, "-o", self.out(), "--clarity", 1.0, "--clarity-radius", 4)
        self.assertTrue((arr(r["output"]) == 120).all())
        y, x = np.mgrid[0:64, 0:64]
        soft = 128 + 30 * np.sin(x / 5.0) * np.cos(y / 7.0)
        p = self.save("soft.png", np.repeat(soft[..., None], 3, 2))
        r0 = run("detail", p, "-o", self.out(), "--clarity", 0.0000001)
        self.assertLessEqual(np.abs(arr(r0["output"]) - arr(p)).max(), 0)
        r = run("detail", p, "-o", self.out(), "--clarity", 1.5, "--clarity-radius", 10)
        self.assertGreater(arr(r["output"]).std(), arr(p).std() * 1.2)

    def test_smart_sharpen_beats_unsharp(self):
        y, x = np.mgrid[0:64, 0:64]
        sharp = np.where(((x // 8) + (y // 8)) % 2 == 0, 200.0, 50.0)
        sharp[20:44, 30] = 240
        blurred = core.gaussian_blur(sharp.astype(np.float32) / 255, 1.5) * 255
        p = self.save("blur.png", np.repeat(np.round(blurred)[..., None], 3, 2))
        r = run("detail", p, "-o", self.out(), "--smart-sharpen", 1.5, "--noise", 0.001)
        u = run("sharpen", p, "-o", self.out(), "--amount", 1.0, "--radius", 1.5)
        rms = lambda a: np.sqrt(((a[4:-4, 4:-4, 0] - sharp[4:-4, 4:-4]) ** 2).mean())  # noqa: E731
        rb, rs, ru = rms(arr(p)), rms(arr(r["output"])), rms(arr(u["output"]))
        self.assertLess(rs, 0.7 * rb, (rs, rb))
        self.assertLess(rs, ru, (rs, ru))

    def test_freqsep_reconstructs(self):
        low = run("detail", self.d / "noise.png", "-o", self.out(), "--freq-sep", 3, "--part", "low")
        high = run("detail", self.d / "noise.png", "-o", self.out(), "--freq-sep", 3, "--part", "high")
        rec = arr(low["output"]) + arr(high["output"]) - 128
        ok = (arr(high["output"]) > 0) & (arr(high["output"]) < 255)   # unclipped high values
        self.assertLessEqual(np.abs(rec - self.noise)[ok].max(), 2)
        self.assertGreater(ok.mean(), 0.9)

    # ------------------------------------------------------------ distort
    def test_pinch_twirl(self):
        n = 65
        y, x = np.mgrid[0:n, 0:n] - 32
        r = np.hypot(x, y)
        disc = np.where(r < 12, 255, 0)
        p = self.save("disc.png", np.repeat(disc[..., None], 3, 2))
        outside = r > 33.5
        area = lambda q: (arr(q)[..., 0] > 127).sum()  # noqa: E731
        pin = run("distort", p, "-o", self.out(), "--pinch", 0.8)
        grow = run("distort", p, "-o", self.out(), "--pinch", -0.8)
        self.assertLess(area(pin["output"]), 0.8 * area(p))
        self.assertGreater(area(grow["output"]), 1.2 * area(p))
        self.assertLessEqual(np.abs(arr(pin["output"]) - arr(p))[outside].max(), 1)
        rings = 128 + 100 * np.cos(r / 3.0)
        q = self.save("rings.png", np.repeat(rings[..., None], 3, 2))
        tw = run("distort", q, "-o", self.out(), "--twirl", 90)
        d = np.abs(arr(tw["output"]) - arr(q))[r < 28]
        self.assertLessEqual(np.percentile(d, 99), 3)
        self.assertLessEqual(np.abs(arr(tw["output"]) - arr(q))[outside].max(), 1)

    def test_polar_rows_to_rings(self):
        rows = np.repeat(np.linspace(0, 255, 64)[:, None], 64, 1)
        p = self.save("rows.png", np.repeat(rows[..., None], 3, 2))
        r = run("distort", p, "-o", self.out(), "--polar", "to")
        a = arr(r["output"])[..., 0]
        y, x = np.mgrid[0:64, 0:64] - 31.5
        rad = np.hypot(x, y)
        inside = rad < 30
        want = np.clip(rad / 32.0 * 64 - 0.5, 0, 63) * 255 / 63      # row value at that radius
        self.assertLessEqual(np.abs(a - want)[inside & (rad > 1)].max(), 3)
        self.assertLess(a[31:33, 31:33].mean(), a[2, 31])     # centre is the top row (dark)

    def test_skew(self):
        im = np.zeros((41, 61, 3), np.uint8)
        im[:, 30] = 255
        p = self.save("line.png", im)
        r = run("distort", p, "-o", self.out(), "--skew", "20,0")
        a = arr(r["output"])[..., 0].astype(float)
        cx = lambda row: (a[row] * np.arange(61)).sum() / a[row].sum()  # noqa: E731
        shift = cx(40) - cx(0)
        self.assertLess(abs(shift - 40 * np.tan(np.radians(20))), 1.0, shift)

    def test_mosaic(self):
        r = run("pixelate", self.d / "noise.png", "-o", self.out(), "--cell", 8)
        a = arr(r["output"])
        for yy in (0, 8, 32):
            for xx in (0, 16, 48):
                cell = self.noise[yy:yy + 8, xx:xx + 8].reshape(-1, 3).mean(0)
                self.assertLessEqual(np.abs(a[yy, xx] - cell).max(), 1)
                self.assertTrue((a[yy:yy + 8, xx:xx + 8] == a[yy, xx]).all())
        r1 = run("pixelate", self.d / "noise.png", "-o", self.out(), "--cell", 1)
        self.assertTrue((arr(r1["output"]) == self.noise).all())

    # ------------------------------------------------------------ masks and replay
    def test_mask_and_replay(self):
        m = np.zeros((40, 56), np.uint8)
        m[10:30, 15:40] = 255
        Image.fromarray(m).save(self.d / "m.png")
        rec = self.d / "job" / "recipe.json"
        r1 = run("grade", self.d / "noise.png", "-o", self.out(), "--desaturate", "--contrast", 0.4,
                 "--mask", self.d / "m.png", "--recipe", rec)
        out = arr(r1["output"])
        self.assertTrue((out[m == 0] == self.noise[m == 0]).all())
        self.assertFalse((out[m == 255] == self.noise[m == 255]).all())
        p1 = run("run", rec)
        self.assertLessEqual(np.abs(arr(p1["output"]) - out).max(), 0)
        self.assertEqual(run("run", rec)["replay"], "same")
        self.assertEqual(json.loads(rec.read_text(encoding="utf-8"))["steps"][0]["op"], "grade.brightness_contrast")


if __name__ == "__main__":
    unittest.main()
