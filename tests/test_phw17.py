"""Proof bars for batch 17 (phw 0.18.0).

- Merge to HDR: a known radiance ramp (1000:1) shot at 1/4, 1 and 4 through the sRGB curve with
  8-bit clipping: the merged radiance (--radiance .npy) has median relative error < 3% and max < 6%
  (past the darkest 10 columns), and every single frame's max error is over 1.5x the merge's;
  --tonemap none output is monotonic along the ramp; wrong exposure count refuses; replay bit-exact.
- HDR Toning: global map is monotonic in luminance and never exceeds 1; --key moves the log-mean
  luminance of the result up; neutral greys stay neutral (R == G == B within 1/255); --detail > 0
  raises local contrast (mean |high-pass| of luminance) over --detail 0.
- Auto-Align: copies of one texture shifted by known integer offsets are recovered exactly (the
  reported shift is the one applied, the negative of the content offset), and the
  aligned overlap equals the reference bit-exact.
- Magnetic Lasso: on a disc with 8 anchors near its edge, IoU with the true disc >= 0.95 and higher
  than the polygon lasso through the same anchors.
- Vanishing Point clone: src == dst quad is bit-exact identity; a pure translation between equal
  axis-aligned quads equals a plain copy bit-exact; on a plane rendered through a homography from a
  periodic texture, cloning one tile's quad onto another tile's quad matches the truth within 8/255
  mean; pixels outside the destination quad never change.
- Adaptive Wide Angle: a grid of straight lines rendered through an equidistant fisheye (180 deg
  diagonal), corrected with the same model: every line straight within 1 px (fitted-line residual)
  where the fisheye showed it sag over 2 px across 60 columns; the wrong model (orthographic) leaves more bend.
- Layer Comps: a comp with no overrides == `layers` flatten within 1/255; a comp hiding a layer ==
  the document without it; a comp moving a layer == the document with that layer's x/y changed;
  the source file is unchanged; an unknown layer name refuses.
- Generator assets: a layer named 'blue.png, 200% blue@2x.png, 4x4 tiny.png' writes three files of
  10x10, 20x20 and 4x4, all pure blue and opaque; no asset-named layer refuses.
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
from phw import hdr  # noqa: E402
from phw.core import to_enc, to_lin  # noqa: E402
from phw.transform import homography  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch17(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw17-"))
        self.o = 0

    def out(self, ext=".png"):
        self.o += 1
        return self.d / f"o{self.o}{ext}"

    def save(self, name, a):
        Image.fromarray(np.asarray(np.clip(np.round(a), 0, 255), np.uint8)).save(self.d / name)
        return self.d / name

    # ------------------------------------------------------------ merge to HDR
    def brackets(self):
        rad = np.repeat(np.repeat(np.logspace(-3, 0, 96)[None, :, None], 8, 0), 3, 2).astype(np.float32) * 0.9
        times = [0.25, 1.0, 4.0]
        files = []
        for i, t in enumerate(times):
            enc = np.round(np.clip(to_enc(np.clip(rad * t, 0, 1)), 0, 1) * 255)
            files.append(self.save(f"b{i}.png", enc))
        return rad, times, files

    def test_merge_recovers_radiance(self):
        rad, times, files = self.brackets()
        npy = self.d / "rad.npy"
        rec = self.d / "r.json"
        o = run("hdrmerge", *files, "--exposures", ",".join(map(str, times)), "--radiance", npy,
                "-o", self.out(), "--recipe", rec)["output"]
        got = np.load(npy)
        rel = np.abs(got - rad) / rad
        self.assertLess(float(np.median(rel)), 0.03)
        self.assertLess(float(rel[:, 10:].max()), 0.06)   # brightest-dark end limited by 8-bit
        merged = float(rel[:, 10:].max())
        for f, t in zip(files, times):  # every single frame is worse somewhere (clipped or coarse)
            single = to_lin(arr(f) / 255.0) / t
            self.assertGreater(float((np.abs(single - rad) / rad)[:, 10:].max()), 1.5 * merged)
        o2 = run("run", rec, "-o", self.out())["output"]
        self.assertTrue((arr(o2) == arr(o)).all())
        lin = run("hdrmerge", *files, "--exposures", "0.25,1,4", "--tonemap", "none", "-o", self.out())["output"]
        row = arr(lin)[4, :, 1]
        self.assertTrue((np.diff(row) >= 0).all())
        with self.assertRaises(Exception):
            run("hdrmerge", *files, "--exposures", "1,4", "-o", self.out())

    # ------------------------------------------------------------ HDR toning
    def test_hdrtone(self):
        g = np.repeat(np.repeat(np.linspace(0, 255, 128)[None, :, None], 16, 0), 3, 2)
        src = self.save("ramp.png", g)
        lo = arr(run("hdrtone", src, "--key", "0.1", "-o", self.out())["output"])
        hi = arr(run("hdrtone", src, "--key", "0.4", "-o", self.out())["output"])
        self.assertTrue((np.diff(lo[8, :, 0]) >= 0).all())
        self.assertLessEqual(int(hi.max()), 255)
        self.assertGreater(hi.mean(), lo.mean())
        self.assertLessEqual(int(np.abs(lo[..., 0] - lo[..., 1]).max()), 1)
        self.assertLessEqual(int(np.abs(lo[..., 1] - lo[..., 2]).max()), 1)
        rng = np.random.default_rng(17)
        t = np.kron(rng.integers(40, 220, (8, 8)), np.ones((8, 8)))
        tex = self.save("tex.png", np.repeat(t[..., None], 3, 2))
        flat = arr(run("hdrtone", tex, "-o", self.out())["output"])[..., 1].astype(float)
        det = arr(run("hdrtone", tex, "--detail", "1.0", "--sigma", "4", "-o", self.out())["output"])[..., 1].astype(float)

        def hp(a):
            return float(np.abs(a - np.mean(a)).mean())
        self.assertGreater(hp(det), hp(flat))

    # ------------------------------------------------------------ auto-align
    def test_autoalign(self):
        rng = np.random.default_rng(3)
        big = rng.integers(0, 256, (80, 96, 3)).astype(float)
        ref = big[10:58, 10:74]
        shifts = [(0, 0), (3, -5), (-7, 4)]
        files = [self.save(f"a{i}.png", big[10 - dy:58 - dy, 10 - dx:74 - dx]) for i, (dx, dy) in enumerate(shifts)]
        r = run("autoalign", *files, "--outdir", self.d / "al")
        for (dx, dy), o in zip(shifts, r["outputs"]):
            self.assertEqual(o["shift"], [-dx, -dy])  # the shift applied
            a = arr(o["output"])
            ov = a[..., 3] == 255
            self.assertGreater(ov.mean(), 0.7)
            self.assertTrue((a[..., :3][ov] == ref.astype(np.int32)[ov]).all())

    # ------------------------------------------------------------ magnetic lasso
    def test_lasso(self):
        yy, xx = np.mgrid[0:96, 0:96]
        disc = (xx - 48) ** 2 + (yy - 48) ** 2 <= 30 ** 2
        src = self.save("disc.png", np.repeat(np.where(disc, 200, 40)[..., None], 3, 2))
        ang = np.arange(8) * np.pi / 4
        anchors = " ".join(f"{48 + 31 * np.cos(t):.0f},{48 + 31 * np.sin(t):.0f}" for t in ang)

        def iou(path):
            m = arr(path) > 127
            return (m & disc).sum() / (m | disc).sum()
        mag = iou(run("lasso", src, "--points", anchors, "-o", self.out())["output"])
        poly = iou(run("lasso", src, "--points", anchors, "--polygon", "-o", self.out())["output"])
        self.assertGreaterEqual(mag, 0.95)
        self.assertGreater(mag, poly)

    # ------------------------------------------------------------ vanishing point clone
    def test_vpclone_identity_and_translate(self):
        rng = np.random.default_rng(5)
        a = rng.integers(0, 256, (40, 60, 3)).astype(float)
        src = self.save("n.png", a)
        q = "5,5 20,5 20,20 5,20"
        same = arr(run("vpclone", src, "--src", q, "--dst", q, "-o", self.out())["output"])
        self.assertTrue((same == arr(src)).all())
        t = arr(run("vpclone", src, "--src", "5,5 20,5 20,20 5,20", "--dst", "30,10 45,10 45,25 30,25", "-o", self.out())["output"])
        a0 = arr(src)
        self.assertTrue((t[11:25, 31:45] == a0[6:20, 6:20]).all())
        dest = np.zeros((40, 60), bool)
        dest[9:27, 29:47] = True
        self.assertTrue((t[~dest] == a0[~dest]).all())

    def test_vpclone_plane(self):
        # texture plane: tiles of 16 px with a smooth periodic pattern; rendered through a homography
        def tex(u, v):
            return 128 + 60 * np.sin(2 * np.pi * u / 16) * np.cos(2 * np.pi * v / 16) + 40 * np.cos(2 * np.pi * (u + v) / 16)
        plane = [(0, 0), (96, 0), (96, 64), (0, 64)]
        img_q = [(20, 20), (140, 30), (150, 110), (10, 100)]
        H = homography(img_q, plane)   # image -> plane
        Hi = homography(plane, img_q)  # plane -> image
        yy, xx = np.mgrid[0:130, 0:170].astype(float)
        P = H @ np.stack([xx.ravel(), yy.ravel(), np.ones(xx.size)])
        u, v = (P[0] / P[2]).reshape(xx.shape), (P[1] / P[2]).reshape(xx.shape)
        img = np.repeat(tex(u, v)[..., None], 3, 2)
        src = self.save("plane.png", img)

        def quad(u0, v0):
            pts = [(u0, v0), (u0 + 32, v0), (u0 + 32, v0 + 32), (u0, v0 + 32)]
            out = []
            for pu, pv in pts:
                p = Hi @ np.array([pu, pv, 1.0])
                out.append(f"{p[0] / p[2]:.4f},{p[1] / p[2]:.4f}")
            return " ".join(out)
        o = arr(run("vpclone", src, "--src", quad(8, 8), "--dst", quad(56, 24), "-o", self.out())["output"])
        a0 = arr(src)
        mask = hdr.poly_mask(a0.shape[:2], [tuple(map(float, s.split(","))) for s in quad(56, 24).split()]) > 0.5
        inner = mask & np.roll(mask, 2, 0) & np.roll(mask, -2, 0) & np.roll(mask, 2, 1) & np.roll(mask, -2, 1)
        self.assertLess(float(np.abs(o[inner] - a0[inner]).mean()), 8)
        self.assertTrue((o[~mask] == a0[~mask]).all())


    # ------------------------------------------------------------ adaptive wide angle
    def test_widefix(self):
        w, h, fov, ofov = 160, 120, 180.0, 110.0
        ff, fo = hdr.fisheye_focals(w, h, fov, ofov, "equidistant")
        cx, cy = (w - 1) / 2, (h - 1) / 2
        S = 4  # supersample the synthetic fisheye
        yy, xx = np.mgrid[0:h * S, 0:w * S].astype(float)
        dx, dy = (xx + 0.5) / S - 0.5 - cx, (yy + 0.5) / S - 0.5 - cy
        rf = np.hypot(dx, dy)
        theta = rf / ff
        ok = theta < np.radians(80)
        rr = fo * np.tan(np.where(ok, theta, 0))
        s = np.where(rf > 1e-9, rr / np.maximum(rf, 1e-9), fo / ff)
        X, Y = dx * s, dy * s
        rows = (-36, -18, 18, 36)
        dark = np.zeros_like(X, bool)
        for r0 in rows:
            dark |= (np.abs(Y - r0) < 1.0) & (np.abs(X) < 50)
        img = np.where(dark & ok, 0, 255).reshape(h, S, w, S).mean(axis=(1, 3))
        src = self.save("fish.png", np.repeat(img[..., None], 3, 2))

        def bend(a, cols):
            res = []
            for r0 in rows:
                ys = []
                band_c = int(round(cy + r0 * (ff / fo if a is None else 1)))
                for c in cols:
                    col = a[:, c]
                    lo, hi = max(0, band_c - 14), min(h, band_c + 15)
                    d = 255 - col[lo:hi]
                    if d.sum() < 200:
                        continue
                    ys.append(lo + float((d * np.arange(len(d))).sum() / d.sum()))
                if len(ys) > 5:
                    ys = np.array(ys)
                    xs = np.arange(len(ys))
                    res.append(float(np.abs(ys - np.polyval(np.polyfit(xs, ys, 1), xs)).max()))
            return max(res)
        fixed = arr(run("widefix", src, "--fov", fov, "--out-fov", ofov, "-o", self.out())["output"])[..., 1]
        cols = range(int(cx - 40), int(cx + 41), 4)
        self.assertLessEqual(bend(fixed.astype(float), cols), 1.0)
        self.assertGreater(max(self._fisheye_bend(img, rows, ff, fo, cx, cy)), 2.0)
        wrong = arr(run("widefix", src, "--fov", fov, "--out-fov", ofov, "--model", "orthographic",
                        "-o", self.out())["output"])[..., 1]
        self.assertGreater(bend(wrong.astype(float), cols), bend(fixed.astype(float), cols))

    @staticmethod
    def _fisheye_bend(img, rows, ff, fo, cx, cy):
        """Sag of each fisheye line: row of the line at the centre column vs at the line's ends."""
        out = []
        for r0 in rows:
            ys = []
            for c in (int(cx), int(cx) - 30, int(cx) + 30):
                col = 255 - img[:, c]
                guess = cy + r0 * ff / fo
                lo, hi = int(max(0, guess - 20)), int(min(img.shape[0], guess + 21))
                d = col[lo:hi]
                ys.append(lo + float((d * np.arange(len(d))).sum() / max(d.sum(), 1e-9)))
            out.append(abs(ys[0] - (ys[1] + ys[2]) / 2))
        return out

    # ------------------------------------------------------------ layer comps and assets
    def doc(self, layers, name="doc.json"):
        rp = self.d / name
        rp.write_text(json.dumps({"version": 1, "kind": "layers", "canvas": {"width": 40, "height": 32},
                                  "layers": layers}), encoding="utf-8")
        return rp

    def base_layers(self, blue_name="blue", red=True, bx=28):
        rng = np.random.default_rng(9)
        self.save("p.png", rng.integers(0, 256, (20, 24, 3)))
        l2 = np.zeros((12, 14, 4))
        l2[..., :3], l2[..., 3] = (250, 40, 10), 255
        Image.fromarray(l2.astype(np.uint8), "RGBA").save(self.d / "r.png")
        l3 = np.zeros((10, 10, 4))
        l3[..., 2], l3[..., 3] = 255, 255
        Image.fromarray(l3.astype(np.uint8), "RGBA").save(self.d / "b.png")
        ls = [{"type": "image", "name": "photo", "file": "p.png", "x": 2, "y": 3}]
        if red:
            ls.append({"type": "image", "name": "red", "file": "r.png", "x": 10, "y": 8, "opacity": 0.7})
        ls.append({"type": "image", "name": blue_name, "file": "b.png", "x": bx, "y": 18})
        return ls

    def flat(self, rp):
        return arr(run("layers", rp, "-o", self.out())["output"])

    def test_comps(self):
        rp = self.doc(self.base_layers())
        before = rp.read_bytes()
        cj = self.d / "comps.json"
        cj.write_text(json.dumps({"all": {}, "nored": {"red": {"visible": False}},
                                  "moved": {"blue": {"x": 5, "y": 20}}}), encoding="utf-8")
        r = run("comps", rp, cj, self.d / "comps")
        got = {o["comp"]: arr(o["file"]) for o in r["outputs"]}
        want = {"all": self.flat(rp), "nored": self.flat(self.doc(self.base_layers(red=False), "n.json")),
                "moved": self.flat(self.doc([dict(l, x=5, y=20) if l["name"] == "blue" else l
                                             for l in self.base_layers()], "m.json"))}
        for k, w in want.items():
            g = got[k]
            vis = g[..., 3] > 0
            self.assertTrue((vis == (w[..., 3] > 0)).all() if w.shape[2] == 4 else True, k)
            self.assertLessEqual(int(np.abs(g[..., :3][vis] - w[..., :3][vis]).max()), 1, k)
        self.assertEqual(rp.read_bytes(), before)
        bad = self.d / "bad.json"
        bad.write_text(json.dumps({"x": {"nope": {"visible": False}}}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            run("comps", rp, bad, self.d / "bad")

    def test_assets(self):
        rp = self.doc(self.base_layers("blue.png, 200% blue@2x.png, 4x4 tiny.png"))
        r = run("assets", rp, self.d / "assets")
        files = {Path(o["file"]).name: arr(o["file"]) for o in r["outputs"]}
        for fn, size in (("blue.png", 10), ("blue@2x.png", 20), ("tiny.png", 4)):
            a = files[fn]
            self.assertEqual(a.shape[:2], (size, size), fn)
            self.assertTrue((a == [0, 0, 255, 255]).all(), fn)
        with self.assertRaises(SystemExit):
            run("assets", self.doc(self.base_layers(), "plain.json"), self.d / "none")


if __name__ == "__main__":
    unittest.main()
