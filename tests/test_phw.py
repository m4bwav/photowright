"""Proof bars for phw.py batch 1. Test images are generated here; nothing is downloaded.

Run: python -m unittest discover -s tests            (all rungs)
     PHW_RUNG_MAX=1 python -m unittest discover -s tests   (rung 2 hidden)
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "phw.py"
sys.path.insert(0, str(SCRIPT.parent))
import phw  # noqa: E402

RUNG_MAX = phw.rung_max()
warnings.simplefilter("ignore", ResourceWarning)  # PIL.Image.open in asserts


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(path):
    return phw.load(path).px


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        rng = np.random.default_rng(1)
        self.rgb = rng.uniform(0.05, 0.6, (24, 32, 3)).astype(np.float32)
        self.src = self.d / "src.png"
        Image.fromarray(np.round(self.rgb * 255).astype(np.uint8), "RGB").save(self.src)

    def tearDown(self):
        self.td.cleanup()

    def png(self, a, name, mode=None, **kw):
        p = self.d / name
        Image.fromarray(a, mode).save(p, **kw)
        return p


class TestInfo(Base):
    def test_doctor(self):
        r = run("doctor")
        self.assertIn("groups", r)
        for t in ("vtracer", "potrace", "inkscape", "gimp", "magick"):
            self.assertIn(t, r["on_path"])
        self.assertEqual(r["rung_max"], RUNG_MAX)
        if RUNG_MAX < 2:
            self.assertEqual(r["groups"]["denoise"]["rung"], 1)
            self.assertIsNone(r["modules"]["cv2"])

    def test_explain(self):
        self.assertEqual(run("explain", "multiply")["kind"], "blend mode")
        self.assertEqual(run("explain", "linear", "light")["kind"], "term")
        name = json.loads((phw.ROOT / "kb" / "tools.json").read_text(encoding="utf-8"))[0]["name"]
        self.assertEqual(run("explain", name)["kind"], "tool")
        self.assertEqual(run("explain", "multiplyy")["kind"], "unknown")

    def test_inspect(self):
        icc = phw.srgb_icc()
        ex = Image.Exif()
        ex[274] = 6
        a = np.zeros((10, 20, 4), np.uint8)
        p = self.png(a, "i.png", "RGBA", icc_profile=icc, exif=ex.tobytes())
        r = run("inspect", p)
        self.assertEqual(r["size"], [10, 20])
        self.assertEqual(r["exif_orientation"], 6)
        self.assertTrue(r["alpha"])
        self.assertEqual(r["bit_depth"], 8)
        self.assertIn("sRGB", r["icc_profile"])
        self.assertIn("Orientation", r["exif_tags"])
        frames = [Image.fromarray(np.full((4, 4), v, np.uint8)) for v in (0, 100, 200)]
        t = self.d / "multi.tif"
        frames[0].save(t, save_all=True, append_images=frames[1:])
        self.assertEqual(run("inspect", t)["layers"], 3)


class TestConvert(Base):
    def test_icc_kept_and_stripped(self):
        icc = phw.srgb_icc()
        p = self.png(np.zeros((8, 8, 3), np.uint8), "c.png", "RGB", icc_profile=icc)
        for fmt in ("png", "webp", "jpg", "tif"):
            out = run("convert", p, "--format", fmt)["output"]
            self.assertEqual(Image.open(out).info.get("icc_profile"), icc, fmt)
        out = run("convert", p, "--profile", "strip")["output"]
        self.assertIsNone(Image.open(out).info.get("icc_profile"))

    def test_convert_to_srgb_changes_pixels_on_purpose(self):
        # Pillow can only build sRGB/LAB/XYZ profiles, so this checks an untagged file gets an sRGB
        # label with unchanged pixels (R2); a real non-sRGB conversion waits for a test profile on disk.
        p = self.png(np.full((4, 4, 3), 120, np.uint8), "s.png", "RGB")
        r = run("convert", p, "--profile", "srgb")
        self.assertIn("sRGB", r["profile"])
        self.assertTrue(np.array_equal(np.asarray(Image.open(r["output"])), np.full((4, 4, 3), 120, np.uint8)))

    def test_16bit_png_stays_16bit(self):
        a16 = (np.arange(5 * 7 * 3).reshape(5, 7, 3) * 997 % 65536).astype(np.uint16)
        p = self.d / "s16.png"
        phw.write_png16(p, a16, phw.srgb_icc())
        r = run("convert", p, "--bits", "16")
        self.assertEqual(phw.png_bitdepth(r["output"])[0], 16)
        back, icc, _ = phw.read_png16(r["output"])
        self.assertTrue(np.array_equal(back, a16))
        self.assertIsNotNone(icc)
        r8 = run("convert", p, "--bits", "8")
        self.assertEqual(phw.png_bitdepth(r8["output"])[0], 8)

    def test_png16_reader_matches_opencv_written_file(self):
        # PNG filters other than None (Sub/Up/Avg/Paeth) come from an outside encoder.
        try:
            import cv2
        except ImportError:
            self.skipTest("cv2 not installed")
        a16 = (np.random.default_rng(3).integers(0, 65535, (9, 11, 3))).astype(np.uint16)
        p = self.d / "cv16.png"
        cv2.imwrite(str(p), a16[..., ::-1])
        back, _, _ = phw.read_png16(p)
        self.assertTrue(np.array_equal(back, a16))

    def test_exif_orientation_applied(self):
        a = np.zeros((10, 20, 3), np.uint8)
        a[0, 0] = 255  # top-left marker
        ex = Image.Exif()
        ex[274] = 6
        p = self.png(a, "o.png", "RGB", exif=ex.tobytes())
        out = run("convert", p)["output"]
        im = Image.open(out)
        self.assertEqual(im.size, (10, 20))
        self.assertNotEqual(im.getexif().get(274, 1), 6)
        ref = np.asarray(Image.open(p).transpose(Image.ROTATE_270))
        self.assertTrue(np.array_equal(np.asarray(im), ref))

    def test_metadata_strip(self):
        ex = Image.Exif()
        ex[0x010F] = "Camera"
        p = self.png(np.zeros((4, 4, 3), np.uint8), "m.png", "RGB", exif=ex.tobytes())
        self.assertIn(0x010F, Image.open(run("convert", p)["output"]).getexif())
        self.assertNotIn(0x010F, Image.open(run("convert", p, "--metadata", "strip")["output"]).getexif())


class TestNoOverwrite(Base):
    def test_never_overwrites(self):
        before = sha(self.src)
        target = self.d / "out.png"
        target.write_bytes(b"keep me")
        r = run("adjust", self.src, "-o", target, "--exposure", "0.5")
        self.assertEqual(Path(r["output"]).name, "out-001.png")
        self.assertEqual(target.read_bytes(), b"keep me")
        r2 = run("adjust", self.src, "-o", target, "--exposure", "0.5")
        self.assertEqual(Path(r2["output"]).name, "out-002.png")
        self.assertEqual(sha(self.src), before)
        r3 = run("crop", self.src, "-o", self.src, "--box", "0,0,4,4")
        self.assertNotEqual(Path(r3["output"]).resolve(), self.src.resolve())
        self.assertEqual(sha(self.src), before)


class TestAdjust(Base):
    tol = 1.5 / 255  # one 8-bit step plus rounding

    def adj(self, *args, src=None):
        return run("adjust", src or self.src, *args)

    def test_levels_reference(self):
        out = arr(self.adj("--levels", "0.1,0.7,1.5,0.05,0.95")["output"])
        x = np.round(self.rgb * 255) / 255
        ref = 0.05 + np.clip((x - 0.1) / 0.6, 0, 1) ** (1 / 1.5) * 0.9
        self.assertLess(np.abs(out - ref).max(), self.tol)

    def test_curves(self):
        x = np.linspace(0, 1, 101)
        self.assertLess(np.abs(phw.monotone_curve([[0, 0], [1, 1]], x) - x).max(), 1e-6)
        y = phw.monotone_curve([[0, 0], [0.5, 0.75], [1, 1]], x)
        self.assertAlmostEqual(float(y[50]), 0.75, places=5)
        self.assertTrue(np.all(np.diff(y) >= 0))
        out = arr(self.adj("--curves", "0,0 1,1")["output"])
        self.assertLess(np.abs(out - np.round(self.rgb * 255) / 255).max(), self.tol)

    def test_exposure_reference_and_round_trip(self):
        r = self.adj("--exposure", "1")
        out = arr(r["output"])
        x = np.round(self.rgb * 255) / 255
        ref = phw.to_enc(np.clip(phw.to_lin(x) * 2, 0, 1))
        self.assertLess(np.abs(out - ref).max(), self.tol)
        back = arr(run("adjust", r["output"], "--exposure", "-1")["output"])
        self.assertLess(np.abs(back - x).max(), 2.5 / 255)
        self.assertEqual(r["rung"], 1)

    def test_white_balance(self):
        out = arr(self.adj("--wb", "1.2,1,0.8")["output"])
        x = np.round(self.rgb * 255) / 255
        ref = phw.to_enc(np.clip(phw.to_lin(x) * np.array([1.2, 1, 0.8], np.float32), 0, 1))
        self.assertLess(np.abs(out - ref).max(), self.tol)
        cast = np.zeros((10, 10, 3), np.float32) + np.array([0.6, 0.5, 0.4], np.float32)
        p = self.png(np.round(cast * 255).astype(np.uint8), "cast.png", "RGB")
        g = arr(run("adjust", p, "--wb-gray", "5,5")["output"])[5, 5]
        self.assertLess(g.max() - g.min(), 2 / 255)

    def test_hue_round_trip(self):
        r = self.adj("--hue", "30")
        self.assertGreater(np.abs(arr(r["output"]) - np.round(self.rgb * 255) / 255).max(), 0.02)
        back = arr(run("adjust", r["output"], "--hue", "-30")["output"])
        self.assertLess(np.abs(back - np.round(self.rgb * 255) / 255).max(), 2.5 / 255)
        h, s, v = phw.rgb_to_hsv(self.rgb)
        self.assertLess(np.abs(phw.hsv_to_rgb(h, s, v) - self.rgb).max(), 1e-5)

    def test_saturation_zero_is_value_grey(self):
        out = arr(self.adj("--saturation", "0")["output"])
        x = np.round(self.rgb * 255) / 255
        self.assertLess(np.abs(out - x.max(axis=2, keepdims=True)).max(), self.tol)

    def test_lut_identity_and_invert(self):
        n = 5
        g = np.linspace(0, 1, n)
        lines = ["LUT_3D_SIZE 5"]
        for b in g:
            for gg in g:
                for r in g:
                    lines.append(f"{r} {gg} {b}")
        ident = self.d / "id.cube"
        ident.write_text("\n".join(lines))
        inv = self.d / "inv.cube"
        inv.write_text("\n".join(["TITLE \"inv\"", "LUT_3D_SIZE 5"] + [
            " ".join(str(1 - float(v)) for v in ln.split()) for ln in lines[1:]]))
        x = np.round(self.rgb * 255) / 255
        self.assertLess(np.abs(arr(self.adj("--lut", ident)["output"]) - x).max(), self.tol)
        self.assertLess(np.abs(arr(self.adj("--lut", inv)["output"]) - (1 - x)).max(), self.tol)

    def test_bw_channel_mix(self):
        r = self.adj("--bw", "0.5,0.3,0.2")
        out = arr(r["output"])
        self.assertEqual(out.shape[2], 1)
        x = np.round(self.rgb * 255) / 255
        ref = (x * np.array([0.5, 0.3, 0.2])).sum(axis=2, keepdims=True)
        self.assertLess(np.abs(out - ref).max(), self.tol)

    def test_mask_limits_edit(self):
        m = np.zeros((24, 32), np.uint8)
        m[:, 16:] = 255
        mp = self.png(m, "mask.png", "L")
        out = arr(self.adj("--exposure", "1", "--mask", mp)["output"])
        x = np.round(self.rgb * 255) / 255
        self.assertLess(np.abs(out[:, :16] - x[:, :16]).max(), 1e-6)
        self.assertGreater(np.abs(out[:, 16:] - x[:, 16:]).max(), 0.05)


class TestGeometry(Base):
    def test_crop_exact(self):
        out = arr(run("crop", self.src, "--rect", "3,4,10,6")["output"])
        x = np.round(self.rgb * 255) / 255
        self.assertTrue(np.allclose(out, x[4:10, 3:13], atol=1e-6))
        self.assertEqual(arr(run("crop", self.src, "--aspect", "1:1")["output"]).shape[:2], (24, 24))

    def test_resize_linear_light_checker(self):
        a = ((np.indices((32, 32)).sum(axis=0) % 2) * 255).astype(np.uint8)
        p = self.png(np.stack([a] * 3, axis=2), "checker.png", "RGB")
        r = run("resize", p, "--scale", "0.5")
        out = arr(r["output"])
        self.assertEqual(out.shape[:2], (16, 16))
        mid = out[3:-3, 3:-3]
        self.assertLess(abs(float(mid.mean()) - 0.735), 0.01)
        self.assertLess(float(mid.max() - mid.min()), 0.02)
        self.assertEqual(r["rung"], 1)

    def test_resize_alpha_no_dark_fringe(self):
        a = np.zeros((16, 16, 4), np.uint8)
        a[:, 8:] = (255, 255, 255, 255)  # white opaque right half, black transparent left
        p = self.png(a, "fringe.png", "RGBA")
        out = arr(run("resize", p, "--scale", "0.5")["output"])
        vis = out[..., 3] > 0.05
        self.assertGreater(float(out[..., :3][vis].min()), 0.97)

    def test_rotate_90_four_times(self):
        x = np.round(self.rgb * 255) / 255
        p = self.src
        for _ in range(4):
            p = run("rotate", p, "--angle", "90")["output"]
        self.assertTrue(np.array_equal(arr(p), x.astype(np.float32)))
        once = arr(run("rotate", self.src, "--angle", "90")["output"])
        self.assertTrue(np.allclose(once, np.rot90(x, 1), atol=1e-6))

    def test_flip_twice(self):
        p = run("rotate", self.src, "--flip", "h")["output"]
        self.assertTrue(np.allclose(arr(p), (np.round(self.rgb * 255) / 255)[:, ::-1], atol=1e-6))
        p2 = run("rotate", p, "--flip", "h")["output"]
        self.assertTrue(np.allclose(arr(p2), np.round(self.rgb * 255) / 255, atol=1e-6))

    def test_straighten_no_empty_corners(self):
        p = self.png(np.full((60, 80, 3), 200, np.uint8), "flat.png", "RGB")
        r = run("rotate", p, "--angle", "7", "--straighten")
        out = arr(r["output"])
        self.assertLess(np.abs(out - 200 / 255).max(), 2 / 255)
        self.assertLess(out.shape[1], 80)
        expanded = arr(run("rotate", p, "--angle", "7")["output"])
        self.assertGreater(expanded.shape[1], 80)
        self.assertLess(float(expanded[0, 0].max()), 0.05)  # black fill corner


class TestFilters(Base):
    def test_blur_rungs_agree(self):
        ch = np.random.default_rng(2).random((20, 30)).astype(np.float32)
        u1, u2 = phw.Used(), phw.Used()
        old = os.environ.get("PHW_RUNG_MAX")
        os.environ["PHW_RUNG_MAX"] = "1"
        try:
            b1 = phw.gaussian_blur(ch, 1.5, u1)
        finally:
            if old is None:
                del os.environ["PHW_RUNG_MAX"]
            else:
                os.environ["PHW_RUNG_MAX"] = old
        b2 = phw.gaussian_blur(ch, 1.5, u2)
        self.assertEqual(u1.items[0]["rung"], 1)
        self.assertLess(np.abs(b1 - b2).max(), 1e-4)

    def test_sharpen(self):
        flat = self.png(np.full((16, 16, 3), 90, np.uint8), "flat.png", "RGB")
        self.assertLess(np.abs(arr(run("sharpen", flat)["output"]) - 90 / 255).max(), 1e-6)
        a = np.full((16, 16, 3), 60, np.uint8)
        a[:, 8:] = 180
        e = self.png(a, "edge.png", "RGB")
        r = run("sharpen", e, "--amount", "1", "--radius", "1")
        out = arr(r["output"])
        self.assertLess(out[8, 7, 0], 60 / 255)
        self.assertGreater(out[8, 8, 0], 180 / 255)
        self.assertEqual(r["rung"], 2 if RUNG_MAX >= 2 and phw.probe("scipy.ndimage") else 1)

    def test_denoise(self):
        rng = np.random.default_rng(5)
        a = np.clip(0.5 + rng.normal(0, 0.06, (40, 40, 3)), 0, 1)
        p = self.png(np.round(a * 255).astype(np.uint8), "noisy.png", "RGB")
        r = run("denoise", p)
        self.assertLess(arr(r["output"]).std(), a.std() * 0.6)
        if RUNG_MAX < 2 or phw.probe("cv2") is None:
            self.assertEqual(r["rung"], 1)
            self.assertIn("median", " ".join(r["tool"]))
        else:
            self.assertEqual(r["rung"], 2)
        old = os.environ.get("PHW_RUNG_MAX")
        try:
            self.assertEqual(run("--rung-max", "1", "denoise", p)["rung"], 1)
        finally:
            if old is None:
                os.environ.pop("PHW_RUNG_MAX", None)
            else:
                os.environ["PHW_RUNG_MAX"] = old


class TestRecipe(Base):
    def test_record_and_replay(self):
        job = self.d / "job"
        rec = job / "recipe.json"
        run("adjust", self.src, "--exposure", "0.5", "--recipe", rec)
        run("crop", self.src, "--box", "2,2,20,18", "--recipe", rec)
        run("rotate", self.src, "--angle", "90", "--recipe", rec)
        run("resize", self.src, "--width", "8", "--recipe", rec)
        r = json.loads(rec.read_text())
        self.assertEqual([s["op"] for s in r["steps"]], ["adjust.exposure", "crop", "rotate", "resize"])
        self.assertEqual(r["source"]["sha256"], sha(self.src))
        first = run("run", rec)
        self.assertEqual(first["replay"], "first run")
        second = run("run", rec)
        self.assertEqual(second["replay"], "same")
        self.assertNotEqual(first["output"], second["output"])
        # resize records the intent (width 8, aspect kept at replay), so a recipe also fits other files in a
        # batch (Step E): crop 18x16 -> rotate 90 -> 16x18 -> width 8 -> 8x9
        self.assertEqual(r["steps"][-1]["params"].get("width"), 8)
        self.assertNotIn("height", r["steps"][-1]["params"])
        self.assertEqual(arr(second["output"]).shape[:2], (9, 8))
        log = [json.loads(x) for x in (job / "log.jsonl").read_text().splitlines()]
        self.assertTrue(all("rung" in x and "tool" in x for x in log))


class TestCLI(Base):
    def test_json_and_rung1_env(self):
        env = dict(os.environ, PHW_RUNG_MAX="1")
        out = subprocess.run([sys.executable, str(SCRIPT), "--json", "denoise", str(self.src)],
                             capture_output=True, text=True, env=env, check=True).stdout
        r = json.loads(out)
        self.assertEqual(r["rung"], 1)
        out = subprocess.run([sys.executable, str(SCRIPT), "--json", "doctor"], capture_output=True, text=True,
                             env=env, check=True).stdout
        self.assertEqual(json.loads(out)["rung_max"], 1)


if __name__ == "__main__":
    unittest.main()
