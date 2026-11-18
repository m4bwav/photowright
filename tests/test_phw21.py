"""Proof bars for batch 21 (phw 0.22.0): Inkscape manual lessons for trace, simplify, vcheck and export
(ai-docs/notes/inkscape-manual.md, candidates 1-7, 9, 12).

- 1 node-count fixture: a raster circle traced by the own tracer has few nodes (<= 16 at the default
  tolerance) and the count falls as the fit tolerance rises (Inkscape: 42 / 25 / 5 by alphamax and
  opttolerance); render-back overlap stays >= 0.99.
- 2 speckle suppression: with --speckle A no closed subpath under A px^2 remains.
- 3 stack mode: stacked layers cover the layers above them; unstacked layers do not overlap;
  --no-background drops the bottom page rectangle.
- 4 brightness steps: --scans N gives exactly N layers (Inkscape gives N+1) and states the thresholds.
- 5 pre-blur: --blur lowers the node count on a halftone screen by at least 10x.
- 6 simplify tolerance is absolute (document units): the same shape 10x bigger keeps more nodes and
  never moves more than the tolerance.
- 7 path parser: implicit repeats, H/V, S/T reflections, arcs as cubics (area of a circle within 1%),
  open filled paths reported.
- 9 export --units mm: width/height in mm and a viewBox in mm (1 user unit = 1 mm).
- 12 clips: a clip-path is reported in the notes, never silently dropped (boolean clipping not built).
"""
import math
import re
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import phw  # noqa: E402
from phw import vector as V, vtrace as T  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def circle(n=128, r=40):
    im = Image.new("RGB", (n, n), "white")
    ImageDraw.Draw(im).ellipse((n / 2 - r, n / 2 - r, n / 2 + r, n / 2 + r), fill="black")
    return im


def painted(doc, sh):
    """Boolean mask of the pixels one shape paints (rendered alone on white)."""
    ren = V.render(dict(doc, shapes=[dict(sh, fill=(0, 0, 0))]), int(doc["width"]), int(doc["height"]))
    return ren.max(2) < 128


def sub_area(s):
    P = V.flatten(s, per_px=1.0)
    return abs(V.signed_area(P))


