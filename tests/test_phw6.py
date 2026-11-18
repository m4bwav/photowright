"""Proof bars for the Szeliski proposals (phw 0.7.0, ai-docs/notes/szeliski.md).

- levels/curves on luminance keep chroma where per-channel curves wash it out.
- equalisation has a strength and a tiled mode without block seams.
- bilateral denoise compares whole colours in Lab: no colour fringe at a red/green edge.
- perspective prefilters where it shrinks >2x: a zone plate shrunk 4x aliases less.
- layers "pyramid": a paste whose exposure differs leaves no step.
- stack --mode median gives a clean plate from frames with people walking through.
- upscale records invented_detail false (Lanczos); the model route says to flag it true.
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
from phw import core  # noqa: E402
from phw.masks import rgb_to_lab  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def save(arr, path):
    Image.fromarray(np.round(np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(path)
    return path


def read(path):
    return np.asarray(Image.open(path).convert("RGB"), np.float32) / 255


def chroma(rgb):
    lab = rgb_to_lab(rgb)
    return np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)


class Szeliski(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def chart(self):
        cols = [(0.7, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.3, 0.7), (0.7, 0.6, 0.2), (0.5, 0.2, 0.6), (0.3, 0.6, 0.6)]
        a = np.zeros((16, 16 * len(cols), 3), np.float32)
        for i, c in enumerate(cols):
            a[:, i * 16:(i + 1) * 16] = c
        return save(a, self.d / "chart.png")

    def test_levels_gamma_on_luminance_keeps_chroma(self):
        src = self.chart()
        c0 = chroma(read(src)).mean()
        lum = run("adjust", src, "--levels", "0,1,2.5", "-o", self.d / "lum.png")
        ch = run("adjust", src, "--levels", "0,1,2.5", "--on", "channels", "-o", self.d / "ch.png")
        cl, cc = chroma(read(lum["output"])).mean(), chroma(read(ch["output"])).mean()
        self.assertEqual(lum["rung"], 1)
        self.assertIn("luminance", " ".join(lum["tool"]))
        self.assertLess(cc, 0.8 * c0, "per-channel gamma should wash colour out (the book's failure mode)")
        self.assertGreater(cl, cc * 1.15, f"luminance chroma {cl:.1f} vs channels {cc:.1f}")

    def test_curves_on_luminance_and_old_recipe_replays_per_channel(self):
        src = self.chart()
        r = run("adjust", src, "--curves", "0,0 0.5,0.75 1,1", "-o", self.d / "c.png")
        self.assertEqual(r["steps"][0]["params"]["on"], "luminance")
        img = core.load(src)
        u = core.Used()
        old = core.op_curves(img, {"points": [[0, 0], [0.5, 0.75], [1, 1]]}, u)
        new = core.op_curves(img, {"points": [[0, 0], [0.5, 0.75], [1, 1]], "on": "luminance"}, u)
        self.assertGreater(np.abs(old.px - new.px).max(), 0.02)

    def test_equalize_strength_and_tiles(self):
        y = np.linspace(0.3, 0.5, 64)[None, :].repeat(64, 0)
        y[:32] *= 0.6
        src = save(np.repeat(y[..., None], 3, 2), self.d / "flat.png")
        full = read(run("adjust", src, "--equalize", "-o", self.d / "e1.png")["output"])[..., 0]
        half = read(run("adjust", src, "--equalize", "0.5", "-o", self.d / "e2.png")["output"])[..., 0]
        tiled = read(run("adjust", src, "--equalize", "--tiles", "4", "-o", self.d / "e3.png")["output"])[..., 0]
        self.assertGreater(full.max() - full.min(), 0.9)
        r0 = y.max() - y.min()
        self.assertTrue(r0 < half.max() - half.min() < full.max() - full.min())
        # no block seams: the biggest jump between neighbouring columns stays small
        j = np.abs(np.diff(tiled[40]))
        seams = j[[15, 31, 47]]
        inner = np.delete(j, [15, 31, 47])
        self.assertLessEqual(seams.max(), inner.max() + 0.01, f"tile seam jump {seams.max():.3f}")

    def test_bilateral_lab_no_colour_fringe(self):
        rng = np.random.default_rng(1)
        a = np.zeros((32, 32, 3), np.float32)
        a[:, :16] = (0.8, 0.15, 0.15)
        a[:, 16:] = (0.15, 0.6, 0.15)
        noisy = np.clip(a + rng.normal(0, 0.03, a.shape), 0, 1)
        src = save(noisy, self.d / "n.png")
        r = run("denoise", src, "--method", "bilateral", "--sigma-space", "2", "--sigma-color", "10",
                "-o", self.d / "b.png")
        self.assertEqual(r["rung"], 1)
        self.assertIn("bilateral", " ".join(r["tool"]))
        out = read(r["output"])
        self.assertLess(np.abs(out - a).mean(), np.abs(read(src) - a).mean() * 0.7)
        # edge columns keep their own colour: red stays red, green stays green
        self.assertLess(np.abs(out[:, 14:16] - a[:, 14:16]).mean(), 0.04)
        self.assertLess(np.abs(out[:, 16:18] - a[:, 16:18]).mean(), 0.04)

    def test_perspective_prefilter_zone_plate(self):
        n = 256
        yy, xx = np.mgrid[:n, :n].astype(np.float64) - n / 2
        z = 0.5 + 0.5 * np.cos(np.pi * (xx ** 2 + yy ** 2) / n)
        src = save(np.repeat(z[..., None], 3, 2), self.d / "zone.png")
        ref = read(run("resize", src, "--width", 64, "--height", 64, "-o", self.d / "ref.png")["output"])
        args = ["perspective", src, "--src", f"0,0 {n},0 {n},{n} 0,{n}", "--dst", "0,0 64,0 64,64 0,64",
                "--size", "64,64"]
        pre = run(*args, "-o", self.d / "pre.png")
        raw = run(*args, "--no-prefilter", "-o", self.d / "raw.png")
        self.assertIn("prefiltered", " ".join(pre["tool"]))
        self.assertEqual(pre["rung"], 1)
        e_pre = np.sqrt(((read(pre["output"]) - ref) ** 2).mean())
        e_raw = np.sqrt(((read(raw["output"]) - ref) ** 2).mean())
        print(f"zone plate 4x shrink RMS vs Lanczos: prefiltered {e_pre:.4f}, raw {e_raw:.4f}")
        self.assertLess(e_pre, 0.6 * e_raw)

    def test_perspective_small_change_unchanged(self):
        a = np.random.default_rng(2).random((32, 32, 3)).astype(np.float32)
        src = save(a, self.d / "s.png")
        r = run("perspective", src, "--keystone", "0.1", "-o", self.d / "k.png")
        self.assertNotIn("prefiltered", " ".join(r["tool"]))

    def test_pyramid_paste_leaves_no_step(self):
        w, hh = 256, 128
        save(np.full((hh, w, 3), 0.3, np.float32), self.d / "dark.png")
        save(np.full((hh, w, 3), 0.6, np.float32), self.d / "bright.png")
        m = np.zeros((hh, w), np.uint8)
        m[:, w // 2:] = 255
        Image.fromarray(m).save(self.d / "m.png")

        def doc(pyr, name):
            rp = self.d / name
            rp.write_text(json.dumps({"version": 1, "kind": "layers", "canvas": {"width": w, "height": hh},
                                      "layers": [{"file": "dark.png"},
                                                 {"file": "bright.png", "mask": "m.png", "pyramid": pyr}]}))
            return read(run("layers", rp)["output"])[64, :, 0]

        hard, pyr = doc(False, "hard.json"), doc(True, "pyr.json")
        self.assertGreater(np.abs(np.diff(hard)).max(), 0.25)
        self.assertLess(np.abs(np.diff(pyr)).max(), 0.1)
        self.assertAlmostEqual(float(pyr[0]), 0.3, delta=0.03)
        self.assertAlmostEqual(float(pyr[-1]), 0.6, delta=0.03)

    def test_stack_median_clean_plate(self):
        rng = np.random.default_rng(3)
        bg = rng.random((24, 40, 3)).astype(np.float32)
        files = []
        for k in range(5):
            f = bg.copy()
            f[6:18, k * 8:k * 8 + 6] = (1, 0, 0)  # a "person" in a new place each frame
            files.append(save(f, self.d / f"f{k}.png"))
        r = run("stack", *files, "--mode", "median", "-o", self.d / "plate.png")
        self.assertEqual(r["rung"], 1)
        self.assertLess(np.abs(read(r["output"]) - read(save(bg, self.d / "bg.png"))).max(), 1 / 255 + 1e-6)

    def test_upscale_records_invented_detail(self):
        src = save(np.random.default_rng(4).random((8, 8, 3)), self.d / "u.png")
        rp = self.d / "rec.json"
        run("upscale", src, "--scale", 2, "-o", self.d / "u2.png", "--recipe", rp)
        self.assertIs(json.loads(rp.read_text())["steps"][0]["params"]["invented_detail"], False)
        self.assertIn("invented_detail: true", phw.transform.ESRGAN_ROUTE)


if __name__ == "__main__":
    unittest.main()
