"""Proof bars for phw 0.27.0: `camraw --match REF` fits the Camera Raw sliders to a reference (after PREEN,
arXiv:2610.36896: match a look by choosing editor presets, so the result stays editable).

Half-image fixture: the left half of tests/fixtures/dark-photo.jpg graded with hidden camraw sliders is the
reference, the right half is the source, and the truth is the right half graded with the same hidden sliders.
- Mean CIE76 dE to the truth over three hidden grades is at most Reinhard's (`tone --match`) + 0.5.
- Replaying the printed sliders with a plain `camraw` call gives the same image within 1/255, and so does
  `run` on the recipe.
- --amount 0.5 halves the colour sliders (temp, tint, vibrance, saturation) and leaves the tone sliders alone.
- An unrelated reference (a flat logo against a photo) raises the different-scene warning; the same-scene halves
  do not.
"""
import io
import json
import shlex
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import phw  # noqa: E402,F401  (registers every op)
from phw import core, rawio  # noqa: E402
from phw.masks import rgb_to_lab  # noqa: E402

PHOTO = HERE / "fixtures" / "dark-photo.jpg"
LOGO = HERE / "fixtures" / "logo.png"
HIDDEN = [
    {"temp": 35, "tint": -15, "exposure": 0.4, "contrast": 20, "whites": 0, "blacks": -20, "vibrance": 30, "saturation": 0},
    {"temp": -40, "tint": 20, "exposure": -0.3, "contrast": -15, "whites": 25, "blacks": 0, "vibrance": 0, "saturation": -30},
    {"temp": 15, "tint": 10, "exposure": 0.6, "contrast": 35, "whites": -20, "blacks": 15, "vibrance": -25, "saturation": 20},
]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        core.cli(["--json"] + argv)
    return json.loads(out.getvalue()), err.getvalue()


def px(path):
    return np.asarray(Image.open(path).convert("RGB"), np.float64) / 255


def de76(a, b):
    return float(np.mean(np.linalg.norm(rgb_to_lab(a) - rgb_to_lab(b), axis=-1)))


def slider_args(g):
    return [x for n, v in g.items() if v for x in (f"--{n}", str(v))]


class CamrawMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        im = Image.open(PHOTO).convert("RGB")
        w, h = im.size
        cls.left, cls.right = d / "left.png", d / "right.png"
        im.crop((0, 0, w // 2, h)).save(cls.left)
        im.crop((w // 2, 0, w, h)).save(cls.right)
        cls.trials = []
        for i, g in enumerate(HIDDEN):
            ref, truth = d / f"ref{i}.png", d / f"truth{i}.png"
            run(["camraw", str(cls.left), *slider_args(g), "-o", str(ref)])
            run(["camraw", str(cls.right), *slider_args(g), "-o", str(truth)])
            out, rh, rec = d / f"fit{i}.png", d / f"reinhard{i}.png", d / f"fit{i}.json"
            r, err = run(["camraw", str(cls.right), "--match", str(ref), "-o", str(out), "--recipe", str(rec)])
            run(["tone", str(cls.right), "--match", str(ref), "-o", str(rh)])
            cls.trials.append({"ref": ref, "truth": truth, "out": out, "reinhard": rh, "recipe": rec, "r": r, "err": err})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_fit_is_as_close_as_reinhard(self):
        fit = [de76(px(t["out"]), px(t["truth"])) for t in self.trials]
        rh = [de76(px(t["reinhard"]), px(t["truth"])) for t in self.trials]
        none = [de76(px(self.right), px(t["truth"])) for t in self.trials]
        self.assertLessEqual(np.mean(fit), np.mean(rh) + 0.5, f"fit {fit} reinhard {rh}")
        self.assertLess(np.mean(fit), np.mean(none), f"fit {fit} no edit {none}")

    def test_replay_of_printed_sliders(self):
        d = Path(self.tmp.name)
        for i, t in enumerate(self.trials):
            r = t["r"]
            self.assertIn("match", r)
            self.assertTrue(r["replay"].startswith("phw.py camraw "))
            argv = [x.strip('"') for x in shlex.split(r["replay"], posix=False)[1:]]
            rep = d / f"replay{i}.png"
            run([*argv, "-o", str(rep)])
            self.assertLessEqual(np.abs(px(rep) - px(t["out"])).max(), 1 / 255 + 1e-9)
            rec = json.loads(t["recipe"].read_text(encoding="utf-8"))
            meta = rec["steps"][0]["params"]["camraw"]
            self.assertEqual(meta["sliders"], {k: v for k, v in r["match"]["sliders"].items() if v})
            ran = d / f"run{i}.png"
            run(["run", str(t["recipe"]), "-o", str(ran)])
            self.assertLessEqual(np.abs(px(ran) - px(t["out"])).max(), 1 / 255 + 1e-9)

    def test_same_scene_has_no_warning(self):
        for t in self.trials:
            self.assertEqual(t["r"]["match"]["warnings"], [], t["r"]["match"])
            self.assertNotIn("different scene", t["err"])

    def test_amount_scales_colour_sliders_only(self):
        d = Path(self.tmp.name)
        full = self.trials[0]["r"]["match"]["sliders"]
        r, _ = run(["camraw", str(self.right), "--match", str(self.trials[0]["ref"]), "--amount", "0.5",
                    "-o", str(d / "half.png")])
        half = r["match"]["sliders"]
        for n in full:
            if n in rawio.CHROMA:
                self.assertAlmostEqual(half[n], round(full[n] * 0.5, 1), delta=0.11, msg=n)
            else:
                self.assertEqual(half[n], full[n], n)

    def test_different_scene_warns(self):
        d = Path(self.tmp.name)
        r, err = run(["camraw", str(PHOTO), "--match", str(LOGO), "-o", str(d / "logo-look.png")])
        self.assertTrue(r["match"]["warnings"], r["match"])
        self.assertIn("different scene", err)

    def test_slider_names_checked(self):
        with self.assertRaises(SystemExit):
            run(["camraw", str(self.right), "--match", str(self.left), "--sliders", "temp,clarity"])


if __name__ == "__main__":
    unittest.main()
