"""Rung 3 ComfyUI routes: graph builders and fallback offline (HTTP mocked), live runs when the
server at PHW_COMFY_URL (default http://127.0.0.1:8199) answers, skipped otherwise."""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import warnings
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import phw  # noqa: E402
from phw import comfy  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


LIVE_WAIT = os.environ.get("PHW_COMFY_TEST_WAIT", "240")


def live_skip_reason():
    """None when the live tests may run: server answers within 3 s, rung 3 not hidden and the
    queue is empty. A busy queue (another session's render) is skipped, never waited on, so the
    full suite always finishes; the live tests also cap each wait at PHW_COMFY_TEST_WAIT s."""
    if os.environ.get("PHW_RUNG_MAX") and int(os.environ["PHW_RUNG_MAX"]) < 3:
        return "rung 3 hidden"
    try:
        json.loads(comfy._req("/system_stats", timeout=3, tries=1))
        q = json.loads(comfy._req("/queue", timeout=3, tries=1))
    except (comfy.Unavailable, ValueError):
        return "ComfyUI server unreachable"
    ahead = len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
    return f"ComfyUI queue busy ({ahead} job(s))" if ahead else None


LIVE_SKIP = live_skip_reason()


def server_up():
    return LIVE_SKIP is None


def picture(path, k=1):
    w, h = 96 * k, 80 * k
    rng = np.random.default_rng(3)
    a = np.full((h, w, 3), 220, np.uint8)
    a[20 * k:60 * k, 30 * k:66 * k] = (180, 40, 30)          # a red box on a light ground
    a = np.clip(a.astype(int) + rng.integers(-6, 7, a.shape), 0, 255).astype(np.uint8)
    Image.fromarray(a).save(path)
    return a


class Graphs(unittest.TestCase):
    def links_ok(self, g):
        for nid, node in g.items():
            self.assertIn("class_type", node)
            for v in node["inputs"].values():
                if isinstance(v, list):
                    self.assertIn(v[0], g, f"{nid} links to missing node {v[0]}")
        self.assertEqual(g["out"]["class_type"], "PreviewImage")

    def test_birefnet_graph(self):
        g = comfy.graph_birefnet("a.png")
        self.links_ok(g)
        self.assertEqual(g["mdl"]["inputs"]["bg_removal_name"], "birefnet.safetensors")
        self.assertEqual(g["rb"]["class_type"], "RemoveBackground")

    def test_lama_graph(self):
        g = comfy.graph_lama("a.png", "m.png", 7)
        self.links_ok(g)
        self.assertEqual(g["inp"]["inputs"]["seed"], 7)
        self.assertEqual(g["mdl"]["inputs"]["model_name"], "big-lama.pt")

    def test_text_graph(self):
        g = comfy.graph_text_select("a.png", "the red box", 0)
        self.links_ok(g)
        self.assertEqual(g["run"]["inputs"]["task"], "caption_to_phrase_grounding")
        self.assertEqual(g["run"]["inputs"]["seed"], 1)  # Florence2Run seed min is 1
        self.assertEqual(g["sam"]["inputs"]["model"], "sam2.1_hiera_base_plus.safetensors")
        self.assertFalse(g["run"]["inputs"]["do_sample"])

    def test_qwen_edit_graph(self):
        g = comfy.graph_qwen_edit("a.png", "m.png", "replace the box with grass", 11)
        self.links_ok(g)
        self.assertEqual(g["unet"]["inputs"]["unet_name"], comfy.QWEN_EDIT)
        self.assertEqual(g["lora"]["inputs"]["lora_name"], comfy.QWEN_LORA)
        self.assertEqual(g["clip"]["inputs"], {"clip_name": comfy.QWEN_CLIP, "type": "qwen_image"})
        self.assertEqual(g["pos0"]["inputs"]["prompt"], "replace the box with grass")
        self.assertEqual(g["lat"]["inputs"]["mask"], ["msk", 0])
        self.assertEqual(g["ks"]["inputs"]["latent_image"], ["lat", 0])
        self.assertEqual((g["ks"]["inputs"]["seed"], g["ks"]["inputs"]["steps"]), (11, 4))
        self.assertEqual(g["msk"]["inputs"]["image"], ["mrs", 0])


