"""Proof bars for batch 15 (phw 0.16.0).

- Gradient: linear black->white == the projection t x 255 within 1/255 and the ends exact; radial ==
  distance / length; reflected symmetric; opacity 0 identity; a gradient fill layer in a `layers`
  recipe == the `gradient` command on the same base within 1/255. Pattern: output == the tile
  repeated at the offset, bit-exact.
- Layer styles (on an opaque square on transparency): colour overlay == the colour inside, alpha and
  outside unchanged; outer glow leaves the square bit-exact, adds alpha only outside, falling with
  distance; inner glow and inner shadow leave alpha and the centre unchanged, inner shadow darkens
  the edge on the light side; bevel: centre unchanged, light-side edge brighter than the far side.
- Blend If: default sliders == plain normal over, bit-exact; Underlying 128,128,255,255 keeps the
  base exactly where its grey < 128 and shows the top elsewhere; split 100,156 gives half at 128
  within 1/255.
- Replace Color: pixels beyond the fuzziness bit-exact; the target colour turns by the hue shift
  within 1 degree; fuzziness 0 changes only the exact colour.
- Focus Area: sharp noise left, blurred noise right: > 95% white on the sharp side and > 95% black
  on the blurred side (4 px from the seam); a sharp disc on blur: IoU > 0.75.
- Eraser: beyond the radius bit-exact and opaque; on the stroke alpha 0. Magic Eraser: the
  contiguous region alone goes transparent; --all takes the disconnected one too. Paint Bucket:
  the region becomes the colour exactly, a same-coloured disconnected region stays.
"""
import json
import math
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


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch15(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw15-"))
        self.rng = np.random.default_rng(15)
        self.o = 0
        self.noise = self.rng.integers(0, 256, (32, 40, 3), dtype=np.uint8)
        self.np_ = self.save("noise.png", self.noise)
        sq = np.zeros((40, 40, 4))
        sq[10:30, 10:30] = [120, 140, 160, 255]
        self.sq = sq
        self.sqp = self.save("sq.png", sq, "RGBA")

    def out(self):
        self.o += 1
        return self.d / f"o{self.o}.png"

    def save(self, name, a, mode=None):
        Image.fromarray(np.asarray(np.clip(np.round(a), 0, 255), np.uint8), mode).save(self.d / name)
        return self.d / name

    # ------------------------------------------------------------ gradient, pattern, fill layers
    def test_gradient(self):
        a = arr(run("gradient", self.np_, "-o", self.out(), "--start", "5,0", "--end", "35,0")["output"])
        xx = np.arange(40)
        t = np.clip((xx - 5) / 30, 0, 1) * 255
        self.assertLessEqual(np.abs(a[..., 0] - t[None, :]).max(), 1)
        self.assertTrue((a[:, :6] == 0).all() and (a[:, 35:] == 255).all())
        r = arr(run("gradient", self.np_, "-o", self.out(), "--kind", "radial", "--start", "20,16", "--end", "30,16")["output"])
        yy, xx2 = np.mgrid[0:32, 0:40]
        rt = np.clip(np.hypot(xx2 - 20, yy - 16) / 10, 0, 1) * 255
        self.assertLessEqual(np.abs(r[..., 1] - rt).max(), 1)
        f = arr(run("gradient", self.np_, "-o", self.out(), "--kind", "reflected", "--start", "20,0", "--end", "30,0")["output"])
        self.assertTrue((f[:, 20 - 8] == f[:, 20 + 8]).all())
        z = arr(run("gradient", self.np_, "-o", self.out(), "--start", "0,0", "--end", "9,9", "--opacity", 0)["output"])
        self.assertTrue((z == self.noise).all())
        # fill layers
        self.save("tile.png", self.rng.integers(0, 256, (5, 7, 3)))
        rec = {"version": 1, "kind": "layers", "canvas": {"width": 40, "height": 32},
               "layers": [{"type": "image", "file": "noise.png"},
                          {"type": "gradient", "kind": "linear", "start": [0, 4], "end": [0, 28],
                           "colors": ["#ff0000", "#0000ff80"], "opacity": 1}]}
        rp = self.d / "fl.json"
        rp.write_text(json.dumps(rec), encoding="utf-8")
        lay = arr(run("layers", rp, "-o", self.out())["output"])[..., :3]
        g = arr(run("gradient", self.np_, "-o", self.out(), "--start", "0,4", "--end", "0,28",
                    "--colors", "#ff0000 #0000ff80")["output"])
        self.assertLessEqual(np.abs(lay - g).max(), 1)
        rec["layers"][1] = {"type": "pattern", "file": "tile.png", "offset": [2, 3]}
        rp.write_text(json.dumps(rec), encoding="utf-8")
        lp = arr(run("layers", rp, "-o", self.out())["output"])[..., :3]
        tile = arr(self.d / "tile.png")
        Y, X = np.mgrid[0:32, 0:40]
        exp = tile[(Y - 3) % 5, (X - 2) % 7]
        self.assertTrue((lp == exp).all())
        pp = arr(run("pattern", self.np_, "-o", self.out(), "--tile", self.d / "tile.png", "--offset", "2,3")["output"])
        self.assertTrue((pp == exp).all())

    # ------------------------------------------------------------ layer styles
    def test_layerstyle(self):
        sq = self.sq.astype(np.int32)
        inside = sq[..., 3] == 255
        co = arr(run("layerstyle", self.sqp, "-o", self.out(), "--color-overlay", "color=#ff8000")["output"])
        self.assertTrue((co[inside][:, :3] == [255, 128, 0]).all())
        self.assertTrue((co[..., 3] == sq[..., 3]).all())
        og = arr(run("layerstyle", self.sqp, "-o", self.out(), "--outer-glow", "size=8,opacity=1")["output"])
        self.assertTrue((og[inside] == sq[inside]).all())
        self.assertGreater(og[20, 8, 3], og[20, 4, 3])
        self.assertGreater(og[20, 4, 3], og[20, 1, 3])
        self.assertGreater(og[20, 8, 3], 50)
        ig = arr(run("layerstyle", self.sqp, "-o", self.out(), "--inner-glow", "size=4")["output"])
        self.assertTrue((ig[..., 3] == sq[..., 3]).all())
        self.assertTrue((np.abs(ig[20, 20] - sq[20, 20]) <= 1).all())
        self.assertGreater(ig[20, 10, :3].mean(), sq[20, 10, :3].mean() + 20)
        ish = arr(run("layerstyle", self.sqp, "-o", self.out(), "--inner-shadow", "size=2,distance=4,opacity=1")["output"])
        self.assertTrue((ish[..., 3] == sq[..., 3]).all())
        self.assertTrue((np.abs(ish[20, 20] - sq[20, 20]) <= 1).all())
        # light from upper left (120 deg): the shadow sits on the inner top-left edge
        self.assertLess(ish[11, 20, :3].mean(), ish[28, 20, :3].mean() - 20)
        bv = arr(run("layerstyle", self.sqp, "-o", self.out(), "--bevel", "size=4")["output"])
        self.assertTrue((np.abs(bv[20, 20] - sq[20, 20]) <= 1).all())
        top, bottom = bv[10:13, 14:26, :3].mean(), bv[27:30, 14:26, :3].mean()
        self.assertGreater(top, sq[20, 20, :3].mean() + 10)
        self.assertLess(bottom, sq[20, 20, :3].mean() - 10)
        self.assertTrue((bv[..., 3] == sq[..., 3]).all())

    # ------------------------------------------------------------ blend if
    def test_blendif(self):
        base = np.tile(np.arange(0, 256, 256 / 40)[None, :, None], (32, 1, 3)).round()
        bp = self.save("base.png", base)
        top = self.rng.integers(0, 256, (32, 40, 3))
        tp = self.save("top.png", top)
        a = arr(run("blendif", bp, "-o", self.out(), "--layer", tp)["output"])
        self.assertTrue((a == top).all())
        b = arr(run("blendif", bp, "-o", self.out(), "--layer", tp, "--under", "128,128,255,255")["output"])
        lo = base[..., 0] < 128
        self.assertTrue((b[lo] == base[lo]).all())
        self.assertTrue((b[~lo] == top[~lo]).all())
        grey = self.save("g128.png", np.full((8, 8, 3), 128))
        white = self.save("w.png", np.full((8, 8, 3), 255))
        c = arr(run("blendif", grey, "-o", self.out(), "--layer", white, "--this", "0,0,100,156")["output"])
        # top is 255 > 156: hidden; use the underlying ramp instead
        self.assertTrue((c == 128).all())
        h = arr(run("blendif", grey, "-o", self.out(), "--layer", white, "--under", "100,156,255,255")["output"])
        self.assertLessEqual(np.abs(h - (128 + 0.5 * 127)).max(), 1)

    # ------------------------------------------------------------ replace color
    def test_replacecolor(self):
        img = self.noise.copy()
        img[4:12, 4:12] = [200, 40, 40]
        p = self.save("rc.png", img)
        r = arr(run("replacecolor", p, "-o", self.out(), "--pick", "6,6", "--fuzziness", 30, "--hue", 120)["output"])
        h0, _, _ = core.rgb_to_hsv(np.array([[[200, 40, 40]]], np.float32) / 255)
        h1, _, _ = core.rgb_to_hsv(r[6:7, 6:7, :3].astype(np.float32) / 255)
        dh = ((float(h1[0, 0]) - float(h0[0, 0])) * 360) % 360
        self.assertLess(abs(dh - 120), 1.0)
        from phw import masks
        lab = masks.rgb_to_lab(img.astype(np.float32) / 255)
        tl = masks.rgb_to_lab(np.array([[[200, 40, 40]]], np.float32) / 255)[0, 0]
        far = np.sqrt(((lab - tl) ** 2).sum(2)) > 30
        self.assertTrue((r[far] == img[far]).all())
        self.assertGreater(far.mean(), 0.5)
        z = arr(run("replacecolor", p, "-o", self.out(), "--color", "#c82828", "--fuzziness", 0, "--hue", 120)["output"])
        same = (img == [200, 40, 40]).all(2)
        self.assertTrue((z[~same] == img[~same]).all())
        self.assertFalse((z[same] == img[same]).all())

    # ------------------------------------------------------------ focus area
    def test_focusarea(self):
        n = self.rng.integers(0, 256, (48, 64)).astype(float)
        blurred = core.gaussian_blur((n / 255).astype(np.float32), 3.0) * 255
        img = n.copy()
        img[:, 32:] = blurred[:, 32:]
        p = self.save("focus.png", np.repeat(img[..., None], 3, 2))
        r = run("focusarea", p, "-o", self.d / "fmask.png", "--radius", 3)
        m = arr(r["output"])
        self.assertGreater((m[:, :28] == 255).mean(), 0.95)
        self.assertGreater((m[:, 36:] == 0).mean(), 0.95)
        yy, xx = np.mgrid[0:64, 0:64]
        disc = (xx - 32) ** 2 + (yy - 32) ** 2 <= 15 ** 2
        n2 = self.rng.integers(0, 256, (64, 64)).astype(float)
        b2 = core.gaussian_blur((n2 / 255).astype(np.float32), 3.0) * 255
        dp = self.save("disc.png", np.repeat(np.where(disc, n2, b2)[..., None], 3, 2))
        md = arr(run("focusarea", dp, "-o", self.d / "dmask.png", "--radius", 3)["output"]) > 127
        self.assertGreater((md & disc).sum() / (md | disc).sum(), 0.75)

    # ------------------------------------------------------------ eraser, magic eraser, bucket
    def test_erase_bucket(self):
        r = arr(run("erase", self.np_, "-o", self.out(), "--stroke", "5,16 35,16", "--radius", 4, "--hardness", 1)["output"])
        self.assertEqual(r.shape[2], 4)
        yy, xx = np.mgrid[0:32, 0:40]
        far = np.abs(yy - 16) > 5
        self.assertTrue((r[far][:, :3] == self.noise[far]).all() and (r[far][:, 3] == 255).all())
        self.assertTrue((r[14:19, 8:33, 3] == 0).all())
        two = np.full((20, 30, 3), 255)
        two[:, 14:16] = 0
        two[2:8, 2:8] = [250, 250, 250]  # inside tolerance
        tp = self.save("two.png", two)
        m = arr(run("erase", tp, "-o", self.out(), "--magic", "1,1", "--tolerance", 10)["output"])
        self.assertTrue((m[:, :14, 3] == 0).all())
        self.assertTrue((m[:, 14:, 3] == 255).all())
        g = arr(run("erase", tp, "-o", self.out(), "--magic", "1,1", "--tolerance", 10, "--all")["output"])
        self.assertTrue((g[:, 16:, 3] == 0).all() and (g[:, 14:16, 3] == 255).all())
        b = arr(run("bucket", tp, "-o", self.out(), "--at", "20,5", "--color", "#3366cc", "--tolerance", 0)["output"])
        self.assertTrue((b[:, 16:] == [0x33, 0x66, 0xcc]).all())
        self.assertTrue((b[:, :16] == two[:, :16]).all())
        rec = self.d / "bk.json"
        b2 = arr(run("bucket", tp, "-o", self.out(), "--at", "20,5", "--color", "#3366cc", "--all", "--tolerance", 0,
                     "--recipe", rec)["output"])
        self.assertTrue((b2[:, :14][(two[:, :14] == 255).all(2)] == [0x33, 0x66, 0xcc]).all())
        self.assertTrue((arr(run("run", rec, "-o", self.out())["output"]) == b2).all())


if __name__ == "__main__":
    unittest.main()
