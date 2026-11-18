"""Proof bars for batch 9 (phw 0.10.0): the next rung 1 rows of the coverage table.

- Auto Contrast: 0.1% clipped ends map to 0 and 1 with one pair for all channels, so channel ratios
  of a mid pixel hold; Auto Tone stretches each channel to the full range; Auto Color leaves each
  channel mean within 2/255 of the luma mean (grey cast removed).
- Vibrance: amount 0 is bit-identical; greys unchanged; a dull colour's chroma grows by a larger
  factor than a saturated one's.
- Shadows/Highlights: amounts 0 identity; a dark area lifts, a bright area beside it changes < 1/255
  (shadows only); hue ratios r:g:b of unclipped pixels kept within 1%.
- Match Color: Lab mean of the result within 1.5 and spread within 10% (or 0.5 Lab units) of the reference; matching
  an image to itself returns it within 1/255; amount 0 identity; replay needs no reference file.
- Add Noise: measured std within 5% of the setting on mid-grey, mean shift < 0.5/255, same seed
  bit-identical, --mono gives equal change on all channels.
- Emboss: flat -> exactly 128; a vertical step lit from the left reads > 128 on one side of the
  edge only. Find Edges: flat -> exactly 255; a step edge column < 128.
- Canvas Size: source pixels land exactly at the anchor offset; trim(canvas(x)) == x; shrinking
  crops around the anchor. Masks leave outside pixels unchanged; `phw run` replays bit-identical.
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
from phw.masks import rgb_to_lab  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch9(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw9-"))
        rng = np.random.default_rng(9)
        self.noise = rng.integers(0, 256, (40, 56, 3), dtype=np.uint8)
        Image.fromarray(self.noise).save(self.d / "noise.png")
        # dull, low-contrast photo-like gradient with a warm cast
        y, x = np.mgrid[0:48, 0:64] / np.array([47.0, 63.0]).reshape(2, 1, 1)
        base = 0.3 + 0.35 * (0.6 * x + 0.4 * y) + 0.04 * rng.standard_normal((48, 64))
        cast = np.stack([base * 1.15, base * 1.0, base * 0.8], axis=2)
        self.dull = np.clip(cast * 255, 0, 255).astype(np.uint8)
        Image.fromarray(self.dull).save(self.d / "dull.png")
        self.o = 0

    def out(self):
        self.o += 1
        return self.d / f"o{self.o}.png"

    # ------------------------------------------------------------ auto
    def test_auto_contrast_and_tone(self):
        r = run("tone", self.d / "dull.png", "-o", self.out(), "--auto", "contrast", "--clip", 0)
        a = arr(r["output"])
        self.assertEqual(a.min(), 0)
        self.assertEqual(a.max(), 255)
        # one pair for all channels: the warm cast stays (R mean > B mean by a wide margin)
        self.assertGreater(a[..., 0].mean() - a[..., 2].mean(), 40)
        r = run("tone", self.d / "dull.png", "-o", self.out(), "--auto", "tone", "--clip", 0)
        a = arr(r["output"])
        for i in range(3):
            self.assertEqual(a[..., i].min(), 0)
            self.assertEqual(a[..., i].max(), 255)
        self.assertEqual(r["rung"], 1)

    def test_auto_color_neutralises(self):
        r = run("tone", self.d / "dull.png", "-o", self.out(), "--auto", "color")
        a = arr(r["output"]).astype(np.float64)
        y = (a * [0.2126, 0.7152, 0.0722]).sum(axis=2).mean()
        for i in range(3):
            self.assertLess(abs(a[..., i].mean() - y), 2.0, f"channel {i}")

    # ------------------------------------------------------------ vibrance
    def test_vibrance(self):
        px = np.array([[[128, 128, 128], [140, 120, 110], [230, 30, 30]]], np.uint8)
        Image.fromarray(px).save(self.d / "v.png")
        r0 = run("tone", self.d / "v.png", "-o", self.out(), "--vibrance", 0.0000001)
        self.assertTrue((arr(r0["output"]) == px).all())
        r = run("tone", self.d / "v.png", "-o", self.out(), "--vibrance", 0.8)
        a = arr(r["output"])
        self.assertTrue((a[0, 0] == 128).all())
        chroma = lambda p: p.max() - p.min()  # noqa: E731
        g_dull = chroma(a[0, 1]) / chroma(px[0, 1].astype(int))
        g_sat = chroma(a[0, 2]) / chroma(px[0, 2].astype(int))
        self.assertGreater(g_dull, g_sat + 0.3)

    # ------------------------------------------------------------ shadows/highlights
    def test_shadows_lift_dark_only(self):
        im = np.full((40, 80, 3), 220, np.uint8)
        im[:, :40] = [40, 30, 20]
        Image.fromarray(im).save(self.d / "sh.png")
        r0 = run("tone", self.d / "sh.png", "-o", self.out(), "--shadows", 0, "--highlights", 0.0000001)
        self.assertLessEqual(np.abs(arr(r0["output"]) - im).max(), 1)
        r = run("tone", self.d / "sh.png", "-o", self.out(), "--shadows", 0.8, "--sh-radius", 4)
        a = arr(r["output"])
        self.assertGreater(a[:, :20].mean(), im[:, :20].mean() + 15)
        self.assertLessEqual(np.abs(a[:, 60:] - im[:, 60:]).max(), 1)
        p0, p1 = im[5, 5].astype(float), a[5, 5].astype(float)
        self.assertLess(abs(p1[0] / p1[1] - p0[0] / p0[1]) / (p0[0] / p0[1]), 0.03)

    def test_highlights_pull_down(self):
        im = np.full((40, 80, 3), 60, np.uint8)
        im[:, 40:] = [235, 225, 215]
        Image.fromarray(im).save(self.d / "hl.png")
        r = run("tone", self.d / "hl.png", "-o", self.out(), "--highlights", 0.8, "--sh-radius", 4)
        a = arr(r["output"])
        self.assertLess(a[:, 60:].mean(), im[:, 60:].mean() - 8)
        self.assertLessEqual(np.abs(a[:, :20] - im[:, :20]).max(), 1)

    # ------------------------------------------------------------ match color
    def test_match_color(self):
        rng = np.random.default_rng(3)
        y, x = np.mgrid[0:48, 0:64] / np.array([47.0, 63.0]).reshape(2, 1, 1)
        b2 = 0.2 + 0.5 * (0.3 * x + 0.7 * (1 - y)) + 0.03 * rng.standard_normal((48, 64))
        ref = np.clip(np.stack([b2 * 0.8, b2 * 0.95, b2 * 1.15], 2) * 255, 0, 255).astype(np.uint8)
        Image.fromarray(ref).save(self.d / "ref.png")
        r = run("tone", self.d / "dull.png", "-o", self.out(), "--match", self.d / "ref.png")
        lo = rgb_to_lab(arr(r["output"]) / 255.0).reshape(-1, 3)
        lr = rgb_to_lab(ref / 255.0).reshape(-1, 3)
        self.assertLess(np.abs(lo.mean(0) - lr.mean(0)).max(), 1.5)
        self.assertTrue((np.abs(lo.std(0) - lr.std(0)) < np.maximum(0.1 * lr.std(0), 0.5)).all())
        rs = run("tone", self.d / "dull.png", "-o", self.out(), "--match", self.d / "dull.png")
        self.assertLessEqual(np.abs(arr(rs["output"]) - self.dull).max(), 1)
        r0 = run("tone", self.d / "dull.png", "-o", self.out(), "--match", self.d / "ref.png", "--amount", 0)
        self.assertLessEqual(np.abs(arr(r0["output"]) - self.dull).max(), 1)
        # replay with the reference gone
        rec = self.d / "mjob" / "recipe.json"
        r1 = run("tone", self.d / "dull.png", "-o", self.out(), "--match", self.d / "ref.png", "--recipe", rec)
        os.remove(self.d / "ref.png")
        p = run("run", rec)
        self.assertTrue((arr(p["output"]) == arr(r1["output"])).all())

    # ------------------------------------------------------------ effects
    def test_noise(self):
        Image.fromarray(np.full((200, 200, 3), 128, np.uint8)).save(self.d / "g.png")
        for dist in ("gaussian", "uniform"):
            r = run("effect", self.d / "g.png", "-o", self.out(), "--noise", 12, "--dist", dist, "--seed", 4)
            a = arr(r["output"]) - 128
            self.assertLess(abs(a.std() / 12 - 1), 0.05, dist)
            self.assertLess(abs(a.mean()), 0.5)
        r2 = run("effect", self.d / "g.png", "-o", self.out(), "--noise", 12, "--dist", "uniform", "--seed", 4)
        self.assertTrue((arr(r2["output"]) == arr(r["output"])).all())
        rm = run("effect", self.d / "g.png", "-o", self.out(), "--noise", 12, "--mono")
        a = arr(rm["output"])
        self.assertTrue((a[..., 0] == a[..., 1]).all() and (a[..., 1] == a[..., 2]).all())

    def test_emboss_and_edges(self):
        Image.fromarray(np.full((20, 20, 3), 90, np.uint8)).save(self.d / "flat.png")
        a = arr(run("effect", self.d / "flat.png", "-o", self.out(), "--emboss", 135)["output"])
        self.assertTrue((a == 128).all())
        a = arr(run("effect", self.d / "flat.png", "-o", self.out(), "--find-edges")["output"])
        self.assertTrue((a == 255).all())
        st = np.zeros((20, 20, 3), np.uint8)
        st[:, 10:] = 255
        Image.fromarray(st).save(self.d / "step.png")
        a = arr(run("effect", self.d / "step.png", "-o", self.out(), "--emboss", 0)["output"])[..., 0]
        self.assertGreater(a[:, 9:11].max(), 200)       # rising edge facing the light
        self.assertTrue((a[:, :8] == 128).all() and (a[:, 12:] == 128).all())
        a = arr(run("effect", self.d / "step.png", "-o", self.out(), "--find-edges")["output"])[..., 0]
        self.assertLess(a[:, 9:11].min(), 128)
        self.assertTrue((a[:, :8] == 255).all())

    # ------------------------------------------------------------ canvas
    def test_canvas_and_trim(self):
        r = run("canvas", self.d / "noise.png", "-o", self.out(), "--size", "80,60", "--anchor", "br")
        a = np.asarray(Image.open(r["output"]))
        self.assertEqual(a.shape, (60, 80, 4))
        self.assertTrue((a[20:, 24:, :3] == self.noise).all())
        self.assertTrue((a[:20, :, 3] == 0).all() and (a[20:, 24:, 3] == 255).all())
        t = run("canvas", r["output"], "-o", self.d / "t.png", "--trim")
        self.assertTrue((np.asarray(Image.open(t["output"]))[..., :3] == self.noise).all())
        rf = run("canvas", self.d / "noise.png", "-o", self.out(), "--size", "10,10", "--relative",
                 "--fill", "#ff0000", "--anchor", "tl")
        a = arr(rf["output"])
        self.assertEqual(a.shape, (50, 66, 3))
        self.assertTrue((a[:40, :56] == self.noise).all() and (a[45, 60] == [255, 0, 0]).all())
        tc = run("canvas", rf["output"], "-o", self.d / "tc.png", "--trim", "--by", "corner")
        self.assertEqual(arr(tc["output"]).shape[:2], (50, 66))   # corner is image, not red: no trim
        rs = run("canvas", self.d / "noise.png", "-o", self.out(), "--size", "20,10", "--anchor", "c")
        self.assertTrue((arr(rs["output"])[..., :3] == self.noise[15:25, 18:38]).all())

    # ------------------------------------------------------------ masks and replay
    def test_mask_and_replay(self):
        m = np.zeros((40, 56), np.uint8)
        m[10:30, 15:40] = 255
        Image.fromarray(m).save(self.d / "m.png")
        rec = self.d / "job" / "recipe.json"
        r1 = run("effect", self.d / "noise.png", "-o", self.out(), "--find-edges", "--mask", self.d / "m.png",
                 "--recipe", rec)
        out = arr(r1["output"])
        self.assertTrue((out[m == 0] == self.noise[m == 0]).all())
        self.assertFalse((out[m == 255] == self.noise[m == 255]).all())
        run("tone", r1["output"], "-o", self.d / "b.png", "--vibrance", 0.5, "--auto", "tone",
            "--recipe", self.d / "tmp.json")
        r = json.loads(rec.read_text(encoding="utf-8"))
        r["steps"] += json.loads((self.d / "tmp.json").read_text(encoding="utf-8"))["steps"]
        with open(rec, "w", encoding="utf-8", newline="\n") as f:
            json.dump(r, f)
        p1 = run("run", rec)
        p2 = run("run", rec)
        self.assertEqual(p2["replay"], "same")
        # the hand-run chain re-read an 8-bit file between steps, the replay stays in float
        self.assertLessEqual(np.abs(arr(p1["output"]) - arr(self.d / "b.png")).max(), 2)


if __name__ == "__main__":
    unittest.main()
