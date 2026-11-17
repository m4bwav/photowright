"""Proof bars for phw batch 4: batch, sheet, diff, trace, simplify, vcheck, export.

Run: python -m unittest discover -s tests            (all rungs)
     PHW_RUNG_MAX=1 python -m unittest discover -s tests   (rung 2 hidden: own tracers only)

Stated thresholds (numbers, not opinions), scored by render-back at 16x supersampling, share of pixels
within 24 (max channel) of the source; test images are the bake-off set (ai-docs/notes/bakeoff/src_*.png):
- overlap: logo and icon >= 0.97, line >= 0.94, photo >= 0.80, pixel sprite >= 0.999 with exact squares;
  the own region tracer alone >= 0.95 on logo and icon (its fallback bar); centreline >= CENTRE_MIN.
- node, path and colour counts within the per-kind budgets (2x the bake-off VTracer counts).
- no open paths, stray points or self-intersections in any trace.
- batch: sources unchanged, a second run writes nothing, a bad file is reported and the rest finish.
- exports: PDF xref offsets exact; DXF holds only POLYLINE/VERTEX/SEQEND; Inkscape opens the SVG, PDF and
  DXF and its PNG matches the own render-back (>= INK_MIN), skipped with a message when not found.
"""
import json
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
from phw import vector as V, vtrace as T, batchops as B  # noqa: E402

RUNG_MAX = phw.rung_max()
warnings.simplefilter("ignore", ResourceWarning)
BAKE = HERE.parent / "ai-docs" / "notes" / "bakeoff"
SRC = {"logo": "src_logo.png", "icon": "src_icon.png", "line": "src_lineart.png", "photo": "src_photo.png",
       "pixel": "src_sprite.png"}
OWN_MIN = 0.95
CENTRE_MIN = 0.90
INK_MIN = 0.99
MEASURED = {}


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def tmpdir(tc):
    d = tempfile.TemporaryDirectory()
    tc.addCleanup(d.cleanup)
    return Path(d.name)


