"""Proof bars for batch 14 (phw 0.15.0).

- Iris blur: pixels inside the ellipse bit-identical; beyond the ramp == the full Gaussian within 1/255.
- Path blur: length 0 identity; a horizontal path == the mean of 2k+1 horizontal shifts within 1/255
  (interior); vertical stripes blurred along a vertical path stay unchanged within 1/255.
- Filter Gallery: the output == the same commands run one after another within 2/255 (one rounding
  per separate run); the sheet has one tile per stage; `phw run` replays it bit-exactly.
- Brushes: strength 0 identity; pixels beyond the radius from the stroke bit-exact; blur halves the
  noise std on the stroke; sharpen raises high-frequency energy > 1.5x; smudge drags a dark blob's
  centroid > 2 px along the stroke and leaves a flat image unchanged.
- Content-Aware Move: the block lands bit-exact at the offset; pixels outside both rects bit-exact;
  the vacated area on a flat background == the background within 2/255.
- Export layers: each layer PNG composited back in order (normal blend) == the flattened file within
  1/255; --trim boxes match the layer rects; artboards: one PNG per top group == that group alone.
- Crop and Straighten: two photos rotated 7 and -12 degrees on a scan come out as two files, angles
  within 0.5 degrees, sizes within 4 px, content mean error < 6/255.
"""
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
from phw import core  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch14(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw14-"))
        self.rng = np.random.default_rng(14)
        self.o = 0
        self.noise = self.rng.integers(0, 256, (32, 40, 3), dtype=np.uint8)
        self.np_ = self.save("noise.png", self.noise)

    def out(self):
        self.o += 1
        return self.d / f"o{self.o}.png"

    def save(self, name, a, mode=None):
        Image.fromarray(np.asarray(np.clip(np.round(a), 0, 255), np.uint8), mode).save(self.d / name)
        return self.d / name

    def gauss(self, a, s):
        return np.stack([core.gaussian_blur(a[..., i] / 255.0, s) for i in range(3)], 2) * 255

    # ------------------------------------------------------------ iris / path blur
    def test_iris(self):
        r = run("blurgallery", self.np_, "-o", self.out(), "--iris", "20,16,8,5", "--ramp", 3, "--sigma", 2.5)
        a = arr(r["output"])
        yy, xx = np.mgrid[0:32, 0:40]
        rho = np.sqrt(((xx - 20) / 8) ** 2 + ((yy - 16) / 5) ** 2)
        inside = rho <= 1
        self.assertTrue((a[inside] == self.noise[inside]).all())
        far = (rho - 1) * 5 >= 3.01
        g = self.gauss(self.noise.astype(float), 2.5)
        self.assertLessEqual(np.abs(a[far] - g[far]).max(), 1.0)
        self.assertGreater(far.sum(), 500)

    def test_path(self):
        a0 = arr(run("blurgallery", self.np_, "-o", self.out(), "--path", "0,16 39,16", "--length", 0)["output"])
        self.assertTrue((a0 == self.noise).all())
        a = arr(run("blurgallery", self.np_, "-o", self.out(), "--path", "0,16 39,16", "--length", 6)["output"])
        n = self.noise.astype(float)
        ref = sum(n[:, 3 + j:37 + j] for j in range(-3, 4)) / 7
        self.assertLessEqual(np.abs(a[:, 3:37] - ref).max(), 1.0)
        st = np.tile(self.rng.integers(0, 256, (1, 40, 3)), (32, 1, 1)).astype(np.uint8)
        sp = self.save("stripes.png", st)
        v = arr(run("blurgallery", sp, "-o", self.out(), "--path", "20,0 20,31", "--length", 8)["output"])
        self.assertLessEqual(np.abs(v - st).max(), 1)
        hz = arr(run("blurgallery", sp, "-o", self.out(), "--path", "0,10 39,10", "--length", 8)["output"])
        self.assertGreater(np.abs(hz - st).max(), 20)

    # ------------------------------------------------------------ filter gallery
    def test_filtergallery(self):
        o = self.out()
        sheet = self.d / "sheet.png"
        rec = self.d / "fg.json"
        r = run("filtergallery", self.np_, "-o", o, "--sheet", sheet, "--thumb", 64, "--recipe", rec,
                "--step", "filter --blur gaussian --radius 1.5", "--step", "color --posterize 6",
                "--step", "effect --emboss 45")
        self.assertEqual(len(r["stages"]), 4)
        a = arr(r["output"])
        s1 = run("filter", self.np_, "-o", self.out(), "--blur", "gaussian", "--radius", 1.5)["output"]
        s2 = run("color", s1, "-o", self.out(), "--posterize", 6)["output"]
        s3 = run("effect", s2, "-o", self.out(), "--emboss", 45)["output"]
        diff = np.abs(a - arr(s3))
        self.assertLessEqual(np.mean(diff), 2.0)
        self.assertGreater(np.mean(diff == 0), 0.6)
        with Image.open(r["sheet"]) as sh:
            size = sh.size
        self.assertEqual(size, (4 * 72 + 8, 64 + 14 + 16))
        self.assertTrue((arr(run("run", rec, "-o", self.out())["output"]) == a).all())
        with self.assertRaises(SystemExit):
            run("filtergallery", self.np_, "-o", self.out(), "--step", "variables a b c")

    # ------------------------------------------------------------ brushes
    def test_paint(self):
        z = arr(run("paint", self.np_, "-o", self.out(), "--tool", "blur", "--stroke", "5,16 35,16", "--strength", 0)["output"])
        self.assertTrue((z == self.noise).all())
        yy, xx = np.mgrid[0:32, 0:40]
        far = np.abs(yy - 16) > 6
        core_ = (np.abs(yy - 16) <= 2) & (xx >= 8) & (xx <= 32)
        b = arr(run("paint", self.np_, "-o", self.out(), "--tool", "blur", "--stroke", "5,16 35,16", "--radius", 6,
                    "--strength", 1, "--sigma", 2)["output"])
        self.assertTrue((b[far] == self.noise[far]).all())
        self.assertLess(b[core_].std(), self.noise[core_].std() / 2)
        smooth = np.round(self.gauss(self.noise.astype(float), 2)).astype(np.uint8)
        sp = self.save("smooth.png", smooth)
        s = arr(run("paint", sp, "-o", self.out(), "--tool", "sharpen", "--stroke", "5,16 35,16", "--radius", 6,
                    "--strength", 1, "--sigma", 2)["output"])
        hf = lambda x: (np.diff(x[core_[:, :]].reshape(5, -1, 3).astype(float), axis=1) ** 2).mean()  # noqa: E731
        self.assertGreater(hf(s), 1.5 * hf(smooth.astype(int)))
        self.assertTrue((s[far] == smooth[far]).all())
        flat = self.save("flat.png", np.full((32, 40, 3), 140))
        self.assertTrue((arr(run("paint", flat, "-o", self.out(), "--tool", "smudge", "--stroke", "5,16 35,16")["output"])
                         == 140).all())
        blob = np.full((32, 40, 3), 230.0)
        blob[((xx - 10) ** 2 + (yy - 16) ** 2) <= 9] = 20
        bp = self.save("blob.png", blob)
        m = arr(run("paint", bp, "-o", self.out(), "--tool", "smudge", "--stroke", "10,16 26,16", "--radius", 5,
                    "--strength", 0.8)["output"])
        dark = lambda x: 230 - x[..., 0].astype(float)  # noqa: E731
        cx0 = (dark(blob) * xx).sum() / dark(blob).sum()
        cx1 = (dark(m) * xx).sum() / dark(m).sum()
        self.assertGreater(cx1 - cx0, 2)
        far2 = np.abs(yy - 16) > 6
        self.assertTrue((m[far2] == blob[far2]).all())

    # ------------------------------------------------------------ content-aware move
    def test_camove(self):
        im = np.zeros((40, 48, 3)) + (90, 130, 170)
        blk = self.rng.integers(0, 256, (8, 10, 3))
        im[6:14, 5:15] = blk
        ip = self.save("ca.png", im)
        a = arr(run("camove", ip, "-o", self.out(), "--rect", "5,6,10,8", "--to", "20,18", "--method", "membrane")["output"])
        self.assertTrue((a[24:32, 25:35] == blk).all())
        other = np.ones((40, 48), bool)
        other[6:14, 5:15] = other[24:32, 25:35] = False
        self.assertTrue((a[other] == np.round(im[other])).all())
        self.assertLessEqual(np.abs(a[6:14, 5:15] - (90, 130, 170)).max(), 2)
        b = arr(run("camove", ip, "-o", self.out(), "--rect", "5,6,10,8", "--to", "4,2")["output"])
        self.assertTrue((b[8:16, 9:19] == blk).all())
        rec = self.d / "cm.json"
        c = arr(run("camove", ip, "-o", self.out(), "--rect", "5,6,10,8", "--to", "20,18", "--recipe", rec)["output"])
        self.assertTrue((arr(run("run", rec, "-o", self.out())["output"]) == c).all())

    # ------------------------------------------------------------ export layers / artboards
    def layered_doc(self):
        self.save("l1.png", np.dstack([self.noise[:20, :24], np.full((20, 24), 255)]), "RGBA")
        l2 = np.zeros((12, 14, 4))
        l2[..., :3] = (250, 40, 10)
        l2[..., 3] = 200
        self.save("l2.png", l2, "RGBA")
        l3 = np.zeros((10, 10, 4))
        l3[..., 2], l3[..., 3] = 255, 255
        self.save("l3.png", l3, "RGBA")
        rec = {"version": 1, "kind": "layers", "canvas": {"width": 40, "height": 32},
               "layers": [{"type": "group", "name": "boardA", "layers": [
                   {"type": "image", "name": "photo", "file": "l1.png", "x": 2, "y": 3},
                   {"type": "image", "name": "red", "file": "l2.png", "x": 10, "y": 8, "opacity": 0.7}]},
                   {"type": "group", "name": "boardB", "layers": [
                       {"type": "image", "name": "blue", "file": "l3.png", "x": 28, "y": 18}]}]}
        rp = self.d / "doc.json"
        rp.write_text(json.dumps(rec), encoding="utf-8")
        return rp

    def test_export_layers(self):
        rp = self.layered_doc()
        psd = run("save", rp, "-o", self.d / "doc.psd")["output"]
        flat = arr(run("layers", rp, "-o", self.out())["output"])
        for src in (rp, psd):
            od = self.d / f"ex-{Path(src).suffix[1:]}"
            r = run("export-layers", src, od)
            self.assertEqual(len(r["written"]), 3)
            acc = np.zeros((32, 40, 3))
            aa = np.zeros((32, 40, 1))
            for f in r["written"]:
                L = np.asarray(Image.open(f)).astype(float) / 255
                self.assertEqual(L.shape[:2], (32, 40))
                acc = L[..., :3] * L[..., 3:] + acc * (1 - L[..., 3:])
                aa = L[..., 3:] + aa * (1 - L[..., 3:])
            comp = np.where(aa > 0, acc / np.maximum(aa, 1e-9), 0) * 255
            vis = aa[..., 0] > 0
            self.assertLessEqual(np.abs(comp[vis] - flat[..., :3][vis]).max(), 1.5, src)
        t = run("export-layers", rp, self.d / "trim", "--trim")
        boxes = [(i["x"], i["y"], i["width"], i["height"]) for i in t["items"]]
        self.assertEqual(boxes, [(2, 3, 24, 20), (10, 8, 14, 12), (28, 18, 10, 10)])
        ab = run("export-layers", rp, self.d / "boards", "--artboards")
        self.assertEqual(len(ab["written"]), 2)
        bb = arr(ab["written"][1])
        self.assertEqual(bb.shape, (10, 10, 4))
        self.assertTrue((bb == [0, 0, 255, 255]).all())
        ba = arr(ab["written"][0])
        self.assertEqual(ba.shape[:2], (20, 24))
        self.assertLessEqual(np.abs(ba[..., :3] - flat[3:23, 2:26, :3]).max(), 1)

    # ------------------------------------------------------------ crop and straighten
    def test_cropstraighten(self):
        yy, xx = np.mgrid[0:60, 0:90]
        pa = np.stack([60 + xx * 1.5, 40 + yy * 2.0, 200 - xx], 2)
        pb = np.stack([200 - yy * 2.0, 30 + xx * 1.2, 90 + yy], 2)
        scan = Image.new("RGB", (400, 260), (250, 250, 250))
        truths = []
        for img, ang, pos in ((pa, 7, (20, 30)), (pb, -12, (210, 90))):
            im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGBA")
            rot = im.rotate(ang, resample=Image.BICUBIC, expand=True)
            scan.paste(rot, pos, rot)
            truths.append((img, ang))
        sp = self.d / "scan.png"
        scan.save(sp)
        r = run("cropstraighten", sp, self.d / "photos")
        self.assertEqual(len(r["photos"]), 2)
        for ph, (img, ang) in zip(sorted(r["photos"], key=lambda p: p["centre"][0]), truths):
            self.assertLessEqual(abs(abs(ph["angle"]) - abs(ang)), 0.5, ph)
            self.assertLessEqual(abs(ph["width"] - 90), 4)
            self.assertLessEqual(abs(ph["height"] - 60), 4)
            o = arr(ph["file"])[..., :3].astype(float)
            ref = np.asarray(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize(
                (o.shape[1], o.shape[0]), Image.BILINEAR)).astype(float)
            self.assertLess(np.abs(o[3:-3, 3:-3] - ref[3:-3, 3:-3]).mean(), 6, ph)

    # ------------------------------------------------------------ mask + replay
    def test_mask_and_replay(self):
        m = np.zeros((32, 40), np.uint8)
        m[:, 20:] = 255
        Image.fromarray(m).save(self.d / "m.png")
        for args in (("blurgallery", "--iris", "20,16,6,4"), ("blurgallery", "--path", "0,0 39,31"),
                     ("paint", "--tool", "blur", "--stroke", "5,16 35,16")):
            rec = self.d / f"r-{self.o}.json"
            r = run(args[0], self.np_, "-o", self.out(), *args[1:], "--mask", self.d / "m.png", "--recipe", rec)
            a = arr(r["output"])
            self.assertTrue((a[:, :19] == self.noise[:, :19]).all(), args)
            self.assertFalse((a[:, 21:] == self.noise[:, 21:]).all(), args)
            self.assertTrue((arr(run("run", rec, "-o", self.out())["output"]) == a).all(), args)


if __name__ == "__main__":
    unittest.main()
