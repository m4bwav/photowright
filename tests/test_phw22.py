"""Proof bars for batch 22 (phw 0.25.0): decompose, an image split into RGBA layers.

- graph: the Qwen-Image-Layered graph follows the core blueprint (layered latent with N layers,
  ReferenceLatent on both prompts, frame 0 cut away, layered VAE, AuraFlow shift 1, 20 steps cfg 2.5).
- working size: about 640x640 pixels, sides multiples of 16.
- rung 1: the k-means colour split gives N hard-alpha layers that flatten back to the source exactly
  and writes a PSD that reads back with N layers.
- fallback: PHW_RUNG_MAX=1 never contacts the server; a busy queue is refused, not queued.
- mocked rung 3: layers come back at the source size, in order, with the invented-detail flag.
"""
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import phw  # noqa: E402
from phw import comfy, layered  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def scene(w=120, h=90):
    im = Image.new("RGB", (w, h), (40, 120, 200))
    d = ImageDraw.Draw(im)
    d.ellipse((10, 20, 60, 70), fill=(220, 40, 30))
    d.rectangle((70, 10, 110, 50), fill=(250, 220, 40))
    return im


class TestDecompose(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw22-"))
        self.src = self.d / "scene.png"
        scene().save(self.src)

    def test_graph_follows_blueprint(self):
        g = comfy.graph_qwen_layered("a.png", 3, 5, "a red ball")
        self.assertEqual(g["lat"]["class_type"], "EmptyQwenImageLayeredLatentImage")
        self.assertEqual(g["lat"]["inputs"]["layers"], 3)
        self.assertEqual(g["lat"]["inputs"]["width"], ["size", 0])
        self.assertEqual(g["unet"]["inputs"]["unet_name"], comfy.QWEN_LAYERED)
        self.assertEqual(g["vae"]["inputs"]["vae_name"], comfy.QWEN_LAYERED_VAE)
        for k in ("pos", "neg"):
            self.assertEqual(g[k]["class_type"], "ReferenceLatent")
            self.assertEqual(g[k]["inputs"]["latent"], ["enc", 0])
        self.assertEqual(g["pos0"]["inputs"]["text"], "a red ball")
        self.assertEqual((g["cut"]["inputs"]["dim"], g["cut"]["inputs"]["index"]), ("t", 1))
        self.assertEqual(g["batch"]["class_type"], "LatentCutToBatch")
        self.assertEqual(g["dec"]["inputs"]["samples"], ["batch", 0])
        self.assertEqual(g["ms"]["inputs"]["shift"], 1.0)
        ks = g["ks"]["inputs"]
        self.assertEqual((ks["steps"], ks["cfg"], ks["seed"], ks["sampler_name"]), (20, 2.5, 5, "euler"))
        for n in g.values():   # every link points at a node in the graph
            for v in n["inputs"].values():
                if isinstance(v, list):
                    self.assertIn(v[0], g)

    def test_layered_size(self):
        self.assertEqual(comfy.layered_size(640, 640), (640, 640))
        w, h = comfy.layered_size(1920, 1080)
        self.assertEqual((w % 16, h % 16), (0, 0))
        self.assertLess(abs(w * h - 640 * 640) / (640 * 640), 0.05)

    def test_kmeans_exact_and_psd(self):
        with mock.patch.dict(os.environ, {"PHW_RUNG_MAX": "1"}):
            r = run("decompose", self.src, "--method", "colour", "--layers", 3, "-o", self.d / "s.psd")
        self.assertEqual((r["rung"], r["layers"]), (1, 3))
        self.assertEqual(r["recomposite_psnr"], float("inf"))
        self.assertAlmostEqual(sum(r["alpha_coverage"]), 1.0, places=3)
        doc = layered.read_layered(r["output"], phw.core.Used())
        self.assertEqual(len(doc.layers), 3)

    def test_png_folder(self):
        with mock.patch.dict(os.environ, {"PHW_RUNG_MAX": "1"}):
            r = run("decompose", self.src, "--method", "colour", "--layers", 2, "-o", self.d / "layers")
        self.assertTrue(Path(r["recipe"]).exists())
        self.assertEqual(len(list((self.d / "layers").glob("*.png"))), 2)

    def test_rung_hidden_falls_back_without_server(self):
        def boom(*a, **k):
            raise AssertionError("contacted the server with rung 3 hidden")
        with mock.patch.dict(os.environ, {"PHW_RUNG_MAX": "1"}), mock.patch("urllib.request.urlopen", side_effect=boom):
            r = run("decompose", self.src, "--layers", 3, "-o", self.d / "s.ora")
        self.assertEqual(r["rung"], 1)
        self.assertTrue(any("hides rung 3" in n for n in r["notes"]), r["notes"])
        self.assertFalse(r["params"]["invented_detail"])

    def test_busy_queue_refused(self):
        def fake(path, data=None, headers=None, timeout=30):
            if path == "/queue":
                return b'{"queue_running": [[0, "x"]], "queue_pending": []}'
            raise AssertionError(f"queued or called {path} on a busy server")
        with mock.patch.object(comfy, "check"), mock.patch.object(comfy, "upload", return_value="x.png"), \
                mock.patch.object(comfy, "_req", side_effect=fake):
            r = run("decompose", self.src, "--layers", 2, "-o", self.d / "s.psd")
        self.assertEqual(r["rung"], 1)
        self.assertTrue(any("ComfyUI is busy (1 jobs ahead" in n for n in r["notes"]), r["notes"])

    def test_mocked_qwen_layers(self):
        bg = np.concatenate([np.full((640, 640, 3), 0.5, np.float32), np.ones((640, 640, 1), np.float32)], 2)
        fg = np.zeros((640, 640, 4), np.float32)
        fg[100:300, 100:300] = [1, 0, 0, 1]
        seen = {}

        def fake_run(graph, wait=None, max_ahead=None):
            seen["graph"], seen["max_ahead"] = graph, max_ahead
            return {"out": {}}, 0, 1.0
        with mock.patch.object(comfy, "check"), mock.patch.object(comfy, "upload", side_effect=lambda d, n: n), \
                mock.patch.object(comfy, "run_graph", side_effect=fake_run), \
                mock.patch.object(comfy, "fetch_all", return_value=[bg, fg]):
            r = run("decompose", self.src, "--model", "qwen-layered", "--layers", 2, "--seed", 4, "-o", self.d / "q.psd")
        self.assertEqual(r["rung"], 3)
        self.assertEqual(seen["max_ahead"], 0)
        self.assertEqual(seen["graph"]["lat"]["inputs"]["layers"], 2)
        self.assertTrue(r["params"]["invented_detail"])
        self.assertEqual(r["layers"], 2)
        self.assertEqual(r["alpha_coverage"][0], 1.0)
        doc = layered.read_layered(r["output"], phw.core.Used())
        self.assertEqual((doc.width, doc.height), (120, 90))


if __name__ == "__main__":
    unittest.main()