class TestTrace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        cls.res = {}
        for kind, f in SRC.items():
            cls.res[kind] = run("--json", "trace", BAKE / f, "--kind", kind, "-o", cls.d / f"{kind}.svg")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_bars_per_kind(self):
        for kind, r in self.res.items():
            with self.subTest(kind=kind):
                MEASURED[f"trace {kind} (rung {r['rung']})"] = r["overlap"]
                self.assertGreaterEqual(r["overlap"], V.BARS[kind], r)
                self.assertTrue(r["pass"], r["fails"])
                st = r["structure"]
                self.assertEqual((st["open_paths"], st["stray_points"], st["self_intersections"]), (0, 0, 0))
                if RUNG_MAX < 2:
                    self.assertEqual(r["rung"], 1)

    def test_vtracer_is_default_when_present(self):
        if RUNG_MAX < 2 or not T.vtracer_ok():
            self.skipTest("vtracer absent or hidden: the own tracer is the default")
        self.assertIn("VTracer (MIT) in a subprocess", self.res["logo"]["tool"])

    def test_pixel_exact_squares(self):
        doc = V.read_svg(self.d / "pixel.svg")
        g = self.res["pixel"]["info"]["grid"]
        self.assertEqual(g, 8)
        for sh in doc["shapes"]:
            for s in sh["subs"]:
                pts = [s["start"]] + [seg[-1] for seg in s["segs"]]
                self.assertTrue(all(seg[0] == "L" for seg in s["segs"]))
                for p in pts:
                    self.assertEqual(p[0] % g, 0)
                    self.assertEqual(p[1] % g, 0)
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    self.assertTrue(a[0] == b[0] or a[1] == b[1], "edges are axis-aligned")
        src = np.asarray(Image.open(BAKE / SRC["pixel"]).convert("RGB"))
        self.assertEqual(int((V.render(doc, S=1) != src).any(axis=2).sum()), 0, "pixel-exact at 1x")

    def test_own_region_tracer_fallback_bar(self):
        for kind in ("logo", "icon"):
            with self.subTest(kind=kind):
                img = Image.open(BAKE / SRC[kind])
                doc, info, used = T.trace(img, kind, "own")
                self.assertEqual(used.rung(), 1)
                r = V.vcheck(V.parse_svg(V.to_svg(doc)), img, kind)
                MEASURED[f"own region tracer {kind}"] = r["overlap"]
                self.assertGreaterEqual(r["overlap"], OWN_MIN)
                self.assertGreaterEqual(r["overlap"], V.BARS[kind])
                self.assertTrue(r["pass"], r["fails"])
        self.assertGreaterEqual(info["hole_loops"], 1, "holes are traced as hole loops")

    def test_holes_survive(self):
        """A ring: the centre must stay background (hole loop + even-odd), not be filled."""
        im = Image.new("RGB", (64, 64), "white")
        ImageDraw.Draw(im).ellipse([8, 8, 56, 56], fill=(200, 0, 0))
        ImageDraw.Draw(im).ellipse([22, 22, 42, 42], fill="white")
        doc, info, _ = T.trace(im, "logo", "own")
        self.assertEqual(info["hole_loops"], 1)
        ren = V.render(V.parse_svg(V.to_svg(doc)))
        self.assertTrue((ren[32, 32] > 240).all(), ren[32, 32])
        self.assertTrue((np.abs(ren[12, 32].astype(int) - [200, 0, 0]) < 40).all() or ren[16, 32][0] > 180)

    def test_vtracer_crash_is_contained(self):
        if RUNG_MAX < 2 or not T.vtracer_ok():
            self.skipTest("vtracer absent or hidden")
        img = Image.open(BAKE / SRC["pixel"])
        doc, info, used = T.trace(img, "logo", "vtracer", vt_opts={"mode": "none", "colormode": "binary"})
        self.assertTrue(doc["shapes"])  # this process survived; either vtracer worked or the fallback ran
        if any("crashed" in n for n in doc["notes"]):
            self.assertEqual(used.rung(), 1)

    def test_centreline(self):
        im = Image.new("RGB", (160, 160), "white")
        ImageDraw.Draw(im).ellipse([20, 20, 140, 140], outline="black", width=3)
        ImageDraw.Draw(im).line([(30, 150), (130, 150)], fill="black", width=3)
        doc, info, _ = T.trace(im, "centreline")
        self.assertEqual(len(doc["shapes"]), 1)
        self.assertIsNone(doc["shapes"][0]["fill"])
        self.assertAlmostEqual(info["stroke_width"], 3.0, delta=1.0)
        self.assertEqual(info["strokes"], 2)
        P = np.vstack([V.flatten(s) for s in doc["shapes"][0]["subs"]])
        ring = P[P[:, 1] < 145]
        r = np.hypot(ring[:, 0] - 80.5, ring[:, 1] - 80.5)
        self.assertLess(float(np.abs(r - 59).max()), 1.5, "centreline within 1.5 px of the true centre")
        img = Image.open(BAKE / SRC["line"])
        doc, info, _ = T.trace(img, "centreline")
        ov = V.vcheck(doc, img, "centreline")["overlap"]
        MEASURED["centreline lineart"] = ov
        self.assertGreaterEqual(ov, CENTRE_MIN)

    def test_centreline_rung1_thinning(self):
        m = np.zeros((40, 40), bool)
        m[18:23, 5:35] = True
        sk = T.zhang_suen(m)
        self.assertLessEqual(int(sk.sum(axis=0)[8:32].max()), 1, "one pixel wide")
        self.assertGreater(int(sk.sum()), 20)


