"""Proof bars for batch 13 (phw 0.14.0).

- Variables: one output per CSV row named from a column; each equals `phw layers` on the hand-edited
  recipe bit-exactly (text and image swapped); the template is unchanged; a second run writes nothing;
  a row with a missing image is reported and the other rows finish.
- Tilt-shift: band pixels bit-identical to the source; beyond the ramp == the full Gaussian within 1/255.
- Field blur: at each pin == the Gaussian of that pin's sigma within 1/255 (sigma 0 pin == source).
- Fibers: seeded (same seed bit-exact, other seed differs); values between fg and bg; vertical
  gradient energy < 1/4 of the horizontal.
- De-Interlace: the kept field bit-exact; a combed smooth image restored to within 3/255 (interp)
  of the progressive original.
- NTSC: every output pixel inside Y + C <= 1.1 + 1/255, Y - C >= -0.2 - 1/255; safe pixels unchanged.
- Liquify twirl/pucker/bloat: strength 0 identity; flat unchanged; outside the radius bit-exact;
  bloat grows a centred disc, pucker shrinks it; twirl turns a bar off its row.
- Masks keep outside pixels; `phw run` replays the recipe bit-exactly.
"""
import csv
import json
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
from phw import core, gallery  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch13(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw13-"))
        self.rng = np.random.default_rng(13)
        self.o = 0
        self.noise = self.rng.integers(0, 256, (32, 40, 3), dtype=np.uint8)
        self.np_ = self.save("noise.png", self.noise)

    def out(self):
        self.o += 1
        return self.d / f"o{self.o}.png"

    def save(self, name, a):
        Image.fromarray(np.asarray(np.clip(a, 0, 255), np.uint8)).save(self.d / name)
        return self.d / name

    def flat(self, v=(120, 90, 60), n=24):
        return self.save("flat.png", np.tile(np.array(v, np.uint8), (n, n, 1)))

    def gauss(self, a, s):
        return np.stack([core.gaussian_blur(a[..., i] / 255.0, s) for i in range(3)], 2) * 255

    # ------------------------------------------------------------ variables
    def test_variables(self):
        self.save("red.png", np.tile(np.array([255, 0, 0], np.uint8), (12, 12, 1)))
        self.save("blue.png", np.tile(np.array([0, 0, 255], np.uint8), (12, 12, 1)))
        tpl = {"canvas": {"width": 64, "height": 40, "background": [1, 1, 1]},
               "layers": [{"type": "image", "name": "photo", "file": "red.png", "x": 4, "y": 4},
                          {"type": "text", "name": "title", "text": "A", "x": 24, "y": 8, "size": 20}]}
        tp = self.d / "tpl.json"
        tp.write_bytes(json.dumps(tpl).encode())
        before = tp.read_bytes()
        cp = self.d / "data.csv"
        with open(cp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerows([["id", "title", "photo"], ["one", "Hi", "red.png"], ["two", "Yo", "blue.png"],
                         ["bad", "No", "missing.png"], ["three", "Ok", "blue.png"]])
        od = self.d / "vars"
        r = run("variables", tp, cp, od, "--name", "id")
        self.assertEqual(sorted(Path(p).name for p in r["written"]), ["one.png", "three.png", "two.png"])
        self.assertEqual(len(r["errors"]), 1)
        self.assertEqual(r["errors"][0]["line"], 4)
        for nm, title, ph in (("one", "Hi", "red.png"), ("two", "Yo", "blue.png")):
            t2 = json.loads(json.dumps(tpl))
            t2["layers"][0]["file"], t2["layers"][1]["text"] = ph, title
            p2 = self.d / f"direct-{nm}.json"
            p2.write_bytes(json.dumps(t2).encode())
            ref = arr(run("layers", p2, "-o", self.out())["output"])
            self.assertTrue((arr(od / f"{nm}.png") == ref).all(), nm)
        a1, a2 = arr(od / "one.png"), arr(od / "two.png")
        self.assertEqual(list(a1[8, 8, :3]), [255, 0, 0])
        self.assertEqual(list(a2[8, 8, :3]), [0, 0, 255])
        self.assertFalse((a1[:, 20:] == a2[:, 20:]).all())  # text differs
        self.assertEqual(tp.read_bytes(), before)
        snap = {p.name: p.read_bytes() for p in od.iterdir()}
        r2 = run("variables", tp, cp, od, "--name", "id")
        self.assertEqual(r2["written"], [])
        self.assertEqual(len(r2["skipped"]), 3)
        self.assertEqual({p.name: p.read_bytes() for p in od.iterdir()}, snap)

    # ------------------------------------------------------------ blur gallery
    def test_tilt(self):
        r = run("blurgallery", self.np_, "-o", self.out(), "--tilt", "12,19", "--ramp", 4, "--sigma", 3)
        a = arr(r["output"])
        self.assertTrue((a[12:20] == self.noise[12:20]).all())
        g = self.gauss(self.noise.astype(float), 3)
        far = np.r_[0:8, 24:32]
        self.assertLessEqual(np.abs(a[far] - g[far]).max(), 1.0)

    def test_field(self):
        r = run("blurgallery", self.np_, "-o", self.out(), "--field", "5,5,0 34,26,2.5")
        a = arr(r["output"]).astype(float)
        self.assertTrue((a[5, 5] == self.noise[5, 5]).all())
        g = self.gauss(self.noise.astype(float), 2.5)
        self.assertLessEqual(np.abs(a[26, 34] - g[26, 34]).max(), 1.0)

    # ------------------------------------------------------------ fibers
    def test_fibers(self):
        f = self.flat(n=48)
        a = arr(run("fibers", f, "-o", self.out(), "--seed", 3, "--fg", "#204060", "--bg", "#e0c0a0")["output"])
        b = arr(run("fibers", f, "-o", self.out(), "--seed", 3, "--fg", "#204060", "--bg", "#e0c0a0")["output"])
        c = arr(run("fibers", f, "-o", self.out(), "--seed", 4, "--fg", "#204060", "--bg", "#e0c0a0")["output"])
        self.assertTrue((a == b).all())
        self.assertFalse((a == c).all())
        self.assertTrue((a[..., 0] >= 0x20).all() and (a[..., 0] <= 0xe0).all())
        self.assertTrue((a[..., 2] >= 0x60).all() and (a[..., 2] <= 0xa0).all())
        L = a[..., 0].astype(float)
        ev, eh = (np.diff(L, axis=0) ** 2).mean(), (np.diff(L, axis=1) ** 2).mean()
        self.assertLess(ev, eh / 4)

    # ------------------------------------------------------------ de-interlace
    def test_deinterlace(self):
        y, x = np.mgrid[0:32, 0:40]
        prog = np.stack([128 + 80 * np.sin(x / 6.0 + y / 9.0), 100 + 50 * np.cos(y / 7.0), 60 + x * 2.0], 2)
        prog = np.round(prog).astype(np.uint8)
        shifted = np.round(np.stack([128 + 80 * np.sin((x + 6) / 6.0 + y / 9.0), 100 + 50 * np.cos(y / 7.0),
                                     60 + (x + 6) * 2.0], 2).clip(0, 255)).astype(np.uint8)
        comb = prog.copy()
        comb[1::2] = shifted[1::2]
        cp = self.save("comb.png", comb)
        a = arr(run("deinterlace", cp, "-o", self.out(), "--field", "odd", "--fill", "interp")["output"])
        self.assertTrue((a[0::2] == comb[0::2]).all())
        self.assertLessEqual(np.abs(a - prog.astype(int))[:-1].max(), 3)
        self.assertGreater(np.abs(comb.astype(int) - prog).max(), 20)
        b = arr(run("deinterlace", cp, "-o", self.out(), "--field", "even", "--fill", "dup")["output"])
        self.assertTrue((b[1::2] == comb[1::2]).all() and (b[2::2] == comb[1:-1:2]).all() and (b[0] == comb[1]).all())

    # ------------------------------------------------------------ NTSC
    def test_ntsc(self):
        im = self.noise.copy()
        im[0, 0], im[0, 1], im[0, 2] = (255, 255, 0), (255, 0, 0), (0, 255, 255)
        a = arr(run("ntsc", self.save("hot.png", im), "-o", self.out())["output"]) / 255.0
        yiq = a @ gallery.YIQ.T
        Y, C = yiq[..., 0], np.hypot(yiq[..., 1], yiq[..., 2])
        self.assertLessEqual((Y + C).max(), 1.1 + 1 / 255)
        self.assertGreaterEqual((Y - C).min(), -0.2 - 1 / 255)
        s = im / 255.0 @ gallery.YIQ.T
        Ys, Cs = s[..., 0], np.hypot(s[..., 1], s[..., 2])
        safe = (Ys + Cs <= 1.1) & (Ys - Cs >= -0.2)
        self.assertGreater(safe.sum(), 100)
        self.assertLessEqual(np.abs(a * 255 - im)[safe].max(), 1.0)
        self.assertFalse(safe[0, 0] or safe[0, 1])

    # ------------------------------------------------------------ liquify brushes
    def test_liquify_brushes(self):
        a = arr(run("liquify", self.np_, "-o", self.out(), "--mode", "twirl", "--stroke", "20,16", "--strength", 0)["output"])
        self.assertTrue((a == self.noise).all())
        f = self.flat()
        for m in ("twirl", "pucker", "bloat"):
            self.assertTrue((arr(run("liquify", f, "-o", self.out(), "--mode", m, "--stroke", "12,12", "--radius", 8)["output"])
                             == arr(f)).all(), m)
        b = arr(run("liquify", self.np_, "-o", self.out(), "--mode", "twirl", "--stroke", "20,16", "--radius", 8)["output"])
        yy, xx = np.mgrid[0:32, 0:40]
        out = (xx - 20) ** 2 + (yy - 16) ** 2 >= 64
        self.assertTrue((b[out] == self.noise[out]).all())
        self.assertFalse((b == self.noise).all())
        disc = np.zeros((41, 41, 3))
        disc[(np.mgrid[0:41, 0:41] - 20).__pow__(2).sum(0) <= 25] = 255
        dp = self.save("disc.png", disc)
        area = lambda p: (arr(p)[..., 0] > 127).sum()  # noqa: E731
        a0 = area(dp)
        bl = run("liquify", dp, "-o", self.out(), "--mode", "bloat", "--stroke", "20,20", "--radius", 14, "--strength", 0.6)["output"]
        pu = run("liquify", dp, "-o", self.out(), "--mode", "pucker", "--stroke", "20,20", "--radius", 14, "--strength", 0.6)["output"]
        self.assertGreater(area(bl), a0 * 1.3)
        self.assertLess(area(pu), a0 * 0.8)
        bar = np.zeros((41, 41, 3))
        bar[19:22, 4:37] = 255
        tw = arr(run("liquify", self.save("bar.png", bar), "-o", self.out(), "--mode", "twirl", "--stroke", "20,20",
                     "--radius", 16, "--strength", 0.5)["output"])
        self.assertGreater((tw[:19, :, 0] > 127).sum() + (tw[22:, :, 0] > 127).sum(), 20)

    # ------------------------------------------------------------ mask + replay
    def test_mask_and_replay(self):
        m = np.zeros((32, 40), np.uint8)
        m[:, 20:] = 255
        Image.fromarray(m).save(self.d / "m.png")
        rec = self.d / "r.json"
        r = run("blurgallery", self.np_, "-o", self.out(), "--tilt", "14,17", "--mask", self.d / "m.png", "--recipe", rec)
        a = arr(r["output"])
        self.assertTrue((a[:, :19] == self.noise[:, :19]).all())
        self.assertFalse((a[:, 21:] == self.noise[:, 21:]).all())
        self.assertTrue((arr(run("run", rec, "-o", self.out())["output"]) == a).all())
        for args in (("fibers", "--seed", 2), ("deinterlace",), ("ntsc",),
                     ("liquify", "--mode", "bloat", "--stroke", "20,16"), ("blurgallery", "--field", "3,3,1 30,20,3")):
            rec2 = self.d / f"r-{args[0]}-{self.o}.json"
            r2 = run(args[0], self.np_, "-o", self.out(), *args[1:], "--recipe", rec2)
            self.assertTrue((arr(run("run", rec2, "-o", self.out())["output"]) == arr(r2["output"])).all(), args[0])


if __name__ == "__main__":
    unittest.main()
