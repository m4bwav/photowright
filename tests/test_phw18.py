"""Proof bars for batch 18 (phw 0.19.0): the two partial rows of 0.18.0 finished.

- Auto-Align rotation/scale/perspective: a smooth random texture warped through a known similarity
  (7 deg, scale 1.06, shift) and a known homography (mild keystone) is recovered by
  `autoalign --model similarity|homography`: the reported matrix moves the four inner corners within
  0.5 px of the truth, and the aligned overlap matches the reference within 3/255 mean; the plain
  translation model on the same pair is over 3x worse.
- Merge to HDR camera response: brackets shot through a non-sRGB curve (z = x^(1/3)); with
  --response recover the radiance (up to one global scale) has median relative error < 5% and is
  over 2x better than the sRGB assumption; the saved curve is monotonic and reused through a JSON
  file gives the same radiance; replay of the recipe is bit-exact.
- Content Credentials: a JPEG with a C2PA APP11 JUMBF segment is reported present with its claim
  generator by `inspect`; a plain JPEG is not; `convert` output carries none.
- Lens profile: a lensfun XML (poly3 k1 -0.06 at 18 mm, 0.02 at 55 mm; pa vignetting) matched by words;
  a grid rendered through the barrel distortion is corrected to within 4/255 mean of the truth (raw > 3x
  worse); 36.5 mm interpolates k1 = -0.02; vignetting brightens corners, centre within 1/255; replay
  bit-exact; an unknown lens refuses.
- Layered TIFF (tests/test_phw2.py): `save x.tif` writes Photoshop tag 37724; the own reader gets the
  same layer tree back, GIMP 3 lists the layers, `--flat` writes no tag.
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
from phw.transform import _blur5  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.float64)


class Batch18(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw18-"))

    def save(self, name, a):
        Image.fromarray(np.asarray(np.clip(np.round(a), 0, 255), np.uint8)).save(self.d / name)
        return self.d / name

    def texture(self, h=128, w=160):
        rng = np.random.default_rng(18)
        t = rng.random((h, w)).astype(np.float32)
        for _ in range(3):
            t = _blur5(t)
        t = (t - t.min()) / (t.max() - t.min())
        return np.repeat((t * 255)[..., None], 3, 2)

    def check(self, H_true, model):
        big = self.texture()
        ref = self.save("ref.png", big)
        mov_a = hdr.warp_h(big.astype(np.float32), np.linalg.inv(H_true), fill=128)[0]
        mov = self.save("mov.png", mov_a)
        # mov(x) = big(Hinv x) so big(x) = mov(H x): the matrix to find is H_true
        r = run("autoalign", ref, mov, "--outdir", self.d / model, "--model", model)
        H = np.array(r["outputs"][1]["matrix"])
        h, w = big.shape[:2]
        corners = np.array([[30, 30, 1], [w - 30, 30, 1], [w - 30, h - 30, 1], [30, h - 30, 1]], float).T

        def proj(M):
            q = M @ corners
            return q[:2] / q[2]
        self.assertLess(float(np.abs(proj(H) - proj(H_true)).max()), 0.5)
        a = arr(r["outputs"][1]["output"])
        ov = a[..., 3] == 255
        ov[:8], ov[-8:], ov[:, :8], ov[:, -8:] = False, False, False, False
        err = float(np.abs(a[..., 0] - big[..., 0])[ov].mean())
        self.assertLess(err, 3.0)
        t = run("autoalign", ref, mov, "--outdir", self.d / "tr")
        b = arr(t["outputs"][1]["output"])
        ovb = (b[..., 3] == 255) & ov
        self.assertGreater(float(np.abs(b[..., 0] - big[..., 0])[ovb].mean()), 3 * err)

    def test_similarity(self):
        th, s = np.deg2rad(7), 1.06
        c = np.array([[1, 0, 80], [0, 1, 64], [0, 0, 1.0]])
        R = np.array([[s * np.cos(th), -s * np.sin(th), 0], [s * np.sin(th), s * np.cos(th), 0], [0, 0, 1]])
        H = c @ R @ np.linalg.inv(c) @ np.array([[1, 0, 3.5], [0, 1, -2.0], [0, 0, 1]])
        self.check(H, "similarity")

    def test_homography(self):
        H = np.array([[1.02, 0.03, 2.0], [-0.02, 0.99, 1.5], [0.0002, -0.0001, 1.0]])
        self.check(H, "homography")

    def test_response_recovery(self):
        rad = np.logspace(-2.5, 0, 96)[None, :] * np.linspace(0.6, 1.0, 24)[:, None]
        rad = np.repeat(rad[..., None], 3, 2) * 0.9
        times = [0.25, 1.0, 4.0]
        files = [self.save(f"b{i}.png", np.clip(rad * t, 0, 1) ** (1 / 3) * 255) for i, t in enumerate(times)]
        ex = ",".join(map(str, times))

        def err(npy):
            got = np.load(npy)
            k = np.median(rad / got)
            return float(np.median(np.abs(got * k - rad) / rad))
        n1, n2, n3 = self.d / "s.npy", self.d / "r.npy", self.d / "j.npy"
        curve = self.d / "curve.json"
        rec = self.d / "rec.json"
        run("hdrmerge", *files, "--exposures", ex, "--radiance", n1, "-o", self.d / "s.png")
        o = run("hdrmerge", *files, "--exposures", ex, "--response", "recover", "--response-out", curve,
                "--radiance", n2, "-o", self.d / "r.png", "--recipe", rec)["output"]
        e_srgb, e_rec = err(n1), err(n2)
        self.assertLess(e_rec, 0.05)
        self.assertGreater(e_srgb, 2 * e_rec)
        g = np.array(json.loads(curve.read_text())["g"])
        self.assertTrue((np.diff(g, axis=1) >= 0).all())
        run("hdrmerge", *files, "--exposures", ex, "--response", curve, "--radiance", n3, "-o", self.d / "j.png")
        self.assertTrue(np.allclose(np.load(n2), np.load(n3), rtol=1e-5))
        o2 = run("run", rec, "-o", self.d / "re.png")["output"]
        self.assertTrue((arr(o2) == arr(o)).all())

    def test_c2pa_detect_and_drop(self):
        import io
        import struct
        buf = io.BytesIO()
        Image.fromarray(np.full((16, 16, 3), 120, np.uint8)).save(buf, "JPEG")
        jpg = buf.getvalue()
        payload = b"JP\x00\x00jumb....jumdc2pa\x00claim_generator\x00\x10TestCam/1.0 c2pa-rs"
        seg = b"\xff\xeb" + struct.pack(">H", len(payload) + 2) + payload
        src = self.d / "cred.jpg"
        src.write_bytes(jpg[:2] + seg + jpg[2:])
        r = run("inspect", src)["c2pa"]
        self.assertTrue(r["present"])
        self.assertEqual(r["where"], ["JPEG APP11"])
        self.assertIn("TestCam/1.0", r["claim_generator"])
        plain = self.d / "plain.jpg"
        plain.write_bytes(jpg)
        self.assertFalse(run("inspect", plain)["c2pa"]["present"])
        out = run("convert", src, "-o", self.d / "conv.png")["output"]
        self.assertFalse(run("inspect", out)["c2pa"]["present"])

    def test_lensprofile(self):
        db = self.d / "db"
        db.mkdir()
        (db / "test.xml").write_text("""<lensdatabase>
 <lens><maker>Test</maker><model>Test 18-55mm f/3.5</model><mount>X</mount><cropfactor>1.5</cropfactor>
  <calibration>
   <distortion model="poly3" focal="18" k1="-0.06"/>
   <distortion model="poly3" focal="55" k1="0.02"/>
   <vignetting model="pa" focal="18" aperture="3.5" distance="10" k1="-0.5" k2="0.1" k3="0"/>
   <vignetting model="pa" focal="18" aperture="8" distance="10" k1="-0.2" k2="0" k3="0"/>
  </calibration></lens></lensdatabase>""")
        h, w = 96, 128
        cx, cy = (w - 1) / 2, (h - 1) / 2
        R = min(cx, cy) + 0.5
        k1 = -0.06
        yy, xx = np.mgrid[0:h, 0:w].astype(float)
        rd = np.hypot(xx - cx, yy - cy) / R
        ru = rd.copy()
        for _ in range(30):  # invert rd = ru (1 - k1 + k1 ru^2)
            f = ru * (1 - k1 + k1 * ru * ru) - rd
            ru -= f / (1 - k1 + 3 * k1 * ru * ru)
        s = np.where(rd > 0, ru / np.maximum(rd, 1e-9), 1)
        ux, uy = cx + (xx - cx) * s, cy + (yy - cy) * s

        def lines(X, Y):  # smooth vertical/horizontal stripes
            return 128 + 100 * np.cos(X * 2 * np.pi / 16) * np.cos(Y * 2 * np.pi / 16)
        src = self.save("dist.png", np.repeat(lines(ux, uy)[..., None], 3, 2))
        truth = lines(xx, yy)
        r = run("lensprofile", src, "--db", db, "--lens", "18-55", "--focal", 18, "-o", self.d / "fix.png",
                "--recipe", self.d / "lp.json")
        self.assertAlmostEqual(r["profile"]["distortion"]["k1"], -0.06)
        fixed = arr(r["output"])[..., 0]
        inner = (slice(12, -12), slice(12, -12))
        e_fix = float(np.abs(fixed - truth)[inner].mean())
        e_raw = float(np.abs(arr(src)[..., 0] - truth)[inner].mean())
        self.assertLess(e_fix, 4.0)
        self.assertGreater(e_raw, 3 * e_fix)
        mid = run("lensprofile", src, "--db", db, "--lens", "18-55", "--focal", 36.5, "-o", self.d / "m.png")
        self.assertAlmostEqual(mid["profile"]["distortion"]["k1"], -0.02, places=6)
        flat = self.save("flat.png", np.full((h, w, 3), 150.0))
        v = run("lensprofile", flat, "--db", db, "--lens", "test 18", "--focal", 18, "--aperture", 3.5,
                "-o", self.d / "v.png")
        va = arr(v["output"])[..., 0]
        self.assertGreater(va[2, 2], va[h // 2, w // 2] + 20)  # corners brightened back
        self.assertLessEqual(abs(va[h // 2, w // 2] - 150), 1)
        o2 = run("run", self.d / "lp.json", "-o", self.d / "re.png")["output"]
        self.assertTrue((arr(o2) == arr(r["output"])).all())
        with self.assertRaises(SystemExit):
            run("lensprofile", src, "--db", db, "--lens", "nikkor", "--focal", 18, "-o", self.d / "x.png")


if __name__ == "__main__":
    unittest.main()
