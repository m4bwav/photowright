"""Proof bars for batch 19 (phw 0.20.0): the rung 2 rows of the coverage table.

- camraw (Camera Raw Basic panel, rung 1): all sliders 0 refuses; out-of-range refuses; --exposure 1
  equals the exposure op bit for bit; --temp +50 warms (R/B rises) and --tint +50 lowers green;
  --contrast +50 darkens a dark patch, brightens a bright one and keeps 18% grey within 2/255;
  --whites +100 lifts highlights more than shadows, --blacks -100 drops shadows more than highlights;
  replay of the recipe is bit-exact.
- HEIC/JXL: without pillow-heif / pillow-jxl-plugin the load refuses with the pip line (never a wrong decode).
- Camera raw: decoded through rawpy (a stand-in module here, so the test needs no raw sample) into a
  16-bit Img with the sRGB profile; with PHW_RUNG_MAX=1 it refuses.
- C2PA verify: without c2patool the report says it did not run; with a tool its JSON is parsed.
"""
import json
import os
import sys
import tempfile
import types
import unittest
import warnings
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import phw  # noqa: E402
from phw import core, rawio  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.float64)


class FakeRaw:
    sizes = types.SimpleNamespace(height=4, width=6, raw_height=4, raw_width=6)
    num_colors = 3
    raw_pattern = np.array([[0, 1], [3, 2]])
    camera_whitebalance = [2.0, 1.0, 1.5, 1.0]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def postprocess(self, **kw):
        assert kw["output_bps"] == 16 and kw["use_camera_wb"]
        a = np.zeros((4, 6, 3), np.uint16)
        a[..., 0] = 65535
        a[1, 2] = 32768
        return a


class Batch19(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw19-"))
        ramp = np.linspace(0, 255, 64)[None, :, None].repeat(16, 0)
        col = np.concatenate([ramp, ramp * 0.8 + 20, ramp * 0.6 + 40], axis=2)
        self.src = self.d / "src.png"
        Image.fromarray(np.round(col).astype(np.uint8)).save(self.src)

    def cam(self, *args):
        return arr(run("camraw", self.src, "-o", self.d / f"o{len(list(self.d.iterdir()))}.png", *args)["output"])

    def test_refusals(self):
        with self.assertRaises(SystemExit):
            run("camraw", self.src)
        with self.assertRaises(SystemExit):
            run("camraw", self.src, "--clarity", "150")

    def test_exposure_matches_op(self):
        out = self.cam("--exposure", "1")
        img = core.load(self.src)
        ref = np.round(np.clip(core.op_exposure(img, {"stops": 1}, core.Used()).px, 0, 1) * 255)
        self.assertEqual(float(np.abs(out - ref).max()), 0.0)

    def test_temp_tint(self):
        a = arr(self.src)
        w = self.cam("--temp", "50")
        m = slice(10, 50)
        self.assertGreater((w[:, m, 0] / w[:, m, 2]).mean(), (a[:, m, 0] / a[:, m, 2]).mean() * 1.1)
        t = self.cam("--tint", "50")
        self.assertLess(t[:, m, 1].mean(), a[:, m, 1].mean() - 3)

    def test_contrast_whites_blacks(self):
        g = self.d / "g.png"
        Image.fromarray(np.array([[[30] * 3, [118] * 3, [220] * 3]], np.uint8)).save(g)
        self.src = g
        c = self.cam("--contrast", "50")[0]
        self.assertLess(c[0, 0], 30)
        self.assertGreater(c[2, 0], 220)
        self.assertLessEqual(abs(c[1, 0] - 118), 2)
        w = self.cam("--whites", "100")[0]
        self.assertGreater(w[2, 0] - 220, w[0, 0] - 30)
        b = self.cam("--blacks", "-100")[0]
        self.assertGreater(30 - b[0, 0], 220 - b[2, 0])

    def test_replay(self):
        rec = self.d / "r.json"
        r = run("camraw", self.src, "--temp", "20", "--contrast", "30", "--shadows", "40", "--highlights", "-40",
                "--clarity", "25", "--vibrance", "30", "-o", self.d / "a.png", "--recipe", rec)
        o2 = run("run", rec, "-o", self.d / "b.png")["output"]
        self.assertTrue(np.array_equal(arr(r["output"]), arr(o2)))
        self.assertLessEqual(r["rung"], 2)  # 2 only when scipy blurs for clarity; rung 1 alone also works

    def test_heif_jxl_refuse(self):
        for ext, mod, pipname in ((".heic", "pillow_heif", "pillow-heif"), (".jxl", "pillow_jxl", "pillow-jxl-plugin")):
            if core.probe(mod) is not None:
                continue
            f = self.d / ("x" + ext)
            f.write_bytes(b"\0" * 32)
            with self.assertRaises(SystemExit) as cm:
                core.load(f)
            self.assertIn(pipname, str(cm.exception))

    @unittest.skipIf(core.rung_max() < 2, "rung 2 route; PHW_RUNG_MAX < 2 refuses (checked in test_raw_through_rawpy)")
    def test_raw_through_rawpy(self):
        fake = types.SimpleNamespace(imread=lambda p: FakeRaw())
        f = self.d / "x.dng"
        f.write_bytes(b"\0" * 32)
        old = core._PROBED.get("rawpy", "unset")
        core._PROBED["rawpy"] = fake
        try:
            img = core.load(f)
            self.assertEqual(img.bits, 16)
            self.assertEqual(img.px.shape, (4, 6, 3))
            self.assertAlmostEqual(float(img.px[1, 2, 0]), 32768 / 65535, places=5)
            self.assertTrue(img.icc)
            r = run("inspect", f)
            self.assertEqual(r["size"], [4, 6])
            self.assertEqual(r["rung"], 2)
            os.environ["PHW_RUNG_MAX"] = "1"
            try:
                with self.assertRaises(SystemExit):
                    core.load(f)
            finally:
                del os.environ["PHW_RUNG_MAX"]
        finally:
            if old == "unset":
                core._PROBED.pop("rawpy", None)
            else:
                core._PROBED["rawpy"] = old

    @unittest.skipIf(core.rung_max() < 2, "rung 2 route; PHW_RUNG_MAX < 2 refuses (checked in test_raw_through_rawpy)")
    def test_c2pa_verify(self):
        r = rawio.c2pa_verify(self.src, tool=None) if not rawio.shutil.which("c2patool") else {"ran": False}
        self.assertFalse(r["ran"])
        script = self.d / "fake_c2patool.py"
        script.write_text("import json;print(json.dumps({'active_manifest':'urn:x','validation_status':[]}))",
                          encoding="utf-8", newline="\n")
        # the fake tool is "python fake_c2patool.py": c2pa_verify runs [tool, path]
        r = rawio.c2pa_verify(script, tool=sys.executable)
        self.assertTrue(r["ran"])
        self.assertTrue(r["valid"])
        self.assertEqual(r["active_manifest"], "urn:x")


if __name__ == "__main__":
    unittest.main()
