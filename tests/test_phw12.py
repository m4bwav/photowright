"""Proof bars for batch 12 (phw 0.13.0).

- Custom kernel: identity kernel bit-exact; 3x3 ones == brute-force symmetric-padded mean within 1/255;
  offset 10 on a zero-sum kernel over a flat image gives exactly 10.
- Reveal All: canvas grows to the union of layer rects; the old canvas area of the flattened result
  equals the original flatten bit-exactly; the off-canvas layer's pixels now all show.
- Apply Image: normal/rgb/opacity 1 == source; multiply with the source luma == brute-force a*luma
  within 1/255; opacity 0 identity; --calc output is grey.
- Texture: amount 0 identity; flat invariant; +0.8 raises high-frequency energy, -1 lowers it; mean within 1/255.
- Pointillize: every pixel is the background or a source cell mean; flat source -> two values; seeded.
- Extrude: depth 0 == the block means (mosaic) within 1/255; flat source -> only the colour and 0.6x it.
- Tiles: offset 0 bit-exact identity; with offset every pixel is a source value or the background; seeded.
- Lens blur: flat invariant; a single dot spreads to the disc / hexagon area within 15%; boost raises the
  spread energy. Shape blur square r == box blur r within 1/255.
- Lens flare: brightness 0 identity; output >= input; the brightest gain sits within 3 px of the flare centre.
- Lighting: ambient 1 intensity 0 identity; flat point light peaks at the light and falls with distance;
  spot light leaves outside-cone pixels at colour x ambient within 1/255; a lit-from-left bump ridge is
  brighter on its left slope.
- Liquify: strength 0 identity; flat invariant; a dot on the stroke moves along it (+x); pixels farther
  than radius + stroke length stay bit-exact.
- Masks keep outside pixels; `phw run` replays the recipe bit-exactly.
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
from phw import compose, core, filters, layered  # noqa: E402

warnings.simplefilter("ignore", ResourceWarning)
Y709 = np.array([0.2126, 0.7152, 0.0722])


def run(*args):
    _, r = phw.main(list(map(str, args)))
    return r


def arr(p):
    return np.asarray(Image.open(p)).astype(np.int32)


class Batch12(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="phw12-"))
        self.rng = np.random.default_rng(12)
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

    # ------------------------------------------------------------ custom kernel
    def test_kernel(self):
        a = arr(run("filter", self.np_, "-o", self.out(), "--kernel", "0,0,0;0,1,0;0,0,0")["output"])
        self.assertTrue((a == self.noise).all())
        b = arr(run("filter", self.np_, "-o", self.out(), "--kernel", "1,1,1,1,1,1,1,1,1")["output"])
        p = np.pad(self.noise.astype(float), ((1, 1), (1, 1), (0, 0)), mode="symmetric")
        ref = sum(p[y:y + 32, x:x + 40] for y in range(3) for x in range(3)) / 9
        self.assertLessEqual(np.abs(b - ref).max(), 1.0)
        f = self.flat((0, 0, 0))
        c = arr(run("filter", f, "-o", self.out(), "--kernel", "0,-1,0,-1,4,-1,0,-1,0", "--kernel-offset", 10)["output"])
        self.assertTrue((c == 10).all())

    # ------------------------------------------------------------ reveal all
    def test_reveal_all(self):
        bg = np.ones((20, 20, 4), np.float32)
        bg[..., :3] = 0.5
        a = np.zeros((10, 10, 4), np.float32)
        a[..., 0] = a[..., 3] = 1
        b = np.zeros((8, 8, 4), np.float32)
        b[..., 1] = b[..., 3] = 1
        doc = compose.Doc(20, 20, [compose.Layer("bg", bg), compose.Layer("a", a, -5, 14), compose.Layer("b", b, 15, -3)])
        src = self.d / "x.ora"
        layered.write_ora(doc, src, core.Used())
        flat0 = np.round(compose.composite_doc(layered.read_layered(src, core.Used())) * 255)
        r = run("canvas", src, "--reveal-all", "-o", self.d / "y.ora")
        self.assertEqual((r["after"], r["shift"]), ([28, 27], [5, 3]))
        doc2 = layered.read_layered(r["output"], core.Used())
        flat1 = np.round(compose.composite_doc(doc2) * 255)
        self.assertTrue((flat1[3:23, 5:25] == flat0).all())
        self.assertTrue((flat1[17:27, 0:10, 0] == 255).all() and (flat1[0:8, 20:28, 1] == 255).all())

    # ------------------------------------------------------------ apply image
    def test_apply_image(self):
        other = self.rng.integers(0, 256, (32, 40, 3), dtype=np.uint8)
        q = self.save("other.png", other)
        a = arr(run("apply-image", self.np_, "-o", self.out(), "--source", q, "--blend", "normal")["output"])
        self.assertTrue((a == other).all())
        b = arr(run("apply-image", self.np_, "-o", self.out(), "--source", q, "--channel", "luma")["output"])
        lum = (other / 255.0 * Y709).sum(2, keepdims=True)
        self.assertLessEqual(np.abs(b - self.noise * lum).max(), 1.0)
        c = arr(run("apply-image", self.np_, "-o", self.out(), "--source", q, "--opacity", 0)["output"])
        self.assertTrue((c == self.noise).all())
        g = arr(run("apply-image", self.np_, "-o", self.out(), "--source", q, "--channel", "r", "--calc")["output"])
        self.assertTrue((g[..., 0] == g[..., 1]).all() and (g[..., 1] == g[..., 2]).all())

    # ------------------------------------------------------------ texture
    def test_texture(self):
        hf = lambda x: np.abs(np.diff(x.astype(float), axis=1)).mean()  # noqa: E731
        mid = self.save("mid.png", 64 + self.noise // 2)
        src = arr(mid)
        self.assertTrue((arr(run("fx", mid, "-o", self.out(), "--texture", 0)["output"]) == src).all())
        f = self.flat()
        self.assertTrue((arr(run("fx", f, "-o", self.out(), "--texture", 0.8)["output"]) == arr(f)).all())
        up = arr(run("fx", mid, "-o", self.out(), "--texture", 0.8)["output"])
        dn = arr(run("fx", mid, "-o", self.out(), "--texture", -1)["output"])
        self.assertGreater(hf(up), 1.3 * hf(src))
        self.assertLess(hf(dn), 0.7 * hf(src))
        self.assertLess(abs(up.mean() - src.mean()), 1.0)

    # ------------------------------------------------------------ pointillize
    def test_pointillize(self):
        a = arr(run("fx", self.np_, "-o", self.out(), "--pointillize", 6, "--seed", 3)["output"])
        b = arr(run("fx", self.np_, "-o", self.out(), "--pointillize", 6, "--seed", 3)["output"])
        self.assertTrue((a == b).all())
        self.assertGreater((a != 255).any(2).mean(), 0.5)
        f = arr(run("fx", self.flat(), "-o", self.out(), "--pointillize", 6)["output"])
        vals = {tuple(v) for v in f.reshape(-1, 3)}
        self.assertEqual(vals, {(120, 90, 60), (255, 255, 255)})

    # ------------------------------------------------------------ extrude
    def test_extrude(self):
        a = arr(run("fx", self.np_, "-o", self.out(), "--extrude", "8,0")["output"]).astype(float)
        ref = self.noise.astype(float).reshape(4, 8, 5, 8, 3).mean((1, 3)).repeat(8, 0).repeat(8, 1)
        self.assertLessEqual(np.abs(a - ref).max(), 1.0)
        f = arr(run("fx", self.flat(), "-o", self.out(), "--extrude", "6,0.4", "--seed", 2)["output"])
        vals = {tuple(v) for v in f.reshape(-1, 3)}
        self.assertTrue(vals <= {(120, 90, 60), (72, 54, 36)})
        self.assertEqual(len(vals), 2)

    # ------------------------------------------------------------ tiles
    def test_tiles(self):
        a = arr(run("fx", self.np_, "-o", self.out(), "--tiles", 5, "--tile-offset", 0)["output"])
        self.assertTrue((a == self.noise).all())
        b = arr(run("fx", self.np_, "-o", self.out(), "--tiles", 5, "--tile-offset", 0.25, "--seed", 1)["output"])
        c = arr(run("fx", self.np_, "-o", self.out(), "--tiles", 5, "--tile-offset", 0.25, "--seed", 1)["output"])
        self.assertTrue((b == c).all())
        src = {tuple(v) for v in self.noise.reshape(-1, 3)} | {(255, 255, 255)}
        self.assertTrue({tuple(v) for v in b.reshape(-1, 3)} <= src)
        self.assertGreater((b == 255).all(2).sum(), 0)

    # ------------------------------------------------------------ lens / shape blur
    def test_lens_blur(self):
        f = self.flat()
        self.assertTrue((arr(run("lensblur", f, "-o", self.out(), "--lens", 4)["output"]) == arr(f)).all())
        dot = np.zeros((41, 41, 3))
        dot[20, 20] = 255
        p = self.save("dot.png", dot)
        for iris, area in (("disc", np.pi * 64), ("hexagon", 1.5 * 3 ** 0.5 * 64)):
            a = arr(run("lensblur", p, "-o", self.out(), "--lens", 8, "--iris", iris)["output"])
            self.assertLess(abs((a[..., 0] > 0).sum() - area) / area, 0.15, iris)
        e0 = arr(run("lensblur", p, "-o", self.out(), "--lens", 3)["output"]).sum()
        e1 = arr(run("lensblur", p, "-o", self.out(), "--lens", 3, "--boost", 4)["output"]).sum()
        self.assertGreater(e1, 1.5 * e0)
        sq = arr(run("lensblur", self.np_, "-o", self.out(), "--shape-blur", 2, "--shape", "square")["output"])
        box = filters.box_blur(self.noise[..., 0].astype(np.float32), 2)
        self.assertLessEqual(np.abs(sq[..., 0] - box).max(), 1.0)

    # ------------------------------------------------------------ lens flare
    def test_flare(self):
        a = arr(run("fx", self.np_, "-o", self.out(), "--flare", "10,8", "--brightness", 0)["output"])
        self.assertTrue((a == self.noise).all())
        dark = self.save("dark.png", self.noise // 4)
        src = arr(dark)
        b = arr(run("fx", dark, "-o", self.out(), "--flare", "10,8")["output"])
        self.assertTrue((b >= src).all())
        g = (b - src).sum(2)
        y, x = np.unravel_index(np.argmax(g), g.shape)
        self.assertLessEqual(np.hypot(x - 10, y - 8), 3)

    # ------------------------------------------------------------ lighting
    def test_lighting(self):
        a = arr(run("fx", self.np_, "-o", self.out(), "--light", "10,10", "--ambient", 1, "--intensity", 0)["output"])
        self.assertTrue((a == self.noise).all())
        f = self.flat((200, 200, 200), 41)
        b = arr(run("fx", f, "-o", self.out(), "--light", "20,20,10", "--ambient", 0, "--intensity", 1)["output"])[..., 0]
        self.assertEqual(b[20, 20], b.max())
        row = b[20, 20:]
        self.assertTrue((np.diff(row) <= 0).all() and row[-1] < row[0] - 50)
        s = arr(run("fx", f, "-o", self.out(), "--light", "5,20,10", "--light-kind", "spot", "--target", "15,20",
                    "--cone", 20, "--ambient", 0.3)["output"])[..., 0]
        self.assertLessEqual(abs(s[20, 40] - 60), 1)
        self.assertLessEqual(abs(s[0, 0] - 60), 1)
        self.assertGreater(s[20, 15], 100)
        x = np.arange(41)
        ridge = 128 + 100 * np.exp(-((x - 20) / 5.0) ** 2)
        rp = self.save("ridge.png", np.stack([np.tile(ridge, (41, 1))] * 3, 2))
        c = arr(run("fx", rp, "-o", self.out(), "--light", "-200,20,60", "--ambient", 0, "--bump", 20)["output"]).astype(float)
        src = arr(rp).astype(float)
        ratio = c[20, :, 0] / src[20, :, 0]
        self.assertGreater(ratio[16], ratio[24] + 0.05)

    # ------------------------------------------------------------ liquify
    def test_liquify(self):
        a = arr(run("liquify", self.np_, "-o", self.out(), "--stroke", "5,16 20,16", "--strength", 0)["output"])
        self.assertTrue((a == self.noise).all())
        f = self.flat()
        self.assertTrue((arr(run("liquify", f, "-o", self.out(), "--stroke", "5,12 18,12", "--radius", 6)["output"])
                         == arr(f)).all())
        im = np.zeros((40, 60, 3))
        im[18:23, 13:18] = 255
        p = self.save("blob.png", im)
        b = arr(run("liquify", p, "-o", self.out(), "--stroke", "15,20 35,20", "--radius", 8, "--strength", 0.6)["output"])
        cx0 = (np.arange(60) * im[..., 0].sum(0)).sum() / im[..., 0].sum()
        cx1 = (np.arange(60) * b[..., 0].sum(0)).sum() / b[..., 0].sum()
        self.assertGreater(cx1 - cx0, 4)
        self.assertTrue((b[:, 45:] == 0).all() and (b[:8] == 0).all())

    # ------------------------------------------------------------ mask + replay
    def test_mask_and_replay(self):
        m = np.zeros((32, 40), np.uint8)
        m[:, 20:] = 255
        Image.fromarray(m).save(self.d / "m.png")
        rec = self.d / "r.json"
        r = run("lensblur", self.np_, "-o", self.out(), "--shape-blur", 3, "--mask", self.d / "m.png", "--recipe", rec)
        a = arr(r["output"])
        self.assertTrue((a[:, :19] == self.noise[:, :19]).all())
        self.assertFalse((a[:, 21:] == self.noise[:, 21:]).all())
        self.assertTrue(json.loads(rec.read_text()))
        self.assertTrue((arr(run("run", rec, "-o", self.out())["output"]) == a).all())
        rec2 = self.d / "r2.json"
        r2 = run("fx", self.np_, "-o", self.out(), "--pointillize", 5, "--light", "5,5", "--recipe", rec2)
        self.assertTrue((arr(run("run", rec2, "-o", self.out())["output"]) == arr(r2["output"])).all())


if __name__ == "__main__":
    unittest.main()