class TestVcheckRender(unittest.TestCase):
    def test_fill_rules_and_supersampling(self):
        sq = "M0 0L40 0L40 40L0 40Z M10 10L30 10L30 30L10 30Z"
        for rule, centre in (("evenodd", 255), ("nonzero", 0)):
            doc = V.parse_svg(f'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                              f'<path d="{sq}" fill="#000" fill-rule="{rule}"/></svg>')
            self.assertEqual(int(V.render(doc)[20, 20, 0]), centre, rule)
        doc = V.parse_svg('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4">'
                          '<rect x="0" y="0" width="2.5" height="4" fill="#000"/></svg>')
        self.assertEqual(int(V.render(doc)[1, 2, 0]), 128, "half-covered pixel is 50% at 16x")

    def test_structure_flags(self):
        doc = V.parse_svg('<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
                          '<path d="M0 0L20 20L20 0L0 20Z" fill="#000"/>'      # bowtie
                          '<path d="M30 30L40 30L40 40" fill="#000"/>'          # open
                          '<path d="M5 45L5.2 45L5.1 45.1Z" fill="#000"/></svg>')  # stray
        st = V.structure(doc)
        self.assertEqual((st["self_intersections"], st["open_paths"], st["stray_points"]), (1, 1, 1))

    def test_budget_fail_is_reported(self):
        r = V.vcheck(V.read_svg(BAKE / "vtracer_lineart.svg"), BAKE / SRC["line"], "logo")
        self.assertFalse(r["pass"])
        self.assertTrue(any(f.startswith("nodes") for f in r["fails"]))

    def test_render_back_matches_bakeoff(self):
        r = V.vcheck(V.read_svg(BAKE / "vtracer_logo.svg"), BAKE / SRC["logo"], "logo")
        self.assertAlmostEqual(r["overlap"], 0.9821, delta=0.005)
        self.assertEqual(r["counts"]["nodes"], 56)


class TestSimplifyExport(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir(self)
        self.svg = Path(run("--json", "trace", BAKE / SRC["icon"], "--kind", "icon", "--backend", "own",
                           "-o", self.d / "i.svg")["output"])

    def test_simplify(self):
        r = run("--json", "simplify", self.svg, "--tolerance", "0.5")
        self.assertLessEqual(r["after"]["nodes"], r["before"]["nodes"])
        self.assertGreaterEqual(r["fidelity"], 0.98)
        r2 = run("--json", "simplify", BAKE / "vtracer_photo.svg", "-o", self.d / "p.svg", "--tolerance", "1.0")
        self.assertLess(r2["after"]["nodes"], r2["before"]["nodes"])
        self.assertGreaterEqual(r2["fidelity"], 0.95)
        r3 = run("--json", "simplify", self.svg, "--method", "rdp", "--tolerance", "0.5")
        self.assertGreaterEqual(r3["fidelity"], 0.97)

    def test_pdf_xref(self):
        out = Path(run("--json", "export", self.svg, "--format", "pdf")["output"])
        b = out.read_bytes()
        self.assertTrue(b.startswith(b"%PDF-1.4"))
        x = int(re.search(rb"startxref\n(\d+)", b).group(1))
        self.assertTrue(b[x:].startswith(b"xref"))
        offs = [int(m) for m in re.findall(rb"(\d{10}) 00000 n", b)]
        for i, o in enumerate(offs, 1):
            self.assertTrue(b[o:].startswith(f"{i} 0 obj".encode()))

    def test_eps_and_dxf(self):
        eps = Path(run("--json", "export", self.svg, "--format", "eps")["output"]).read_text()
        self.assertTrue(eps.startswith("%!PS-Adobe-3.0 EPSF-3.0"))
        self.assertIn("%%BoundingBox: 0 0 192 192", eps)
        self.assertIn("eofill", eps)
        r = run("--json", "export", self.svg, "--format", "dxf", "--units", "mm")
        txt = Path(r["output"]).read_text()
        ents = V.read_dxf_entities(txt)
        self.assertEqual(set(ents) - {"EOF"}, {"POLYLINE", "VERTEX", "SEQEND"})
        self.assertIn("AC1009", txt)
        self.assertEqual(ents.count("POLYLINE"), ents.count("SEQEND"))

    def test_svg_roundtrip_and_never_overwrite(self):
        a = Path(run("--json", "export", self.svg, "--format", "svg")["output"])
        b = Path(run("--json", "export", self.svg, "--format", "svg")["output"])
        self.assertNotEqual(a, b)
        doc0, doc1 = V.read_svg(self.svg), V.read_svg(a)
        self.assertGreaterEqual(V.overlap(V.render(doc0), V.render(doc1)), 0.999)
        txt = a.read_text()
        for bad in ("<style", "class=", "<use", "<g", "transform="):
            self.assertNotIn(bad, txt)

    def test_inkscape_opens_exports(self):
        if V.inkscape() is None:
            self.skipTest("Inkscape not found (or hidden at rung 1): open check skipped")
        for kind in ("logo", "icon", "line", "pixel"):
            svg = Path(run("--json", "trace", BAKE / SRC[kind], "--kind", kind, "-o", self.d / f"{kind}.svg",
                           "--no-check")["output"])
            for fmt in ("svg", "pdf", "dxf"):
                with self.subTest(kind=kind, fmt=fmt):
                    r = run("--json", "export", svg, "--format", fmt, "--check")
                    self.assertTrue(r["inkscape"]["opened"])
                    if fmt != "dxf":
                        MEASURED[f"inkscape {fmt} {kind} vs own render"] = r["inkscape"]["overlap_vs_own_render"]
                        self.assertGreaterEqual(r["inkscape"]["overlap_vs_own_render"], INK_MIN)
                    else:
                        self.assertGreaterEqual(r["inkscape"]["paths_read"], 1)


class TestBatchSheetDiff(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir(self)
        self.src = self.d / "in"
        self.src.mkdir()
        rng = np.random.default_rng(3)
        for i in range(4):
            Image.fromarray(rng.integers(0, 255, (24, 32, 3), dtype=np.uint8)).save(self.src / f"im{i}.png")
        run("--json", "adjust", self.src / "im0.png", "--exposure", "0.5", "--recipe", self.d / "r" / "recipe.json",
            "-o", self.d / "seed.png")
        self.recipe = self.d / "r" / "recipe.json"

    def hashes(self):
        return {p.name: phw.sha256(p) for p in sorted(self.src.iterdir())}

    def test_dry_run_apply_rerun_failure(self):
        (self.src / "broken.png").write_bytes(b"not a png")
        before = self.hashes()
        r = run("--json", "batch", self.recipe, self.src)
        self.assertEqual(r["mode"], "dry run")
        self.assertEqual(len(r["would_write"]), 5)
        out = Path(r["output_folder"])
        self.assertFalse(out.exists(), "dry run writes nothing")
        r = run("--json", "batch", self.recipe, self.src, "--apply")
        self.assertEqual(len(r["written"]), 4)
        self.assertEqual([f["source"] for f in r["failed"]], ["broken.png"])
        self.assertEqual(self.hashes(), before, "no source changed")
        snap = {p.name: phw.sha256(p) for p in out.glob("*.png")}
        r = run("--json", "batch", self.recipe, self.src, "--apply")
        self.assertEqual(r["written"], [])
        self.assertEqual(len(r["skipped"]), 4)
        self.assertEqual({p.name: phw.sha256(p) for p in out.glob("*.png")}, snap, "second run changes nothing")
        a = np.asarray(Image.open(self.src / "im1.png"), np.float32)
        b = np.asarray(Image.open(out / "im1.png"), np.float32)
        self.assertGreater(b.mean(), a.mean(), "exposure +0.5 applied")

    def test_recipe_change_never_overwrites(self):
        out = Path(run("--json", "batch", self.recipe, self.src, "--apply")["output_folder"])
        snap = {p.name: phw.sha256(p) for p in out.glob("*.png")}
        r = json.loads(self.recipe.read_text())
        r["steps"][0]["params"]["stops"] = 1.0
        self.recipe.write_text(json.dumps(r))
        res = run("--json", "batch", self.recipe, self.src, "--apply")
        self.assertEqual(len(res["written"]), 4)
        self.assertTrue(all("-001" in w["output"] for w in res["written"]))
        for k, h in snap.items():
            self.assertEqual(phw.sha256(out / k), h)

    def test_sheet(self):
        r = run("--json", "sheet", self.src / "im0.png", self.src / "im1.png", "--labels", "before,after",
                "--cell", "100", "-o", self.d / "s.png")
        im = Image.open(r["output"])
        w0, h0 = Image.open(self.src / "im0.png").size
        ch = round(100 * h0 / w0)  # cells are as tall as the inputs' aspect needs (Step E)
        self.assertEqual(im.size, (2 * 100 + 3 * 12, ch + 22 + 2 * 12))  # label 12 px font + 10
        self.assertEqual(r["labels"], ["before", "after"])
        a = np.asarray(im.convert("RGB")).astype(int)
        self.assertGreater(a[12 + 50, 12 + 50].std() + a[12:112, 12:112].std(), 10, "cell has the image")

    def test_diff(self):
        A = np.full((50, 60, 3), 100, np.uint8)
        Bm = A.copy()
        Bm[5:10, 5:15] = 200
        Bm[30:40, 40:45] = 0
        Image.fromarray(A).save(self.d / "a.png")
        Image.fromarray(Bm).save(self.d / "b.png")
        r = run("--json", "diff", self.d / "a.png", self.d / "b.png")
        self.assertEqual(r["bbox"], [5, 5, 45, 40])
        self.assertEqual(r["regions"], 2)
        self.assertEqual(r["changed_pixels"], 50 + 50)
        self.assertTrue(Path(r["heatmap"]).exists())
        r = run("--json", "diff", self.d / "a.png", self.d / "a.png", "-o", self.d / "same.png")
        self.assertTrue(r["identical"])
        self.assertIsNone(r["psnr_db"])

    def test_components_diagonal(self):
        m = np.zeros((5, 5), bool)
        m[0, 0] = m[1, 1] = m[3, 3] = True
        self.assertEqual(B.components(m), 2)


def tearDownModule():
    if MEASURED:
        p = Path(tempfile.gettempdir()) / f"phw4-measured-rung{RUNG_MAX}.json"
        p.write_text(json.dumps(MEASURED, indent=1))


if __name__ == "__main__":
    unittest.main()