class SeedVR2Graph(unittest.TestCase):

    def test_seedvr2_graph(self):
        g = comfy.graph_seedvr2("a.png", 192, 160, 4, comfy.SEEDVR2["3b"])
        Graphs.links_ok(self, g)
        self.assertEqual(g["ks"]["inputs"]["steps"], 1)
        self.assertEqual(g["rs"]["inputs"]["width"], 192)
        self.assertEqual(g["post"]["inputs"]["original_resized_images"], ["rs", 0])


class ICLightGraph(unittest.TestCase):

    def test_iclight_graph_with_direction(self):
        g = comfy.graph_iclight("a.png", "l.png", "warm sunset light", 5, 576, 512)
        Graphs.links_ok(self, g)
        classes = {n["class_type"] for n in g.values()}
        for c in ("LoadAndApplyICLightUnet", "ICLightConditioning", "DepthAnythingV2Preprocessor", "ImageBlend",
                  "CheckpointLoaderSimple"):
            self.assertIn(c, classes)
        self.assertEqual(g["ic"]["inputs"]["model_path"], comfy.ICLIGHT)
        self.assertEqual(g["depth"]["inputs"]["ckpt_name"], "depth_anything_v2_vits.pth")  # Small only (licence)
        self.assertEqual(g["ckpt"]["inputs"]["ckpt_name"], comfy.SD15)
        self.assertEqual(g["pos0"]["inputs"]["text"], "warm sunset light")
        ks = g["ks"]["inputs"]
        self.assertEqual((ks["latent_image"], ks["denoise"], ks["seed"]), (["init", 0], 0.9, 5))
        self.assertEqual((ks["positive"], ks["negative"]), (["icc", 0], ["icc", 1]))
        self.assertEqual(g["lit"]["inputs"]["blend_mode"], "multiply")

    def test_iclight_graph_no_direction(self):
        g = comfy.graph_iclight("a.png", None, "neon", 1, 512, 640)
        Graphs.links_ok(self, g)
        self.assertNotIn("depth", g)
        self.assertEqual((g["ks"]["inputs"]["latent_image"], g["ks"]["inputs"]["denoise"]), (["icc", 2], 1.0))

    def test_light_gradient_and_size(self):
        g = comfy.light_gradient(8, 4, "left")
        self.assertGreater(g[0, 0, 0], g[0, -1, 0])
        g = comfy.light_gradient(8, 4, "bottom")
        self.assertGreater(g[-1, 0, 0], g[0, 0, 0])
        w, h = comfy.relight_size(1920, 1080)
        self.assertEqual((w % 64, h % 64), (0, 0))
        self.assertGreater(w, h)


class Fallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.src = self.d / "p.png"
        self.a = picture(self.src)
        env = mock.patch.dict(os.environ, {"PHW_RUNG_MAX": "9"})  # these tests set the rung themselves
        env.start()
        self.addCleanup(env.stop)

    def down(self):
        return mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused"))

    def test_cutout_falls_back_when_down(self):
        with self.down():
            r = run("cutout", self.src, "--model", "birefnet", "-o", self.d / "c.png")
        self.assertLess(r["rung"], 3)
        self.assertTrue(any(n.startswith("fell back: ComfyUI server unreachable") for n in r["notes"]), r["notes"])
        self.assertEqual(r["steps"][0]["params"]["model"], "birefnet.safetensors")

    def test_fill_falls_back_and_keeps_outside(self):
        with self.down():
            r = run("fill", self.src, "--model", "lama", "--rect", "30,20,36,40", "-o", self.d / "f.png")
        self.assertLess(r["rung"], 3)
        self.assertTrue(any(n.startswith("fell back:") for n in r["notes"]))
        b = np.asarray(Image.open(r["output"]).convert("RGB"))
        out = np.ones(b.shape[:2], bool)
        out[18:62, 28:68] = False   # rect plus the remove/fill grow margin
        self.assertTrue((b[out] == self.a[out]).all())

    def test_rung_max_hides_rung3(self):
        with mock.patch.dict(os.environ, {"PHW_RUNG_MAX": "2"}):
            r = run("fill", self.src, "--method", "lama", "--rect", "30,20,36,40", "-o", self.d / "f.png")
        self.assertTrue(any("PHW_RUNG_MAX=2 hides rung 3" in n for n in r["notes"]))

    def test_missing_node_falls_back(self):
        def fake(path, data=None, headers=None, timeout=30):
            return b"{}" if path.startswith("/object_info/") else b'{"system": {}}'
        with mock.patch.object(comfy, "_req", side_effect=fake):
            r = run("cutout", self.src, "--method", "birefnet", "-o", self.d / "c.png")
        self.assertTrue(any("node LoadBackgroundRemovalModel is not installed" in n for n in r["notes"]), r["notes"])

    def test_select_text_refuses_when_down(self):
        with self.down(), self.assertRaises(SystemExit) as cm:
            run("select", self.src, "--text", "red box", "-o", self.d / "m.png")
        self.assertIn("needs rung 3", str(cm.exception))

    def test_mocked_lama_pastes_back(self):
        """A model that changes every pixel must still leave the outside bit-identical."""
        def fake_fill(rgb, hole, seed):
            return np.zeros_like(rgb), {"model": "big-lama.pt", "seed": seed, "server": "mock", "seconds": 0,
                                        "queued_ahead": 0}
        with mock.patch.object(comfy, "lama_fill", side_effect=fake_fill):
            r = run("fill", self.src, "--model", "lama", "--rect", "30,20,36,40", "--seed", "5", "-o", self.d / "f.png")
        self.assertEqual(r["rung"], 3)
        self.assertEqual(r["steps"][0]["params"]["model"], "big-lama.pt")
        self.assertEqual(r["steps"][0]["params"]["seed"], 5)
        b = np.asarray(Image.open(r["output"]).convert("RGB"))
        self.assertTrue((b[20:60, 30:66] == 0).all())
        out = np.ones(b.shape[:2], bool)
        out[20:60, 30:66] = False
        self.assertTrue((b[out] == self.a[out]).all())

    def test_qwen_edit_falls_back_when_down(self):
        with self.down():
            r = run("fill", self.src, "--model", "qwen-edit", "--prompt", "grass", "--rect", "30,20,36,40",
                    "-o", self.d / "f.png")
        self.assertLess(r["rung"], 3)
        self.assertTrue(any(n.startswith("fell back: ComfyUI server unreachable") for n in r["notes"]), r["notes"])
        self.assertEqual(r["steps"][0]["params"]["prompt"], "grass")
        b = np.asarray(Image.open(r["output"]).convert("RGB"))
        out = np.ones(b.shape[:2], bool)
        out[20:60, 30:66] = False
        self.assertTrue((b[out] == self.a[out]).all())

    def test_qwen_edit_refuses_busy_queue(self):
        def fake(path, data=None, headers=None, timeout=30):
            if path == "/queue":
                return b'{"queue_running": [[0, "h3"]], "queue_pending": []}'
            raise AssertionError(f"queued or called {path} on a busy server")
        with mock.patch.object(comfy, "check"), mock.patch.object(comfy, "upload", return_value="x.png"), \
                mock.patch.object(comfy, "_req", side_effect=fake):
            r = run("fill", self.src, "--model", "qwen-edit", "--prompt", "grass", "--rect", "30,20,36,40",
                    "-o", self.d / "f.png")
        self.assertLess(r["rung"], 3)
        self.assertTrue(any("ComfyUI is busy (1 jobs ahead" in n for n in r["notes"]), r["notes"])

    def test_qwen_edit_needs_prompt(self):
        with self.assertRaises(SystemExit) as cm:
            run("fill", self.src, "--model", "qwen-edit", "--rect", "30,20,36,40", "-o", self.d / "f.png")
        self.assertIn("--prompt", str(cm.exception))

    def test_mocked_qwen_edit_composites_through_mask(self):
        """The model repaints the whole frame at another size; only mask pixels may change."""
        seen = {}

        def fake_post(path, data=None, headers=None, timeout=30):
            if path == "/queue":
                return b'{"queue_running": [], "queue_pending": []}'
            if path == "/prompt":
                seen["graph"] = json.loads(data)["prompt"]
                return b'{"prompt_id": "p1"}'
            if path.startswith("/history/"):
                return b'{"p1": {"status": {"completed": true}, "outputs": {"out": {"images": [{"filename": "o.png"}]}}}}'
            raise AssertionError(path)

        def fake_fetch(outs, node="out"):
            return np.zeros((40, 48, 3), np.float32)      # half size, all black
        with mock.patch.object(comfy, "check"), mock.patch.object(comfy, "upload", side_effect=lambda d, n: n), \
                mock.patch.object(comfy, "_req", side_effect=fake_post), \
                mock.patch.object(comfy, "fetch_first", side_effect=fake_fetch):
            r = run("fill", self.src, "--model", "qwen-edit", "--prompt", "a green plant", "--rect", "30,20,36,40",
                    "--seed", "4", "-o", self.d / "f.png")
        self.assertEqual(r["rung"], 3)
        prm = r["steps"][0]["params"]
        self.assertEqual((prm["model"], prm["seed"], prm["prompt"]), (comfy.QWEN_EDIT, 4, "a green plant"))
        self.assertTrue(prm["invented_detail"])
        self.assertEqual(seen["graph"]["pos0"]["inputs"]["prompt"], "a green plant")
        b = np.asarray(Image.open(r["output"]).convert("RGB"))
        self.assertTrue((b[20:60, 30:66] == 0).all())
        out = np.ones(b.shape[:2], bool)
        out[20:60, 30:66] = False
        self.assertTrue((b[out] == self.a[out]).all())

    def test_upscale_seedvr2_falls_back_when_down(self):
        with self.down():
            r = run("upscale", self.src, "--method", "seedvr2", "--scale", 2, "-o", self.d / "u.png")
        self.assertEqual(r["rung"], 1)
        self.assertTrue(any(n.startswith("fell back: ComfyUI server unreachable") for n in r["notes"]), r["notes"])
        self.assertFalse(r["steps"][0]["params"]["invented_detail"])
        self.assertEqual(Image.open(r["output"]).size, (192, 160))

    def test_mocked_seedvr2_flags_invented(self):
        def fake(rgb, w, h, seed, size="3b"):
            return np.full((h, w, 3), 0.5, np.float32), {"model": comfy.SEEDVR2[size], "seed": seed,
                                                          "server": "mock", "seconds": 0, "queued_ahead": 0}
        with mock.patch.object(comfy, "seedvr2_upscale", side_effect=fake):
            r = run("upscale", self.src, "--model", "seedvr2", "--size", "7b", "--seed", 9, "--scale", 2,
                    "-o", self.d / "u.png")
        self.assertEqual(r["rung"], 3)
        prm = r["steps"][0]["params"]
        self.assertTrue(prm["invented_detail"])
        self.assertEqual((prm["model"], prm["seed"]), (comfy.SEEDVR2["7b"], 9))
        self.assertTrue(any("invents detail" in n for n in r["notes"]))
        self.assertEqual(Image.open(r["output"]).size, (192, 160))

    def test_relight_needs_prompt(self):
        with self.assertRaises(SystemExit) as cm:
            run("relight", self.src, "--light", "left", "-o", self.d / "r.png")
        self.assertIn("--prompt", str(cm.exception))

    def test_relight_refused_when_rung_hidden(self):
        def boom(*a, **k):
            raise AssertionError("contacted the server with rung 3 hidden")
        with mock.patch.dict(os.environ, {"PHW_RUNG_MAX": "1"}), mock.patch("urllib.request.urlopen", side_effect=boom):
            r = run("relight", self.src, "--prompt", "sunset", "--light", "left", "-o", self.d / "r.png")
        self.assertEqual(r["rung"], 1)
        self.assertTrue(any("hides rung 3" in n for n in r["notes"]), r["notes"])
        self.assertFalse(r["steps"][0]["params"]["invented_detail"])

    def test_relight_falls_back_when_down(self):
        with self.down():
            r = run("relight", self.src, "--model", "iclight", "--prompt", "sunset", "--light", "right",
                    "-o", self.d / "r.png")
        self.assertEqual(r["rung"], 1)
        self.assertTrue(any(n.startswith("fell back: ComfyUI server unreachable") for n in r["notes"]), r["notes"])
        b = np.asarray(Image.open(r["output"]).convert("RGB")).astype(int)
        self.assertGreater(b[:, -10:].mean(), b[:, :10].mean())   # lit from the right
        self.assertEqual(b.shape[:2], self.a.shape[:2])

    def test_relight_refuses_busy_queue(self):
        def fake(path, data=None, headers=None, timeout=30):
            if path == "/queue":
                return b'{"queue_running": [[0, "h3"]], "queue_pending": []}'
            raise AssertionError(f"queued or called {path} on a busy server")
        with mock.patch.object(comfy, "check"), mock.patch.object(comfy, "upload", return_value="x.png"), \
                mock.patch.object(comfy, "_req", side_effect=fake):
            r = run("relight", self.src, "--prompt", "sunset", "-o", self.d / "r.png")
        self.assertEqual(r["rung"], 1)
        self.assertTrue(any("ComfyUI is busy (1 jobs ahead" in n for n in r["notes"]), r["notes"])

    def test_mocked_relight_resizes_back_and_flags(self):
        seen = {}

        def fake_post(path, data=None, headers=None, timeout=30):
            if path == "/queue":
                return b'{"queue_running": [], "queue_pending": []}'
            if path == "/prompt":
                seen["graph"] = json.loads(data)["prompt"]
                return b'{"prompt_id": "p1"}'
            if path.startswith("/history/"):
                return b'{"p1": {"status": {"completed": true}, "outputs": {"out": {"images": [{"filename": "o.png"}]}}}}'
            raise AssertionError(path)
        with mock.patch.object(comfy, "check"), mock.patch.object(comfy, "upload", side_effect=lambda d, n: n), \
                mock.patch.object(comfy, "_req", side_effect=fake_post), \
                mock.patch.object(comfy, "fetch_first", return_value=np.full((512, 576, 3), 0.25, np.float32)):
            r = run("relight", self.src, "--model", "iclight", "--prompt", "blue rim light", "--light", "top",
                    "--seed", 7, "-o", self.d / "r.png")
        self.assertEqual(r["rung"], 3)
        prm = r["steps"][0]["params"]
        self.assertEqual((prm["model"], prm["seed"], prm["depth"]),
                         (f"{comfy.ICLIGHT} on {comfy.SD15}", 7, comfy.DAV2_SMALL))
        self.assertTrue(prm["invented_detail"])
        self.assertEqual(seen["graph"]["pos0"]["inputs"]["text"], "blue rim light")
        self.assertTrue(seen["graph"]["limg"]["inputs"]["image"].endswith("_light.png"))
        self.assertEqual(Image.open(r["output"]).size, (96, 80))


