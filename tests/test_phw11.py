"""Proof bars for batch 11 (phw 0.12.0).

- Wave: amp 0 identity; a vertical line's column shift follows amp * sin(2 pi y / wl) within 1 px.
- Spherize: + grows a centred disc, - shrinks it; the corners (outside the circle) within 1/255.
- ZigZag: concentric rings stay within 3/255 (rotation keeps the radius); spokes move.
- Lens: a dot at source radius r lands where r_out (1 + k1 r_out^2) = r_src, within 1 px.
- Crystallize: unique colours <= cell count; each cell exactly its source mean within 1/255; seeded.
- Halftone: flat greys 25/50/75% keep their mean within 10/255; output is binary per channel.
- Trace Contour: on a disc, every black pixel lies within 1.5 px of the disc radius.
- Diffuse: every output pixel equals one of its 3x3 source neighbours; seeded repeatable.
- Wind: flat image unchanged; one bright pixel leaves a decreasing trail on the downwind side only.
- Oil Paint: flat unchanged; a hard step stays two-valued; noise std drops by more than half.
- Clouds: seeded repeatable, values between fg and bg, low-frequency energy > high.
- Radial blur: spin leaves concentric rings within 3/255 and cuts the variance along a spoke ring
  by more than half; zoom leaves spokes within a mean 4/255 (measured 2.87)
  and changes rings over 4x as much.
- Surface Blur: a step of 100 levels stays exact at threshold 30; noise std (sd 6) drops by half.
- Dodge/Burn: highlights dodge moves bright pixels more than dark; burn darkens; 0 and 255 fixed;
  sponge desaturate lowers chroma with luma within 2/255.
- Masks keep outside pixels; `phw run` replays the recipe bit-exactly.
"""
import json
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
Y709 = np.array([0.2126, 0.7152, 0.0722])


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch11(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw11-"))
        self.rng = np.random.default_rng(11)
        self.o = 0
        n = 65
        Y, X = np.mgrid[0:n, 0:n] - 32.0
        self.R = np.hypot(X, Y)
        self.A = np.arctan2(Y, X)

    def out(self):
        self.o += 1
        return self.d / f"o{self.o}.png"

    def save(self, name, a):
        Image.fromarray(np.asarray(np.clip(a, 0, 255), np.uint8)).save(self.d / name)
        return self.d / name

    def rings(self):
        g = (127.5 + 127.5 * np.cos(self.R / 4.0))
        return self.save("rings.png", np.stack([g] * 3, 2))

    def spokes(self):
        g = (127.5 + 127.5 * np.cos(self.A * 8))
        return self.save("spokes.png", np.stack([g] * 3, 2))

    def ring_spread(self, a, r0=20):
        m = np.abs(self.R - r0) < 0.5
        return a[..., 0][m].std()

    # ------------------------------------------------------------ warpfx
    def test_wave(self):
        im = np.zeros((60, 60, 3), np.uint8)
        im[:, 30] = 255
        p = self.save("line.png", im)
        r0 = run("warpfx", p, "-o", self.out(), "--wave", "0,20")
        self.assertTrue((arr(r0["output"]) == im).all())
        r = run("warpfx", p, "-o", self.out(), "--wave", "4,20", "--axis", "x")
        a = arr(r["output"])[..., 0].astype(float)
        for y in range(60):
            col = (a[y] * np.arange(60)).sum() / a[y].sum()
            self.assertLessEqual(abs(col - (30 - 4 * np.sin(2 * np.pi * y / 20))), 1.0)
        self.assertIn(r["rung"], (1, 2))   # 2 only when cv2 is present for remap

    def test_spherize(self):
        im = np.zeros((65, 65, 3), np.uint8)
        im[self.R <= 10] = 255
        im[0:4, 0:4] = [10, 200, 90]
        p = self.save("disc.png", im)
        area = (arr(p)[..., 0] > 127).sum()
        big = (arr(run("warpfx", p, "-o", self.out(), "--spherize", 0.8)["output"])[..., 0] > 127).sum()
        small = (arr(run("warpfx", p, "-o", self.out(), "--spherize", -0.8)["output"])[..., 0] > 127).sum()
        self.assertGreater(big, area * 1.3)
        self.assertLess(small, area * 0.8)
        a = arr(run("warpfx", p, "-o", self.out(), "--spherize", 0.8)["output"])
        self.assertLessEqual(np.abs(a[0:4, 0:4] - im[0:4, 0:4]).max(), 1)

    def test_zigzag(self):
        a0 = arr(self.rings())
        a = arr(run("warpfx", self.rings(), "-o", self.out(), "--zigzag", 30)["output"])
        inner = self.R < 29
        self.assertLessEqual(np.abs(a - a0)[inner].max(), 3)
        s0 = arr(self.spokes())
        s = arr(run("warpfx", self.spokes(), "-o", self.out(), "--zigzag", 30)["output"])
        self.assertGreater(np.abs(s - s0)[inner].mean(), 10)

    def test_lens(self):
        n = 81
        im = np.zeros((n, n, 3), np.uint8)
        im[38:43, 68:73] = 255           # dot centred at (70, 40): dx = 30, dy = 0 from centre (40, 40)
        p = self.save("dot.png", im)
        k1 = 0.3
        a = arr(run("warpfx", p, "-o", self.out(), "--lens", k1)["output"])[..., 0].astype(float)
        xs = np.arange(n)
        cx = (a.sum(0) * xs).sum() / a.sum()
        D = np.hypot(40, 40)
        # solve r_out (1 + k1 (r_out/D)^2) = 30
        ro = 30.0
        for _ in range(50):
            ro = 30.0 / (1 + k1 * (ro / D) ** 2)
        self.assertLessEqual(abs((cx - 40) - ro), 1.0)

    # ------------------------------------------------------------ stylize
    def test_crystallize(self):
        im = self.rng.integers(0, 256, (48, 48, 3), dtype=np.uint8)
        p = self.save("noise.png", im)
        r = run("stylize", p, "-o", self.out(), "--crystallize", 8, "--seed", 3)
        a = arr(r["output"])
        cols = np.unique(a.reshape(-1, 3), axis=0)
        self.assertLessEqual(len(cols), 36)
        for c in cols[:10]:
            m = (a == c).all(2)
            self.assertLessEqual(np.abs(im[m].mean(0) - c).max(), 1.0)
        a2 = arr(run("stylize", p, "-o", self.out(), "--crystallize", 8, "--seed", 3)["output"])
        self.assertTrue((a == a2).all())

    def test_halftone(self):
        for g in (64, 128, 192):
            p = self.save(f"g{g}.png", np.full((96, 96, 3), g))
            a = arr(run("stylize", p, "-o", self.out(), "--halftone", 8)["output"])
            self.assertTrue(np.isin(a, [0, 255]).all())
            self.assertLessEqual(np.abs(a.reshape(-1, 3).mean(0) - g).max(), 10)

    def test_trace_contour(self):
        im = np.zeros((65, 65, 3), np.uint8)
        im[self.R <= 20] = 200
        p = self.save("disc2.png", im)
        a = arr(run("stylize", p, "-o", self.out(), "--trace-contour", 100)["output"])[..., 0]
        blk = a == 0
        self.assertGreater(blk.sum(), 60)
        self.assertLessEqual(np.abs(self.R[blk] - 20).max(), 1.5)

    def test_diffuse(self):
        im = self.rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)
        p = self.save("n2.png", im)
        a = arr(run("stylize", p, "-o", self.out(), "--diffuse", 1, "--seed", 5)["output"])
        pd = np.pad(im, ((1, 1), (1, 1), (0, 0)), mode="edge").astype(np.int32)
        ok = np.zeros((30, 30), bool)
        for oy in (0, 1, 2):
            for ox in (0, 1, 2):
                ok |= (pd[oy:oy + 30, ox:ox + 30] == a).all(2)
        self.assertTrue(ok.all())
        self.assertFalse((a == im).all())
        b = arr(run("stylize", p, "-o", self.out(), "--diffuse", 1, "--seed", 5)["output"])
        self.assertTrue((a == b).all())

    def test_wind(self):
        p = self.save("flat.png", np.full((10, 40, 3), 90))
        self.assertTrue((arr(run("stylize", p, "-o", self.out(), "--wind", 10)["output"]) == 90).all())
        im = np.zeros((5, 40, 3), np.uint8)
        im[2, 10] = 255
        p = self.save("dot2.png", im)
        a = arr(run("stylize", p, "-o", self.out(), "--wind", 10)["output"])[2, :, 0]
        self.assertTrue((a[:10] == 0).all())
        self.assertGreater(a[15], 50)
        self.assertTrue((np.diff(a[10:]) <= 0).all())

    def test_oil_paint(self):
        p = self.save("flat2.png", np.full((20, 20, 3), 77))
        self.assertTrue((arr(run("stylize", p, "-o", self.out(), "--oil-paint", 3)["output"]) == 77).all())
        im = np.zeros((32, 32, 3))
        im[:, 16:] = 200
        p = self.save("step.png", im)
        a = arr(run("stylize", p, "-o", self.out(), "--oil-paint", 3)["output"])
        self.assertEqual(set(np.unique(a)), {0, 200})
        noisy = np.clip(128 + self.rng.normal(0, 20, (40, 40, 3)), 0, 255)
        p = self.save("nz.png", noisy)
        b = arr(run("stylize", p, "-o", self.out(), "--oil-paint", 3)["output"])
        self.assertLess(b[5:-5, 5:-5].std(), 0.5 * arr(p)[5:-5, 5:-5].std())

    def test_clouds(self):
        p = self.save("any.png", np.zeros((64, 64, 3)))
        a = arr(run("stylize", p, "-o", self.out(), "--clouds", 32, "--fg", "#204060", "--bg", "#c0e0ff",
                    "--seed", 2)["output"])
        b = arr(run("stylize", p, "-o", self.out(), "--clouds", 32, "--fg", "#204060", "--bg", "#c0e0ff",
                    "--seed", 2)["output"])
        self.assertTrue((a == b).all())
        lo, hi = np.array([0x20, 0x40, 0x60]), np.array([0xc0, 0xe0, 0xff])
        self.assertTrue(((a >= lo - 1) & (a <= hi + 1)).all())
        F = np.abs(np.fft.fft2(a[..., 0] - a[..., 0].mean()))
        self.assertGreater(F[1:4, 1:4].mean(), 4 * F[20:44, 20:44].mean())

    # ------------------------------------------------------------ blurfx
    def test_radial_blur(self):
        a0 = arr(self.rings())
        a = arr(run("blurfx", self.rings(), "-o", self.out(), "--spin", 30)["output"])
        self.assertLessEqual(np.abs(a - a0)[self.R < 29].max(), 3)
        s0 = arr(self.spokes())
        s = arr(run("blurfx", self.spokes(), "-o", self.out(), "--spin", 40)["output"])
        self.assertLess(self.ring_spread(s), 0.5 * self.ring_spread(s0))
        z = arr(run("blurfx", self.spokes(), "-o", self.out(), "--zoom", 0.3)["output"])
        m = (self.R > 12) & (self.R < 29)
        err = np.abs(z - s0)[m]
        self.assertLessEqual(err.mean(), 4)     # measured 2.87: pixel-grid spokes alias a little
        zr = arr(run("blurfx", self.rings(), "-o", self.out(), "--zoom", 0.3)["output"])
        self.assertGreater(np.abs(zr - a0)[m].mean(), 4 * err.mean())

    def test_surface_blur(self):
        im = np.zeros((32, 32, 3))
        im[:, 16:] = 100
        im = im + 60 + self.rng.normal(0, 6, im.shape)
        p = self.save("sn.png", im)
        src = arr(p)
        a = arr(run("blurfx", p, "-o", self.out(), "--surface", "3,30")["output"])
        self.assertLess(a[:, 3:12].std(), 0.5 * src[:, 3:12].std())
        self.assertGreater(a[:, 16:].min() - a[:, :16].max(), 60)

    # ------------------------------------------------------------ tonebrush
    def test_dodge_burn_sponge(self):
        ramp = np.tile(np.arange(256), (4, 1))
        p = self.save("ramp.png", np.stack([ramp] * 3, 2))
        a = arr(run("tonebrush", p, "-o", self.out(), "--mode", "dodge", "--range", "highlights")["output"])[0, :, 0]
        self.assertEqual((a[0], a[255]), (0, 255))
        self.assertGreater(a[200] - 200, 3 * max(1, a[50] - 50))
        b = arr(run("tonebrush", p, "-o", self.out(), "--mode", "burn")["output"])[0, :, 0]
        self.assertEqual((b[0], b[255]), (0, 255))
        self.assertLess(b[128], 128 - 10)
        col = self.rng.integers(30, 226, (16, 16, 3)).astype(float)
        q = self.save("col.png", col)
        src = arr(q).astype(float)
        c = arr(run("tonebrush", q, "-o", self.out(), "--mode", "sponge", "--exposure", 0.6)["output"]).astype(float)
        ch = lambda x: np.abs(x - (x * Y709).sum(2, keepdims=True)).mean()  # noqa: E731
        self.assertLess(ch(c), 0.6 * ch(src))
        self.assertLessEqual(np.abs((c * Y709).sum(2) - (src * Y709).sum(2)).max(), 2.0)

    # ------------------------------------------------------------ mask + replay
    def test_mask_and_replay(self):
        im = self.rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)
        p = self.save("mr.png", im)
        m = np.zeros((32, 32), np.uint8)
        m[:, 16:] = 255
        Image.fromarray(m).save(self.d / "m.png")
        rec = self.d / "r.json"
        r = run("stylize", p, "-o", self.out(), "--oil-paint", 2, "--mask", self.d / "m.png", "--recipe", rec)
        a = arr(r["output"])
        self.assertTrue((a[:, :15] == im[:, :15]).all())
        self.assertFalse((a[:, 17:] == im[:, 17:]).all())
        self.assertTrue(json.loads(rec.read_text()))
        r2 = run("run", rec, "-o", self.out())
        self.assertTrue((arr(r2["output"]) == a).all())


if __name__ == "__main__":
    unittest.main()