class TestTrace(unittest.TestCase):
    def test_1_circle_node_count(self):
        im = circle()
        n = []
        for tol in (0.3, 0.6, 1.5):
            doc, _, _ = T.trace(im, "logo", "own", tol)
            n.append(V.counts(doc)["nodes"])
            self.assertGreaterEqual(V.vcheck(doc, im, "logo")["overlap"], 0.99)
        self.assertLessEqual(n[1], 16)
        self.assertTrue(n[0] >= n[1] >= n[2], n)

    def test_2_speckle(self):
        im = Image.new("RGB", (64, 64), "white")
        d = ImageDraw.Draw(im)
        d.rectangle((20, 20, 43, 43), fill="black")
        for x, y in ((3, 3), (8, 50), (55, 6), (50, 55)):
            d.rectangle((x, y, x + 1, y + 1), fill="black")      # 2x2 dots: area 4
        keep, _, _ = T.trace(im, "logo", "own", speckle=2)
        drop, info, _ = T.trace(im, "logo", "own", speckle=10)
        subs = [s for sh in drop["shapes"][1:] for s in sh["subs"]]
        self.assertTrue(subs)
        self.assertTrue(all(sub_area(s) >= 10 for s in subs), [sub_area(s) for s in subs])
        self.assertGreater(sum(len(sh["subs"]) for sh in keep["shapes"][1:]), len(subs))
        self.assertGreaterEqual(info["speckles_dropped"], 4)

    def _two(self):
        im = Image.new("RGB", (96, 96), "white")
        d = ImageDraw.Draw(im)
        d.rectangle((15, 15, 70, 70), fill=(220, 30, 30))
        d.rectangle((30, 30, 55, 55), fill=(30, 30, 220))
        return im

    def test_3_stack_modes(self):
        im = self._two()
        flat, info, _ = T.trace(im, "logo", "own", stack=False)
        self.assertFalse(info["stacked"])
        red, blue = painted(flat, flat["shapes"][1]), painted(flat, flat["shapes"][2])
        self.assertLess((red & blue).sum(), 0.02 * blue.sum())          # no overlap (anti-alias edge only)
        st, info, _ = T.trace(im, "logo", "own", stack=True)
        self.assertTrue(info["stacked"])
        red, blue = painted(st, st["shapes"][1]), painted(st, st["shapes"][2])
        self.assertGreater((red & blue).sum(), 0.98 * blue.sum())       # red covers blue: no seam gap
        nb, info, _ = T.trace(im, "logo", "own", background=False)
        self.assertEqual(len(nb["shapes"]), len(flat["shapes"]) - 1)
        self.assertNotEqual(tuple(nb["shapes"][0]["fill"]), (255, 255, 255))

    def test_4_exact_scans(self):
        gr = Image.fromarray(np.tile(np.linspace(0, 255, 200).astype(np.uint8), (50, 1))).convert("RGB")
        for n in (2, 4, 7):
            doc, info, _ = T.trace(gr, "logo", "own", scans=n, background=False)
            self.assertEqual(len(doc["shapes"]), n)
            self.assertEqual(len(info["thresholds"]), n)
            self.assertEqual(info["thresholds"], sorted(info["thresholds"]))

    def test_5_preblur_halftone(self):
        g = np.tile(np.linspace(0, 1, 192), (192, 1))
        yy, xx = np.mgrid[:192, :192]
        cx, cy = (xx % 6) - 2.5, (yy % 6) - 2.5
        ht = Image.fromarray(np.where(np.hypot(cx, cy) < 3.6 * np.sqrt(1 - g), 0, 255).astype(np.uint8)).convert("RGB")
        raw, _, _ = T.trace(ht, "logo", "own")
        bl, _, used = T.trace(ht, "logo", "own", blur=3)
        self.assertLess(V.counts(bl)["nodes"] * 10, V.counts(raw)["nodes"])
        self.assertIn("pre-blur", [u["op"] for u in used.items])

    def test_cli_flags(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "g.png"
            Image.fromarray(np.tile(np.linspace(0, 255, 120).astype(np.uint8), (40, 1))).save(src)
            r = run("trace", src, "-o", Path(td) / "g.svg", "--scans", 3, "--no-background", "--blur", 1,
                    "--speckle", 6, "--no-check")
            self.assertEqual(r["info"]["scans"], 3)
            self.assertEqual(len(V.read_svg(r["output"])["shapes"]), 3)


class TestVector(unittest.TestCase):
    def test_6_simplify_absolute(self):
        def ring(r):
            t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
            P = np.c_[200 + r * np.cos(t), 200 + r * np.sin(t)]
            return {"width": 400, "height": 400, "shapes": [{"fill": (0, 0, 0), "stroke": None, "width": 0,
                    "rule": "nonzero", "subs": [{"start": tuple(P[0]), "segs": [("L", tuple(p)) for p in P[1:]],
                                                 "closed": True}]}]}
        small = V.simplify_doc(ring(15), 0.5, "rdp")
        big = V.simplify_doc(ring(150), 0.5, "rdp")
        self.assertGreater(V.counts(big)["nodes"], 2 * V.counts(small)["nodes"])
        Q = V.flatten(big["shapes"][0]["subs"][0], per_px=0.5)
        self.assertLess(np.abs(np.hypot(Q[:, 0] - 200, Q[:, 1] - 200) - 150).max(), 0.5 + 1e-6)

    def test_7_parser(self):
        subs, _ = V.parse_d("M0 0 10 0 10 10 0 10z")
        self.assertEqual(len(subs[0]["segs"]), 3)
        self.assertTrue(subs[0]["closed"])
        subs, _ = V.parse_d("m5 5 h10 v10 H5 V5")
        self.assertEqual([g[1] for g in subs[0]["segs"]], [(15, 5), (15, 15), (5, 15), (5, 5)])
        subs, _ = V.parse_d("M0 0 C0 10 10 10 10 0 S20 -10 20 0")
        self.assertEqual(subs[0]["segs"][1][1], (10, -10))               # reflected control point
        subs, _ = V.parse_d("M0 0 Q5 10 10 0 T20 0")
        self.assertEqual(len(subs[0]["segs"]), 2)
        self.assertAlmostEqual(subs[0]["segs"][1][1][1], -20 / 3, places=6)   # T reflects to (15,-10)
        subs, arcs = V.parse_d("M0 50 A50 50 0 1 0 100 50 A50 50 0 1 0 0 50Z")
        self.assertEqual(arcs, 2)
        self.assertTrue(all(g[0] == "C" for g in subs[0]["segs"]))
        P = V.flatten(subs[0], per_px=0.5)
        self.assertAlmostEqual(abs(V.signed_area(P)) / (math.pi * 2500), 1, delta=0.01)
        r = np.hypot(P[:, 0] - 50, P[:, 1] - 50)
        self.assertLess(np.abs(r - 50).max(), 0.05)
        subs, _ = V.parse_d("M0 0 a10 5 30 0 1 20 0")                    # rotated ellipse ends on target
        self.assertTrue(np.allclose(subs[0]["segs"][-1][-1], (20, 0)))
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
               '<path d="M2 2 L18 2 L18 18" fill="#000"/></svg>')
        self.assertEqual(V.vcheck(V.parse_svg(svg))["structure"]["open_paths"], 1)

    def test_9_mm_viewbox(self):
        doc = {"width": 192, "height": 96, "shapes": [{"fill": (0, 0, 0), "stroke": None, "width": 0,
               "rule": "nonzero", "subs": [{"start": (96, 0), "segs": [("L", (192, 0)), ("L", (192, 96))],
                                            "closed": True}]}]}
        s = V.to_svg(doc, "mm")
        self.assertIn('width="50.8mm" height="25.4mm"', s)
        self.assertIn('viewBox="0 0 50.8 25.4"', s)
        self.assertIn("M25.4 0", s)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.svg"
            src.write_text(V.to_svg(doc), encoding="utf-8")
            r = run("export", src, "-o", Path(td) / "b.svg", "--units", "mm")
            out = Path(r["output"]).read_text(encoding="utf-8")
            self.assertTrue(re.search(r'viewBox="0 0 50.8 25.4"', out))

    def test_12_clip_noted(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><defs><clipPath id="c">'
               '<rect width="10" height="10"/></clipPath></defs>'
               '<rect width="20" height="20" clip-path="url(#c)"/></svg>')
        doc = V.parse_svg(svg)
        self.assertTrue(any("clip-path" in n for n in doc["notes"]))


if __name__ == "__main__":
    unittest.main()