@unittest.skipUnless(server_up(), LIVE_SKIP or "")
class Live(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"PHW_COMFY_WAIT": LIVE_WAIT, "PHW_COMFY_MAX_AHEAD": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.src = self.d / "p.png"
        self.a = picture(self.src, 2)

    def test_live_cutout(self):
        r = run("cutout", self.src, "--model", "birefnet", "-o", self.d / "c.png", "--recipe", self.d / "r.json")
        self.assertEqual(r["rung"], 3, r["notes"])
        b = np.asarray(Image.open(r["output"]))
        self.assertTrue((b[..., :3] == self.a).all())  # colour untouched, alpha only
        rec = json.loads((self.d / "r.json").read_text())
        self.assertEqual(rec["steps"][0]["params"]["model"], "birefnet.safetensors")

    def test_live_lama(self):
        r = run("remove", self.src, "--model", "lama", "--rect", "60,40,72,80", "--seed", "3", "-o", self.d / "f.png")
        self.assertEqual(r["rung"], 3, r["notes"])
        b = np.asarray(Image.open(r["output"]).convert("RGB"))
        out = np.ones(b.shape[:2], bool)
        out[36:124, 56:136] = False
        self.assertTrue((b[out] == self.a[out]).all())
        # the red box is gone: the region is now close to the light ground
        self.assertGreater(b[50:110, 70:120].mean(), 190)

    def test_live_select_text(self):
        r = run("select", self.src, "--text", "red square", "-o", self.d / "m.png")
        self.assertEqual(r["rung"], 3)
        m = np.asarray(Image.open(r["output"])) > 127
        box = np.zeros(m.shape, bool)
        box[40:120, 60:132] = True
        iou = (m & box).sum() / max(1, (m | box).sum())
        self.assertGreater(iou, 0.7, iou)


if __name__ == "__main__":
    unittest.main()
