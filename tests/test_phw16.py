"""Proof bars for batch 16 (phw 0.17.0).

- Content-Aware Extend: the source rect and every pixel outside the destination rect bit-exact; on a
  flat background the destination interior == the patch within 1/255 (Poisson adds no offset);
  on a gradient background the destination's interior gradients == the patch's within 2/255 and
  the border ring keeps the image; --blend none pastes the patch bit-exact; replay bit-exact.
- Indexed colour: dither none == the brute-force nearest palette colour at every pixel; web
  palette is the 216 multiples of 51; flat grey 128 to black/white: Floyd-Steinberg white share
  128/255 within 1/100, ordered Bayer 8 within 1/64, noise within 3/100 and the same seed gives
  the same file; an ordered ramp has non-decreasing column means; transparent pixels map to the
  transparency index; auto keeps at most --colors colours; a .gpl file loads.
- Shake Reduction: a smooth random texture blurred by a known 9 px line at 30 degrees: mean error
  to the sharp original at least a third lower; the wrong angle (120) does worse than the right one.
- History snapshots (`run --upto N`): 0 == the source, 1 == the first edit alone bit-exact, N ==
  the full replay; out of range refuses.
- Satin: zero opacity identity; the interior farther than distance + 2 x size from every edge
  bit-exact; alpha unchanged; near the edge darker on the shape.
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


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch16(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw16-"))
        self.o = 0
        rng = np.random.default_rng(16)
        self.tex = rng.integers(0, 256, (12, 14, 3))

    def out(self, ext=".png"):
        self.o += 1
        return self.d / f"o{self.o}{ext}"

    def save(self, name, a, mode=None):
        Image.fromarray(np.asarray(np.clip(np.round(a), 0, 255), np.uint8), mode).save(self.d / name)
        return self.d / name

    # ------------------------------------------------------------ content-aware extend
    def test_extend_flat(self):
        a = np.full((48, 64, 3), 90.0)
        a[10:22, 8:22] = self.tex
        src = self.save("f.png", a)
        rec = self.d / "r.json"
        o = run("caextend", src, "-o", self.out(), "--rect", "6,8,18,16", "--to", "30,20", "--recipe", rec)["output"]
        b, a0 = arr(o), arr(src)
        dest = np.zeros((48, 64), bool)
        dest[28:44, 36:54] = True
        self.assertTrue((b[~dest] == a0[~dest]).all())
        # the patch has a flat margin, so the Poisson offset is 0: the texture lands as it was
        self.assertLessEqual(np.abs(b[30:42, 38:52] - a0[10:22, 8:22]).max(), 1)
        o2 = run("run", rec, "-o", self.out())["output"]
        self.assertTrue((arr(o2) == b).all())

    def test_extend_gradient(self):
        yy, xx = np.mgrid[0:48, 0:64]
        a = np.repeat((40 + 2 * xx + yy)[..., None], 3, axis=2).astype(float)
        a[6:16, 6:18] += np.clip(self.tex[:10, :12] - 128, -30, 30)
        src = self.save("g.png", a)
        b = arr(run("caextend", src, "-o", self.out(), "--rect", "4,4,16,16", "--to", "30,24")["output"])
        a0 = arr(src)
        self.assertTrue((b[4:20, 4:20] == a0[4:20, 4:20]).all())
        # border ring of the destination keeps the image
        ring = np.zeros((48, 64), bool)
        ring[28:44, 34:50] = True
        ring[29:43, 35:49] = False
        self.assertTrue((b[ring] == a0[ring]).all())
        # gradients inside the destination == the patch's
        gp = np.diff(a0[5:19, 5:19].astype(float), axis=1)
        gd = np.diff(b[29:43, 35:49].astype(float), axis=1)
        self.assertLessEqual(np.abs(gp - gd)[1:-1, 1:-1].max(), 2)
        n = arr(run("caextend", src, "-o", self.out(), "--rect", "4,4,16,16", "--to", "30,24", "--blend", "none")["output"])
        self.assertTrue((n[28:44, 34:50] == a0[4:20, 4:20]).all())

    # ------------------------------------------------------------ indexed colour
    def test_indexed_none_is_nearest(self):
        rng = np.random.default_rng(3)
        a = rng.integers(0, 256, (20, 24, 3))
        src = self.save("n.png", a)
        pal = "#000000 #ffffff #ff0000 #00ff00 #0000ff #808080"
        r = run("indexed", src, "-o", self.out(), "--palette", pal)
        im = Image.open(r["output"])
        self.assertEqual(im.mode, "P")
        P = np.array([[0, 0, 0], [255, 255, 255], [255, 0, 0], [0, 255, 0], [0, 0, 255], [128, 128, 128]])
        got = np.asarray(im.convert("RGB")).astype(int)
        want = P[((a[..., None, :] - P[None, None]) ** 2).sum(-1).argmin(-1)]
        self.assertTrue((got == want).all())

    def test_web_palette(self):
        from phw import extend
        w = extend.web_palette()
        self.assertEqual(len(w), 216)
        self.assertEqual(len({tuple(r) for r in w}), 216)
        self.assertTrue((w % 51 == 0).all())

    def white_share(self, dither, *extra):
        src = self.save("grey.png", np.full((64, 64, 3), 128.0))
        r = run("indexed", src, "-o", self.out(), "--palette", "#000000 #ffffff", "--dither", dither, *extra)
        g = np.asarray(Image.open(r["output"]).convert("L")).astype(float)
        return (g > 127).mean(), r

    def test_dither_means(self):
        self.assertLessEqual(abs(self.white_share("floyd")[0] - 128 / 255), 0.01)
        self.assertLessEqual(abs(self.white_share("ordered")[0] - 128 / 255), 1 / 64)
        s1, r1 = self.white_share("noise", "--seed", "4")
        self.assertLessEqual(abs(s1 - 128 / 255), 0.03)
        s2, r2 = self.white_share("noise", "--seed", "4")
        self.assertEqual(Path(r1["output"]).read_bytes(), Path(r2["output"]).read_bytes())
        self.assertEqual(self.white_share("none")[0], 1.0)

    def test_ordered_ramp_monotone(self):
        ramp = np.repeat(np.repeat(np.linspace(0, 255, 64)[None, :, None], 32, 0), 3, 2)
        src = self.save("ramp.png", ramp)
        r = run("indexed", src, "-o", self.out(), "--palette", "gray", "--colors", "4", "--dither", "ordered")
        g = np.asarray(Image.open(r["output"]).convert("L")).astype(float).mean(0)
        sm = np.convolve(g, np.ones(8) / 8, "valid")
        self.assertTrue((np.diff(sm) >= -1e-9).all())
        self.assertLessEqual(np.abs(g.reshape(8, 8).mean(1) - np.linspace(0, 255, 64).reshape(8, 8).mean(1)).max(), 12)

    def test_alpha_and_auto_and_gpl(self):
        a = np.zeros((16, 16, 4))
        a[..., :3] = np.random.default_rng(5).integers(0, 256, (16, 16, 3))
        a[..., 3] = 255
        a[:4] = 0
        src = self.save("t.png", a, "RGBA")
        r = run("indexed", src, "-o", self.out(), "--colors", "8")
        im = Image.open(r["output"])
        self.assertEqual(im.info.get("transparency"), 0)
        idx = np.asarray(im)
        self.assertTrue((idx[:4] == 0).all() and (idx[4:] != 0).all())
        self.assertLessEqual(r["colors"], 8)
        gpl = self.d / "p.gpl"
        gpl.write_text("GIMP Palette\nName: t\n#\n  0   0   0 black\n255 255 255 white\n", encoding="utf-8")
        r = run("indexed", self.save("g2.png", np.full((8, 8, 3), 200.0)), "-o", self.out(), "--palette", gpl)
        self.assertEqual(r["colors"], 2)
        self.assertTrue((np.asarray(Image.open(r["output"]).convert("L")) == 255).all())

    # ------------------------------------------------------------ shake reduction
    def blur_line(self, sharp, length, angle):
        from phw import extend
        k = extend.motion_psf(length, angle)
        pad = k.shape[0]
        f = np.pad(sharp, pad, mode="reflect")
        kp = np.zeros_like(f)
        kp[:k.shape[0], :k.shape[1]] = k
        kp = np.roll(kp, (-(k.shape[0] // 2), -(k.shape[1] // 2)), axis=(0, 1))
        return extend.fft_conv(f, np.fft.fft2(kp))[pad:-pad, pad:-pad]

    def test_shake(self):
        small = np.random.default_rng(1).integers(40, 216, (16, 16)).astype(np.uint8)
        sharp = np.asarray(Image.fromarray(small).resize((64, 64), Image.BICUBIC)).astype(float)
        src = self.save("b.png", np.repeat(self.blur_line(sharp, 9, 30)[..., None], 3, 2))
        inner = (slice(10, 54), slice(10, 54))
        e0 = np.abs(arr(src)[..., 0][inner] - sharp[inner]).mean()
        errs = {}
        for ang in (30, 120):
            out = arr(run("shake", src, "-o", self.out(), "--length", 9, "--angle", ang)["output"])[..., 0]
            errs[ang] = np.abs(out[inner] - sharp[inner]).mean()
        self.assertLess(errs[30], e0 * 2 / 3, (e0, errs))
        self.assertLess(errs[30], errs[120], errs)

    # ------------------------------------------------------------ history snapshots
    def test_run_upto(self):
        rng = np.random.default_rng(9)
        src = self.save("h.png", rng.integers(0, 256, (24, 24, 3)))
        rec = self.d / "h.json"
        o1 = run("color", src, "-o", self.out(), "--invert", "--recipe", rec)["output"]
        run("filter", src, "-o", self.out(), "--offset", "3,2", "--recipe", rec)
        r = json.loads(rec.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(r["steps"]), 2)
        s0 = arr(run("run", rec, "-o", self.out(), "--upto", 0)["output"])
        self.assertTrue((s0 == arr(src)).all())
        s1 = arr(run("run", rec, "-o", self.out(), "--upto", 1)["output"])
        self.assertTrue((s1 == arr(o1)).all())
        full = arr(run("run", rec, "-o", self.out())["output"])
        upto_all = arr(run("run", rec, "-o", self.out(), "--upto", len(r["steps"]))["output"])
        self.assertTrue((full == upto_all).all())
        with self.assertRaises(SystemExit):
            run("run", rec, "-o", self.out(), "--upto", len(r["steps"]) + 1)

    # ------------------------------------------------------------ satin
    def test_satin(self):
        sq = np.zeros((96, 96, 4))
        sq[8:88, 8:88] = [200, 180, 160, 255]
        src = self.save("sq.png", sq, "RGBA")
        a0 = arr(src)
        z = arr(run("layerstyle", src, "-o", self.out(), "--satin", "opacity=0")["output"])
        self.assertTrue((z == a0).all())
        b = arr(run("layerstyle", src, "-o", self.out(), "--satin", "distance=6,size=8,opacity=1")["output"])
        self.assertTrue((b[..., 3] == a0[..., 3]).all())
        m = 8 + 6 + 2 * 8 + 4
        self.assertTrue((b[m:96 - m, m:96 - m] == a0[m:96 - m, m:96 - m]).all())
        self.assertLess(b[8:20, 8:88, :3].mean(), a0[8:20, 8:88, :3].mean() - 5)
        self.assertTrue((b[:8] == a0[:8]).all())


if __name__ == "__main__":
    unittest.main()
