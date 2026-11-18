"""Proof bars for `bridge` (phw 0.8.0): hand a file to a free editor and prove the hand-off.

- GIMP 3 (when installed): the editor's flatten of phw's ORA and PSD matches phw's own flatten
  (premultiplied colour mean < 1/255, alpha max <= 2) in both blend spaces.
- Krita absent: status "absent", the command is still written.
- Photopea and Photoshop: a script is written, never run; status "emitted", rung 4.
- --rung-max 1 refuses every target; the source is never written over.
"""
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import phw  # noqa: E402
from phw import bridge  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


class Bridge(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw-bridge-"))
        a = np.zeros((32, 48, 3), np.uint8)
        a[..., 0] = np.arange(48) * 5
        a[..., 1] = 120
        Image.fromarray(a).save(self.d / "base.png")
        b = np.zeros((32, 48, 4), np.uint8)
        b[8:24, 12:36] = (0, 0, 255, 160)
        Image.fromarray(b).save(self.d / "top.png")
        rec = {"version": 1, "kind": "layers", "canvas": {"width": 48, "height": 32},
               "layers": [{"name": "base", "file": "base.png"},
                          {"name": "top", "file": "top.png", "mode": "multiply", "opacity": 0.8}]}
        (self.d / "rec.json").write_text(json.dumps(rec), encoding="utf-8")
        self.ora = run("save", self.d / "rec.json", "-o", self.d / "doc.ora")["output"]
        self.psd = run("save", self.d / "rec.json", "-o", self.d / "doc.psd")["output"]

    def tearDown(self):
        os.environ.pop("PHW_RUNG_MAX", None)

    def test_closed_editors_emit_only(self):
        if phw.rung_max() < 4:
            self.skipTest("PHW_RUNG_MAX hides rung 4: refusal is covered by the rung-max test")
        for to, ext in (("photopea", ".js"), ("photoshop", ".jsx")):
            r = run("bridge", self.ora, "--to", to)
            self.assertEqual((r["status"], r["rung"]), ("emitted", 4))
            self.assertTrue(r["script"].endswith(ext) and Path(r["script"]).exists())
            self.assertFalse(Path(r["output"]).exists())
        jsx = Path(run("bridge", self.ora, "--to", "photoshop", "--emit", self.d / "ps")["script"]).read_text()
        self.assertIn(Path(self.ora).resolve().as_posix(), jsx)

    def test_krita_absent_writes_command(self):
        with mock.patch.object(bridge, "krita_exe", return_value=None):
            r = run("bridge", self.ora, "--to", "krita", "--run")
        self.assertEqual(r["status"], "absent")
        self.assertIn("--export-filename", (Path(r["emit"]) / "command.txt").read_text())

    def test_gimp_absent_still_emits(self):
        with mock.patch("phw.core.gimp_console", return_value=None):
            r = run("bridge", self.psd, "--to", "gimp", "--run")
        self.assertEqual(r["status"], "absent")
        self.assertIn("RGB_PERCEPTUAL", Path(r["script"]).read_text())

    def test_rung_max_refuses(self):
        for to in bridge.TARGETS:
            r = run("--rung-max", "1", "bridge", self.ora, "--to", to)
            self.assertEqual(r["status"], "refused", to)

    def test_never_overwrites_source(self):
        before = (self.d / "base.png").read_bytes()
        r = run("bridge", self.d / "base.png", "--to", "photoshop", "-o", self.d / "base.png")
        self.assertNotEqual(Path(r["output"]).name, "base.png")
        self.assertEqual((self.d / "base.png").read_bytes(), before)

    def test_gimp_round_trip_matches_own_flatten(self):
        if os.environ.get("PHW_SKIP_GIMP") or not phw.gimp_console():
            self.skipTest("GIMP 3 not found or PHW_SKIP_GIMP set")
        for src in (self.ora, self.psd):
            for space in ("gamma", "linear"):
                r = run("bridge", src, "--to", "gimp", "--run", "--space", space, "--emit", self.d / f"g-{Path(src).suffix[1:]}-{space}")
                self.assertEqual(r["status"], "ran", r.get("error"))
                self.assertTrue(r["compare"]["pass"], (src, space, r["compare"]))


if __name__ == "__main__":
    unittest.main()
