"""Proof bars for batch 20 (phw 0.21.0): PDF/EPS open and video frames (rung 2, external programs).

- split_index: `a.pdf[3]` -> page 3; a plain path has no index; a file really named `x[2].png` is kept.
- PDF: a two-page PDF made by Pillow (red page, blue page) opens page 1 by default and page 2 with `[2]`;
  the colour of the page centre matches within 3/255; the recipe hashes the PDF itself.
- Video: a 6-frame clip made by ffmpeg (frame n has grey level 40*n) opens frame 4 with `[4]`;
  `frames --every 2` writes 3 PNGs whose levels rise.
- With PHW_RUNG_MAX=1 both refuse (never a silent wrong decode); EPS without Ghostscript refuses
  naming Ghostscript.
Tests that need pdftoppm/mutool or ffmpeg skip when the program is not on PATH.
"""
import json
import os
import shutil
import subprocess
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
from phw import docio  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)
HAS_PDF = bool(shutil.which("pdftoppm") or shutil.which("mutool"))
HAS_FF = bool(shutil.which("ffmpeg"))
HAS_GS = any(shutil.which(n) for n in ("gswin64c", "gswin32c", "gs"))


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def centre(p):
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.float64)
    h, w = a.shape[:2]
    return a[h // 2, w // 2]


class SplitIndex(unittest.TestCase):
    def test_split(self):
        self.assertEqual(docio.split_index("a.pdf[3]"), (Path("a.pdf"), 3))
        self.assertEqual(docio.split_index("a.pdf"), (Path("a.pdf"), None))
        self.assertEqual(docio.kind_of("c.MP4[2]"), "video")
        self.assertIsNone(docio.kind_of("c.png"))

    def test_real_bracket_name_kept(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x[2].png"
            Image.new("RGB", (4, 4)).save(p)
            self.assertEqual(docio.split_index(p), (p, None))


class Refusals(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_rung1_refuses(self):
        p = self.d / "a.pdf"
        Image.new("RGB", (20, 20), (255, 0, 0)).save(p)
        old = os.environ.get("PHW_RUNG_MAX")
        os.environ["PHW_RUNG_MAX"] = "1"
        try:
            with self.assertRaises(SystemExit) as c:
                run("adjust", p, "--exposure", "0.5", "-o", self.d / "o.png")
            self.assertIn("rung 2", str(c.exception))
        finally:
            if old is None:
                os.environ.pop("PHW_RUNG_MAX", None)
            else:
                os.environ["PHW_RUNG_MAX"] = old

    @unittest.skipIf(HAS_GS or phw.rung_max() < 2, "Ghostscript present, or rung 1 (refused before the GS check)")
    def test_eps_without_gs(self):
        p = self.d / "a.eps"
        p.write_text("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n", encoding="ascii")
        with self.assertRaises(SystemExit) as c:
            run("adjust", p, "--exposure", "0.5", "-o", self.d / "o.png")
        self.assertIn("Ghostscript", str(c.exception))


@unittest.skipUnless(HAS_PDF and phw.rung_max() >= 2, "needs pdftoppm or mutool, and rung 2")
class PdfOpen(unittest.TestCase):
    def test_pages(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            pdf = d / "two.pdf"
            red = Image.new("RGB", (100, 80), (220, 30, 30))
            blue = Image.new("RGB", (100, 80), (30, 30, 220))
            red.save(pdf, save_all=True, append_images=[blue], resolution=72)
            run("adjust", pdf, "--exposure", "0", "-o", d / "p1.png")
            r = run("adjust", f"{pdf}[2]", "--exposure", "0", "-o", d / "p2.png", "--recipe", d / "r.json")
            self.assertLess(np.abs(centre(d / "p1.png") - [220, 30, 30]).max(), 4)
            self.assertLess(np.abs(centre(d / "p2.png") - [30, 30, 220]).max(), 4)
            self.assertEqual(r["rung"], 2)
            self.assertTrue(any("page 2" in n for n in r["notes"]))
            rec = json.loads((d / "r.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rec["source"]["sha256"]), 64)


@unittest.skipUnless(HAS_FF and phw.rung_max() >= 2, "needs ffmpeg, and rung 2")
class VideoFrames(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        for n in range(6):
            Image.new("RGB", (64, 48), (40 * n,) * 3).save(self.d / f"in_{n}.png")
        self.vid = self.d / "clip.mkv"
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-framerate", "6", "-i",
                        str(self.d / "in_%d.png"), "-c:v", "ffv1", "-pix_fmt", "bgr0", str(self.vid)],
                       check=True)

    def tearDown(self):
        self.td.cleanup()

    def test_frame_index(self):
        run("adjust", f"{self.vid}[4]", "--exposure", "0", "-o", self.d / "f4.png")
        self.assertLess(np.abs(centre(self.d / "f4.png") - 160).max(), 3)

    def test_frames_command(self):
        r = run("frames", self.vid, self.d / "out", "--every", "2")
        self.assertEqual(r["frames"], 3)
        lv = [centre(p)[0] for p in sorted((self.d / "out").glob("frame_*.png"))]
        self.assertEqual(lv, sorted(lv))
        self.assertLess(abs(lv[1] - 80), 3)


if __name__ == "__main__":
    unittest.main()
