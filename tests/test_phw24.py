"""Proof bars for phw 0.26.0: `drift` scores an edit chain against round 0 (after arXiv:2611.06741, TailSteer).

A synthetic chain built from one textured image, each round adding a small yellow cast, a light blur and a pasted
local patch (the intended edit):
- median dE and the b* (yellow) shift rise round by round; sharpness falls below 1; the restart flag trips past
  --limit-de and names the first round over it.
- With the patch's mask, the patch is not scored: a chain whose only change is the patch scores dE 0 outside it.
- An identical chain scores dE 0, SSIM 1, no PSNR (no error) and no flag.
- --global: a round with an intended global change is not flagged, and later rounds are scored against it.
- --prev scores each round against the one before it.
- CIEDE2000 matches published test pairs (Sharma, Wu and Dalal 2005).
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from phw import batchops, core  # noqa: E402

PATCH = (40, 40, 72, 72)  # x0, y0, x1, y1


def base_image(n=128):
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:n, 0:n] / n
    img = np.stack([0.45 + 0.3 * x, 0.4 + 0.25 * y, 0.5 - 0.2 * x * y], -1)
    img += rng.normal(0, 0.04, (n, n, 3))          # texture, so blur shows up as lost sharpness
    img[::16, :, :] = 0.15                          # grid lines: edges
    img[:, ::16, :] = 0.15
    return Image.fromarray(np.rint(np.clip(img, 0, 1) * 255).astype(np.uint8))


def chain_round(prev, cast=True, blur=True, patch=True):
    im = prev
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(0.5))
    a = np.asarray(im, np.float64) / 255
    if cast:  # yellow cast: blue down, red and green a touch up (b* rises)
        a = np.clip(a * np.array([1.01, 1.01, 0.96]), 0, 1)
    out = Image.fromarray(np.rint(a * 255).astype(np.uint8))
    if patch:
        x0, y0, x1, y1 = PATCH
        out.paste((220, 30, 30), (x0, y0, x1, y1))
    return out


class DriftChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.mask = d / "mask.png"
        m = Image.new("L", (128, 128), 0)
        m.paste(255, PATCH)
        m.save(cls.mask)
        r0 = base_image()

        def write(prefix, n, **kw):
            paths, im = [d / f"{prefix}0.png"], r0
            r0.save(paths[0])
            for k in range(1, n + 1):
                im = chain_round(im, **kw)
                paths.append(d / f"{prefix}{k}.png")
                im.save(paths[-1])
            return [str(p) for p in paths]
        cls.chain = write("c", 5)
        cls.patch_only = write("p", 3, cast=False, blur=False)
        cls.same = write("s", 3, cast=False, blur=False, patch=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_drift_rises(self):
        r = batchops.drift(self.chain, masks=[self.mask], limit_de=4)
        de = [x["dE76_median"] for x in r["rounds"]]
        db = [x["db"] for x in r["rounds"]]
        self.assertEqual(de, sorted(de))
        self.assertTrue(all(b > a for a, b in zip(de, de[1:])), de)
        self.assertTrue(all(v > 0 for v in db), db)
        self.assertTrue(all(b > a for a, b in zip(db, db[1:])), db)
        self.assertTrue(all(x["sharpness_ratio"] < 1 for x in r["rounds"]))
        self.assertTrue(all(x["dE00_median"] <= x["dE76_median"] + 1e-9 for x in r["rounds"]))
        ps = [x["psnr_db"] for x in r["rounds"]]
        self.assertTrue(all(b < a for a, b in zip(ps, ps[1:])), ps)
        over = [x["round"] for x in r["rounds"] if x["dE76_median"] > 4]
        self.assertTrue(over, de)
        self.assertEqual(r["first_over_limit"], over[0])
        self.assertIn("restart from the original", r["advice"])

    def test_mask_ignores_the_edit(self):
        masked = batchops.drift(self.patch_only, masks=[self.mask])
        for x in masked["rounds"]:
            self.assertEqual(x["dE76_median"], 0.0)
            self.assertIsNone(x["psnr_db"])
            self.assertEqual(x["over10_share"], 0.0)
        unmasked = batchops.drift(self.patch_only)
        self.assertGreater(unmasked["rounds"][0]["over10_share"], 0.05)
        self.assertIsNotNone(unmasked["rounds"][0]["psnr_db"])
        self.assertAlmostEqual(masked["scored_share"], 1 - 32 * 32 / 128 ** 2, places=4)

    def test_identical_chain(self):
        r = batchops.drift(self.same)
        for x in r["rounds"]:
            self.assertEqual(x["dE76_median"], 0.0)
            self.assertEqual(x["dE00_median"], 0.0)
            self.assertAlmostEqual(x["ssim"], 1.0, places=6)
            self.assertIsNone(x["psnr_db"])
            self.assertEqual(x["sharpness_ratio"], 1.0)
            self.assertFalse(x["over_limit"])
        self.assertIsNone(r["first_over_limit"])

    def test_global_round(self):
        # round 2 of the cast chain marked as an intended global change: not flagged even when far off,
        # and rounds 3+ are scored against round 2 (so they drift less than against round 0)
        plain = batchops.drift(self.chain, masks=[self.mask], limit_de=0.5)
        g = batchops.drift(self.chain, masks=[self.mask], global_rounds=[2], limit_de=0.5)
        self.assertTrue(plain["rounds"][1]["over_limit"])
        self.assertFalse(g["rounds"][1]["over_limit"])
        self.assertTrue(g["rounds"][1]["global"])
        self.assertEqual(g["rounds"][2]["against"], 2)
        self.assertLess(g["rounds"][2]["dE76_median"], plain["rounds"][2]["dE76_median"])

    def test_prev(self):
        r = batchops.drift(self.chain, prev=True, masks=[self.mask])
        self.assertEqual([x["against"] for x in r["rounds"]], [0, 1, 2, 3, 4])
        last0 = batchops.drift(self.chain, masks=[self.mask])["rounds"][-1]["dE76_median"]
        self.assertLess(r["rounds"][-1]["dE76_median"], last0)

    def test_cli_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            core.cli(["drift", *self.chain, "--mask", str(self.mask), "--global", "3", "--limit-de", "4", "--json"])
        r = json.loads(buf.getvalue())
        self.assertEqual(r["command"], "drift")
        self.assertEqual(len(r["rounds"]), 5)
        self.assertTrue(r["rounds"][2]["global"])
        self.assertIn("2611.06741", r["source"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            core.cli(["drift", *self.chain])
        self.assertIn("dE76", buf.getvalue())


class CIEDE2000(unittest.TestCase):
    def test_sharma_pairs(self):
        pairs = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
                 ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
                 ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
                 ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
                 ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082)]
        a = np.array([p[0] for p in pairs])
        b = np.array([p[1] for p in pairs])
        got = batchops.de2000(a, b)
        for g, (_, _, want) in zip(got, pairs):
            self.assertAlmostEqual(float(g), want, places=4)
        self.assertTrue(np.allclose(batchops.de2000(b, a), got))


if __name__ == "__main__":
    unittest.main()
