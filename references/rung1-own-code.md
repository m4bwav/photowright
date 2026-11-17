# Rung 1: own code (Python stdlib, Pillow, NumPy)

Checked 2026-11-16. Machine: Windows 11, Python 3.14.6, Pillow 12.3.0, NumPy 2.5.2 (also present: OpenCV 5.0.0, scikit-image 0.26.0, SciPy 1.18.1, which count as rung 2).

## What each layer does alone

- **stdlib**: no pixel decoding; `zlib` (enough to write a PNG by hand) and `colorsys` (RGB/HSV/HLS per pixel, slow). Good for file handling, JSON recipes, `.cube` parsing. https://docs.python.org/3/library/colorsys.html
- **Pillow** (MIT-CMU / HPND licence, https://github.com/python-pillow/Pillow/blob/main/LICENSE): open/save most raster formats (PNG, JPEG, WebP, TIFF, GIF, BMP, ICO, AVIF), resize (NEAREST to LANCZOS), crop/rotate/transform (affine, perspective, mesh), `ImageFilter` (GaussianBlur, BoxBlur, UnsharpMask, Rank/Median, kernels, Color3DLUT), `ImageEnhance` (brightness, contrast, colour, sharpness), `ImageOps` (autocontrast, equalize, posterize, solarize, fit, pad, exif_transpose), `ImageChops` (add, subtract, multiply, screen, overlay, soft_light, hard_light, darker, lighter, difference), `Image.point` LUTs, `alpha_composite`, `ImageDraw`/`ImageFont`, `ImageCms` (LittleCMS ICC transforms). https://pillow.readthedocs.io/en/stable/reference/index.html
- **NumPy** (BSD-3, https://github.com/numpy/numpy/blob/main/LICENSE.txt): float32 per-pixel maths: every blend mode, curves, levels, channel mixer, masks, gradients, HSL, vignette, 3D LUT with trilinear interpolation (hand-written).

## Where they stop

- Pillow is mostly 8 bits per channel; 16-bit modes are single-channel ("I;16"), float "F" is single-channel. Do multi-step work in NumPy float32 and quantise once on save. https://pillow.readthedocs.io/en/stable/handbook/concepts.html#modes
- No RAW decoding, no PSD writing (Pillow reads PSD only), no EXR/HDR, no content-aware fill, no inpainting, no real selection tools beyond threshold, colour-range masks and `ImageDraw.floodfill`.
- Pillow's ImageChops soft_light/hard_light/overlay are not reference-exact to W3C; write our own for Photoshop parity.
- Large-radius blur in pure NumPy needs FFT or box passes; Pillow's GaussianBlur is about 10x slower than OpenCV (table below).
- Memory: 4000x3000 float32 RGBA is 192 MB; a compound blend with temporaries can approach 1 GB.

## Timings (4000x3000 RGB uint8 random image, best of 3, this machine, 2026-11-16)

| Operation | ms |
|---|---|
| Pillow resize LANCZOS to 2000x1500 | 78 |
| OpenCV resize LANCZOS4 (rung 2, comparison) | 8.5 |
| Pillow GaussianBlur(radius 10) | 239 |
| OpenCV GaussianBlur sigma 10 (rung 2) | 22 |
| Pillow `point()` curves LUT, 3 channels | 18 |
| NumPy fancy-index LUT `lut[a]` | 46 |
| NumPy multiply blend, float32 | 26 |
| NumPy soft light (W3C formula), float32 | 619 |
| Pillow PNG save (random data, worst case) | 994 |

Takeaway: LUT work is near-instant in Pillow; compound NumPy formulas cost about 0.5 s per 12 MP (use `out=` buffers or numexpr-style chunking if it matters); filters and resize are where OpenCV pays off.

## Blend modes

Sources: W3C Compositing and Blending Level 1, https://www.w3.org/TR/compositing-1/#blending ; Adobe/ISO 32000-1 (PDF 1.7) section 11.3.5, https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf . The W3C text follows the PDF (Adobe) definitions. Cb = backdrop, Cs = source, values 0..1.

Composite with alpha (W3C section 5.8): `Cs' = (1 - ab) * Cs + ab * B(Cb, Cs)`, then source-over: `co = cs' * as + cb * ab * (1 - as)`, `ao = as + ab * (1 - as)` (premultiplied co).

### Separable (per channel)
- normal: `B = Cs`
- multiply: `B = Cb * Cs`
- screen: `B = Cb + Cs - Cb * Cs`
- overlay: `B = HardLight(Cs, Cb)` (hard light with the arguments swapped)
- darken: `B = min(Cb, Cs)`
- lighten: `B = max(Cb, Cs)`
- color-dodge: `0 if Cb == 0; 1 if Cs == 1; else min(1, Cb / (1 - Cs))`
- color-burn: `1 if Cb == 1; 0 if Cs == 0; else 1 - min(1, (1 - Cb) / Cs)`
- hard-light: `Multiply(Cb, 2*Cs) if Cs <= 0.5 else Screen(Cb, 2*Cs - 1)`
- soft-light: `Cb - (1 - 2*Cs) * Cb * (1 - Cb) if Cs <= 0.5 else Cb + (2*Cs - 1) * (D(Cb) - Cb)`, with `D(Cb) = ((16*Cb - 12)*Cb + 4)*Cb if Cb <= 0.25 else sqrt(Cb)`
- difference: `B = |Cb - Cs|`
- exclusion: `B = Cb + Cs - 2 * Cb * Cs`

Photoshop-only modes (Adobe publishes descriptions, not formulas: https://helpx.adobe.com/photoshop/using/blending-modes.html ; the formulas below are the widely used community derivations, unverified against Photoshop): linear burn `max(0, Cb + Cs - 1)`, linear dodge/add `min(1, Cb + Cs)`, subtract `max(0, Cb - Cs)`, divide `min(1, Cb / Cs)`, linear light `clip(Cb + 2*Cs - 1)`, vivid light (color-burn with 2*Cs below 0.5, color-dodge with 2*(Cs-0.5) above), pin light (darken with 2*Cs below 0.5, lighten with 2*(Cs-0.5) above), hard mix (`1 if Cb + Cs >= 1 else 0`), darker/lighter colour (pick whole pixel by Lum). Photoshop's own soft light differs slightly from the W3C/PDF one.

### Non-separable (W3C section 5.9)
```
Lum(C) = 0.3*R + 0.59*G + 0.11*B
ClipColor(C): L = Lum(C); n = min(R,G,B); x = max(R,G,B)
  if n < 0: C = L + (C - L) * L / (L - n)
  if x > 1: C = L + (C - L) * (1 - L) / (x - L)
SetLum(C, l): d = l - Lum(C); return ClipColor(C + d)
Sat(C) = max(R,G,B) - min(R,G,B)
SetSat(C, s): sort components into Cmax, Cmid, Cmin
  if Cmax > Cmin: Cmid = (Cmid - Cmin) * s / (Cmax - Cmin); Cmax = s
  else: Cmid = Cmax = 0
  Cmin = 0
```
- hue: `B = SetLum(SetSat(Cs, Sat(Cb)), Lum(Cb))`
- saturation: `B = SetLum(SetSat(Cb, Sat(Cs)), Lum(Cb))`
- color: `B = SetLum(Cs, Lum(Cb))`
- luminosity: `B = SetLum(Cb, Lum(Cs))`

Browsers and Photoshop (8-bit default) blend gamma-encoded sRGB; keep that as default for parity, offer linear light as an option.

## Curves, levels, LUTs, grading

- **Curves**: control points to a 256 or 65536 entry table with monotone cubic (PCHIP/Fritsch-Carlson) to avoid overshoot; apply with `Image.point` (8-bit) or `np.interp` (float32). Photoshop `.acv`: big-endian int16 version, curve count, then per curve a point count and (output, input) int16 pairs. https://www.adobe.com/devnet-apps/photoshop/fileformatashtml/
- **Levels**: `out = clip((x - in_black)/(in_white - in_black), 0, 1) ** (1/gamma) * (out_white - out_black) + out_black`.
- **Grading**: ASC CDL `out = (in * slope + offset) ** power` then saturation around Rec.709 luma (https://en.wikipedia.org/wiki/ASC_CDL); channel mixer = 3x3 matrix; split toning by luminance masks; white balance = per-channel gains in linear light.
- **.cube 3D LUT** (Adobe Cube LUT Specification 1.0, https://web.archive.org/web/2020/https://wwwimages2.adobe.com/content/dam/acom/en/products/speedgrade/cc/pdfs/cube-lut-specification-1.0.pdf): text; optional `TITLE "x"`; `LUT_3D_SIZE N` (2..256) or `LUT_1D_SIZE N`; optional `DOMAIN_MIN r g b` / `DOMAIN_MAX r g b` (defaults 0 and 1); `#` comments; then N^3 lines `R G B` floats, red index changing fastest, then green, then blue. Apply with Pillow `ImageFilter.Color3DLUT(size, table)` (trilinear, red-fastest order too, so a parsed .cube maps straight in; https://pillow.readthedocs.io/en/stable/reference/ImageFilter.html#PIL.ImageFilter.Color3DLUT) or NumPy trilinear/tetrahedral on float32.
- **Hald CLUT** images (ImageMagick, G'MIC, darktable use them) are a 3D LUT stored as a square image; trivial to convert to and from .cube in NumPy.

## Design findings
1. All maths in NumPy float32 0..1, quantise once on save; Pillow is codec plus the fast LUT and resize path.
2. Implement W3C blend modes ourselves with tests; do not rely on ImageChops for parity.
3. `.cube` parse plus `Color3DLUT` gives grading at rung 1.
4. OpenCV is the first rung-2 accelerator (10x on blur and resize) and is installed here.
