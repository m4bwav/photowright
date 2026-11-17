"""Regressions from Step E (first real jobs, 2026-11-17). Each test is a failure seen on a real job.

- convert --recipe recorded nothing (profile and metadata steps were lost from batch recipes).
- resize --scale was recorded as the probe file's pixel size, so a batch stretched every file to it.
- the pixel tracer drew semi-transparent pixels opaque (overlap 0.91 on a soft-edged 24 px icon).
- vcheck scored a hard-edged (binary) source against an anti-aliased render: every edge pixel failed.
- PDF export rounded the page scale to 2 decimals: at 130.05 dpi the drawing missed the page by 0.7 %.
- a DXF for a laser carried the white background rectangle as a cut (export --drop leaves it out).
- sheet put wide frames in square cells (empty bands, labels far below the image).
"""
import json
import re
import sys
import tempfile
import unittest
import warnings
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import phw  # noqa: E402
from phw import vector as V, batchops as B  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


class StepE(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def sprite(self, name, w, h, seed):
        rng = np.random.default_rng(seed)
        pal = rng.integers(0, 256, (5, 4))
        pal[:, 3] = 255
        pal[0] = [0, 0, 0, 0]
        a = pal[rng.integers(0, 5, (h, w))].astype(np.uint8)
        p = self.d / "src" / name
        p.parent.mkdir(exist_ok=True)
        Image.fromarray(a, "RGBA").save(p)
        return p, a

    def test_batch_scale_and_convert_recorded(self):
        p1, a1 = self.sprite("a.png", 16, 24, 1)
        p2, a2 = self.sprite("b.png", 40, 8, 2)
        rec = self.d / "r.json"
        run("resize", p1, "--scale", 2, "--filter", "nearest", "-o", self.d / "x.png", "--recipe", rec)
        run("convert", self.d / "x.png", "--profile", "srgb", "--metadata", "strip", "-o", self.d / "y.png",
            "--recipe", rec)
        steps = json.loads(rec.read_text())["steps"]
        self.assertEqual([s["op"] for s in steps], ["resize", "convert"])
        self.assertEqual(steps[0]["params"].get("scale"), 2.0)
        run("batch", rec, self.d / "src", "--out", self.d / "out", "--ext", ".png", "--apply")
        for name, a in (("a.png", a1), ("b.png", a2)):
            o = Image.open(self.d / "out" / name)
            self.assertIsNotNone(o.info.get("icc_profile"))
            b = np.asarray(o.convert("RGBA"))
            self.assertEqual(b.shape[:2], (a.shape[0] * 2, a.shape[1] * 2))
            vis = a[..., 3] > 0
            self.assertTrue((b[::2, ::2][vis] == a[vis]).all())

    def test_old_width_height_recipe_still_replays(self):
        p, _ = self.sprite("a.png", 10, 10, 3)
        rec = self.d / "old.json"
        rec.write_text(json.dumps({"version": 1, "source": {"file": str(p)},
                                   "steps": [{"op": "resize", "params": {"width": 30, "height": 20,
                                                                         "filter": "nearest"}}]}))
        r = run("run", rec, "-o", self.d / "o.png")
        self.assertEqual(Image.open(r["output"]).size, (30, 20))

    def test_pixel_trace_keeps_partial_alpha(self):
        a = np.zeros((8, 8, 4), np.uint8)
        a[2:6, 2:6] = [200, 40, 40, 255]
        a[1, 2:6] = [200, 40, 40, 128]
        a[6, 2:6] = [40, 40, 200, 64]
        p = self.d / "soft.png"
        Image.fromarray(a, "RGBA").save(p)
        r = run("trace", p, "--kind", "pixel", "-o", self.d / "soft.svg")
        self.assertEqual(r["overlap"], 1.0)
        self.assertIn("fill-opacity", Path(r["output"]).read_text())
        doc = V.read_svg(r["output"])
        self.assertTrue(any(abs(sh.get("opacity", 1) - 128 / 255) < 1e-3 for sh in doc["shapes"]))

    def test_vcheck_hard_edged_source(self):
        im = Image.new("L", (256, 256), 255)
        d = ImageDraw.Draw(im)
        for i in range(12):
            d.polygon([(128, 128), (128 + 120 * np.cos(i / 2), 128 + 120 * np.sin(i / 2)),
                       (128 + 120 * np.cos(i / 2 + 0.15), 128 + 120 * np.sin(i / 2 + 0.15))], fill=0)
        p = self.d / "bw.png"
        im.save(p)
        svg = run("trace", p, "--kind", "logo", "--backend", "own", "-o", self.d / "bw.svg")["output"]
        r = run("vcheck", svg, "--source", p, "--kind", "logo")
        self.assertIn("overlap_antialiased", r)
        self.assertGreaterEqual(r["overlap"], r["overlap_antialiased"])
        self.assertGreaterEqual(r["overlap"], 0.97)

    def test_pdf_scale_exact_at_odd_dpi(self):
        doc = {"width": 512, "height": 512, "shapes": [
            {"fill": (0, 0, 0), "stroke": None, "width": 0, "rule": "nonzero",
             "subs": [{"start": (0, 0), "segs": [("L", (512, 0)), ("L", (512, 512))], "closed": True}]}]}
        pdf = V.to_pdf(doc, 130.05)
        box = float(re.search(rb"/MediaBox \[0 0 ([\d.]+)", pdf).group(1))
        z = re.search(rb"stream\n(.*)\nendstream", pdf, re.S).group(1)
        k = float(zlib.decompress(z).split(b" ")[0])
        self.assertAlmostEqual(512 * k, box, delta=0.01)

    def test_export_drop_background(self):
        im = Image.new("RGB", (64, 64), "white")
        ImageDraw.Draw(im).ellipse([16, 16, 48, 48], fill="black")
        p = self.d / "dot.png"
        im.save(p)
        svg = run("trace", p, "--kind", "logo", "--backend", "own", "-o", self.d / "dot.svg")["output"]
        r = run("export", svg, "--format", "dxf", "--units", "mm", "--drop", "ffffff", "-o", self.d / "dot.dxf")
        self.assertGreaterEqual(r["dropped_shapes"], 1)
        text = Path(r["output"]).read_text()
        self.assertNotIn("CFFFFFF", text.split("ENTITIES", 1)[1])
        self.assertIn("C000000", text)

    def test_sheet_wide_frames(self):
        p = self.d / "wide.png"
        Image.new("RGB", (864, 480), "red").save(p)
        img = B.sheet([p, p], ["a", "b"], cols=2, cell=320)
        self.assertLess(img.height, 320)


if __name__ == "__main__":
    unittest.main()
