# Coverage gaps: rung 1 and 2 rows phw does not implement (2026-11-17)

Scored against [references/photoshop-feature-map.md](../../references/photoshop-feature-map.md) using `phw.py <cmd> --help` and a keyword sweep of `scripts/phw/*.py` (phw 0.8.0). Rows that phw covers (levels, curves, exposure, hue/sat, LUT, b&w, equalize, white balance, blend modes, layer masks, clipping, groups, text, shapes, drop shadow, stroke, marquee, lasso, magic wand, colour range, grow/shrink/feather, heal, clone, patch, content-aware fill, red eye, image size, crop, rotate, perspective, warp, stack, stitch, unsharp mask, despeckle/median, reduce noise, batch, sheet, recipes, PSD/ORA, tracing) are left out.

Status: **BUILT 0.9.0** = built in this session (tests/test_phw8.py); gap = still missing; partial = some of the row exists.

| Row | Rung | Status | Owner command |
|---|---|---|---|
| Gaussian Blur | 1 | **BUILT 0.9.0** (impulse sum 1, variance sigma^2 within 2%) | `filter --blur gaussian` |
| Box Blur | 1 | **BUILT 0.9.0** (= brute-force mean, max 1/255 rounding) | `filter --blur box` |
| Motion Blur | 1 | **BUILT 0.9.0** (spread along angle >2.5 px, across <0.6 px) | `filter --blur motion` |
| High Pass | 1 | **BUILT 0.9.0** (flat -> 0.5 within 1e-5) | `filter --high-pass` |
| Maximum / Minimum | 1 | **BUILT 0.9.0** (= brute-force dilation/erosion, bit exact) | `filter --maximum/--minimum` |
| Offset | 1 | **BUILT 0.9.0** (= np.roll, bit exact) | `filter --offset` |
| Invert | 1 | **BUILT 0.9.0** (exact on all 256 values) | `color --invert` |
| Posterize | 1 | **BUILT 0.9.0** (floor(xN/256)*255/(N-1), exact) | `color --posterize` |
| Threshold | 1 | **BUILT 0.9.0** (Rec. 601 luma >= t, exact) | `color --threshold` |
| Solarize | 1 | **BUILT 0.9.0** (x>127 -> 255-x, exact) | `color --solarize` |
| Channel Mixer | 1 | **BUILT 0.9.0** (= matrix product within 1/255; identity bit exact) | `color --mixer` |
| Gradient Map | 1 | **BUILT 0.9.0** (ends exact, midpoint at middle stop) | `color --gradient-map` |
| Brightness/Contrast | 1 | **BUILT 0.11.0** `grade` (0/255 fixed, monotone on all 256 levels) | `adjust` |
| Vibrance | 1 | **BUILT 0.10.0** (grey unchanged, dull chroma gains > saturated + 0.3) | `adjust` |
| Color Balance | 1 | **BUILT 0.11.0** `grade --balance-*` (preserve luminosity: luma within 1/255) | `adjust` |
| Photo Filter | 1 | **BUILT 0.11.0** `grade --photo-filter` (density 0 identity, luma within 1/255) | `color` |
| Selective Color | 1 | **BUILT 0.11.0** `grade --selective` absolute (reds c+1: pure red -> R 0; greys, blue untouched) | `color` |
| Shadows/Highlights | 1 | **BUILT 0.10.0** (dark side +15/255, bright side within 1/255, hue ratio within 3%) | `adjust` |
| HDR Toning | 2 | gap | `adjust` |
| Desaturate | 1 | **BUILT 0.11.0** `grade --desaturate` ((max+min)/2 within 0.5/255) | `adjust` |
| Match Color / Color Transfer | 1 | **BUILT 0.10.0** (Lab mean within 1.5, self-match within 1/255) | `color --match` |
| Replace Color | 1 | **BUILT 0.16.0** `replacecolor --pick x,y|--color --fuzziness --hue --saturation --lightness` (beyond fuzziness bit-exact, target hue turns within 1 deg, fuzziness 0 exact colour only) | `color` |
| Auto Tone / Contrast / Color | 1 | **BUILT 0.10.0** (full 0..255 range; auto color channel means within 2/255 of luma) | `adjust --auto` |
| Camera Raw basic panel | 2 | gap | none planned |
| Dehaze | 1 | **BUILT 0.11.0** `detail --dehaze` dark channel prior (synthetic haze RMS to truth < 40% of hazy) | `adjust` |
| Clarity / Texture | 1 | **BUILT 0.11.0** Clarity `detail --clarity` (flat unchanged, spread x1.2); **BUILT 0.13.0** Texture `fx --texture` (0 identity, flat unchanged, +0.8 raises adjacent-difference energy >1.3x, -1 lowers it <0.7x, mean within 1/255) | `adjust` |
| Indexed colour / palette for web | 1 | **BUILT 0.17.0** `indexed --palette auto|web|gray|FILE --dither none|floyd|ordered|noise` (none == brute-force nearest; FS white share on grey 128 within 1/100, Bayer 8 within 1/64; transparency index) | `convert` |
| Blend If | 1 | **BUILT 0.16.0** `blendif --layer --this b0,b1,w0,w1 --under ... --channel` (defaults == normal over bit-exact, underlying 128 split keeps base below exactly, split ramp half within 1/255) | `layers` |
| Gradient tool, fill layers (gradient, pattern) | 1 | **BUILT 0.16.0** `gradient --kind linear|radial|angle|reflected|diamond --start --end --colors` and `pattern --tile --offset`; `layers` types `gradient`/`pattern` (linear == projection within 1/255, radial == distance, fill layer == command within 1/255, pattern bit-exact) | `layers` |
| Inner Shadow, Outer/Inner Glow, Bevel, Satin, overlays | 1 | **BUILT 0.16.0** (Satin BUILT 0.17.0: interior bit-exact, alpha kept) `layerstyle --color-overlay --gradient-overlay --inner-shadow --inner-glow --outer-glow --bevel` (overlay exact inside, alpha kept; outer glow leaves the layer bit-exact and falls off; bevel centre unchanged, lit edge brighter); Satin still a gap | `layers` |
| Smart Objects / Smart Filters / linked | 1 | partial (layered recipe re-renders) | `layers` |
| Artboards, Layer comps | 1 | gap | `layers` |
| Auto-Blend Layers | 2 | partial (stack focus mode) | `stack` |
| Auto-Align Layers | 2 | gap | `stack --align` |
| Merge to HDR Pro | 2 | gap (exposure fusion only) | `stack` |
| Apply Image / Calculations | 1 | **BUILT 0.13.0** `apply-image --source --channel --blend [--calc]` (normal == source exact, multiply by source luma == brute force within 1/255, opacity 0 identity, --calc grey) | `layers` |
| Spot channels | 2 | gap | `save` |
| Magnetic Lasso | 2 | gap | `select` |
| Focus Area | 1 | **BUILT 0.16.0** `focusarea --radius [--threshold] [--soft]` (Laplacian energy + Otsu, pulled back 2 sigma: sharp/blurred halves >95% right 4 px from the seam, sharp disc IoU > 0.75) | `select --focus` |
| Quick Selection | 2 | partial (GrabCut in cutout) | `select` |
| Spot Healing Brush | 2 | partial (`heal`) | `heal` |
| Content-Aware Move / Extend | 2 | partial: **BUILT 0.15.0** Move `camove --rect x,y,w,h --to dx,dy --method` (block lands bit-exact, outside both rects bit-exact, vacated area on flat bg within 2/255, replay bit-exact); **Extend BUILT 0.17.0** `caextend` (source and outside dest bit-exact, dest ring kept, interior gradients == patch within 2/255) | `fill` |
| Dodge / Burn / Sponge | 1 | **BUILT 0.12.0** `tonebrush --mask` (highlights dodge moves bright 3x dark, 0/255 fixed; sponge chroma -40%, luma within 2/255) | `adjust --mask` route |
| Blur / Sharpen / Smudge brushes, brush engine | 1 | **BUILT 0.15.0** `paint --tool blur|sharpen|smudge --stroke --radius --strength` (strength 0 identity, beyond radius bit-exact, blur halves noise std, sharpen HF energy >1.5x, smudge drags a blob centroid >2 px, flat unchanged); full brush engine still a gap | new `paint` |
| Eraser / Magic Eraser / Paint Bucket | 1 | **BUILT 0.16.0** `erase --stroke|--magic x,y --tolerance [--all]`, `bucket --at --color --tolerance [--all]` (beyond radius bit-exact, stroke alpha 0, contiguous vs global regions exact, replay bit-exact) | `mask`/`select` |
| Liquify | 1 | **BUILT 0.13.0** push `liquify --stroke` (strength 0 identity, flat unchanged, blob centroid moves >4 px along the stroke, far pixels exact); **BUILT 0.14.0** `--mode twirl|pucker|bloat` (outside radius bit-exact, flat unchanged, bloat disc area >1.3x, pucker <0.8x) | `warp` |
| Frequency separation | 1 | **BUILT 0.11.0** `detail --freq-sep --part low|high` (low+high-0.5 within 2/255) | `filter` |
| Radial, Lens, Surface, Shape blur; Blur Gallery | 1 | partial: **BUILT 0.12.0** `blurfx --spin/--zoom` (rings/spokes kept, spoke spread halved) and `--surface R,T` (100-level step exact, noise std halved); **BUILT 0.13.0** `lensblur --lens R --iris disc; **BUILT 0.15.0** `--iris CX,CY,RX,RY` (inside ellipse bit-exact, beyond ramp == Gaussian within 1/255) and `--path 'x,y ...' --length` (horizontal path == mean of shifts within 1/255, vertical stripes unchanged along a vertical path) |hexagon --boost` (flat unchanged, dot spreads to disc/hexagon area within 15%, boost raises energy >1.5x) and `--shape-blur` (square == box blur within 1/255); **BUILT 0.14.0** `blurgallery --tilt` (band bit-identical, beyond ramp == full Gaussian within 1/255) and `--field` (at a pin == that sigma's Gaussian within 1/255) | `filter` |
| Smart Sharpen | 1 | **BUILT 0.11.0** `detail --smart-sharpen` Wiener (sigma 1.5 blur: RMS < 70% of blurred and below unsharp) | `sharpen` |
| Shake Reduction | 2 | **BUILT 0.17.0 (rung 1)** `shake --length --angle` known straight trace, Richardson-Lucy (error a third lower; wrong angle worse); blind trace estimate still a gap | `sharpen` |
| Add Noise | 1 | **BUILT 0.10.0** (std within 5%, mean shift < 0.5/255, seeded) | `filter` |
| Emboss, Find Edges, Trace Contour | 1 | **BUILT 0.10.0** Emboss + Find Edges (flat -> 128 / 255 exactly); **BUILT 0.12.0** Trace Contour (black pixels within 1.5 px of a disc's radius) | `filter` |
| Diffuse, Wind, Extrude, Tiles; Oil Paint; Pixelate family | 1 | partial: **BUILT 0.11.0** Mosaic `pixelate --cell` (cell = source mean within 1/255); **BUILT 0.12.0** Crystallize (cell = source mean within 1/255), Color Halftone (flat grey mean within 10/255), Diffuse (3x3 neighbour, seeded), Wind (one-sided decaying trail), Oil Paint (Kuwahara: step two-valued, noise std halved); **BUILT 0.13.0** `fx --pointillize` (pixels are bg or cell means, flat -> 2 values, seeded), `--extrude` (depth 0 == block means within 1/255, flat -> colour and 0.6x only), `--tiles` (offset 0 identity, pixels from source or bg, seeded) | `filter` |
| Distort family (Pinch, Twirl, Polar ...) | 1 | partial: **BUILT 0.11.0** `distort --pinch/--twirl/--polar` (outside circle within 1/255; polar rows->rings within 3/255); **BUILT 0.12.0** `warpfx` Wave/Ripple (line follows amp sin within 1 px), Spherize (disc +30%/-20%, corners within 1/255), ZigZag (rings within 3/255) | `warp` |
| Adaptive Wide Angle | 2 | gap | `perspective` |
| Lens Correction | 1 | **BUILT 0.12.0** `warpfx --lens k1,k2` (dot lands at the solved radius within 1 px) | `perspective` |
| Vanishing Point | 1 | gap | `clone` |
| Clouds / Fibers, Lens Flare / Lighting | 1 | partial: **BUILT 0.12.0** Clouds (seeded, between fg/bg, low-frequency energy > 4x high); **BUILT 0.13.0** Lens Flare `fx --flare` (0 identity, output >= input, peak gain within 3 px of centre), Lighting `fx --light --light-kind point|spot --bump` (ambient 1 identity, point peaks at light and falls, outside spot cone = colour x ambient within 1/255, bump ridge lit on the light side); **BUILT 0.14.0** `fibers` (seeded, between fg/bg, vertical gradient energy < 1/4 horizontal) | `filter` |
| Filter Gallery | 1 | **BUILT 0.15.0** `filtergallery --step "CMD ARGS" ... --sheet` (chain == the commands run one by one, mean diff <= 2/255, one sheet tile per stage, replay bit-exact) | `filter` |
| Custom kernel, De-Interlace, NTSC Colors | 1 | partial: **BUILT 0.13.0** Custom `filter --kernel` (identity bit-exact, 3x3 ones == brute-force mean within 1/255, offset exact); **BUILT 0.14.0** `deinterlace` (kept field bit-exact, combed image restored within 3/255) and `ntsc` (Y+C <= 1.1, Y-C >= -0.2 within 1/255; safe pixels within 1/255) | `filter` |
| Content Credentials (C2PA) | 2 | gap | `convert` |
| Canvas Size, Trim / Reveal All | 1 | **BUILT 0.10.0** Canvas Size + Trim (pixels exact at anchor, trim(canvas(x)) == x); **BUILT 0.13.0** Reveal All `canvas --reveal-all` on .psd/.ora/layers json (canvas = union of layer rects, old area of the flatten bit-exact, off-canvas layers fully shown) | `crop` |
| Free Transform (skew) | 1 | **BUILT 0.11.0** `distort --skew X,Y` (line shift = H tan a within 1 px) | `perspective` |
| Crop and Straighten Photos | 1 | **BUILT 0.15.0** `cropstraighten SCAN OUTDIR` (two photos at 7 and -12 deg: 2 files, angles within 0.5 deg, sizes within 4 px, content mean error < 6/255) | `stitch` |
| Lens profile correction | 2 | gap | `perspective` |
| Make Work Path from selection | 2 | partial (trace of a mask) | `trace` |
| Variables (data-driven graphics) | 1 | **BUILT 0.14.0** `variables TEMPLATE.json DATA.csv OUTDIR --name COL` (each row == `layers` on the edited recipe bit-exact, text and image swapped, template unchanged, rerun writes nothing, a missing-image row reported and the rest finish) | `batch` |
| Export layers / artboards; Generator assets | 1 | **BUILT 0.15.0** `export-layers FILE OUTDIR [--trim] [--artboards]` (layers composited back == flattened within 1.5/255 from recipe and PSD, trim boxes == layer rects, artboard == group alone); Generator assets still a gap | `open` |
| History / Snapshots | 1 | **BUILT 0.17.0** `run RECIPE --upto N` (0 == source, 1 == first edit bit-exact, N == full replay) | `run` |
| Layered TIFF, AVIF/HEIC/JXL, camera raw, PDF/EPS open, video layers | 2 | gap | `open`/`convert` |

Built in 0.10.0 (tests/test_phw9.py): Auto Tone/Contrast/Color, Vibrance, Shadows/Highlights, Match Color, Add Noise, Emboss, Find Edges, Canvas Size, Trim.

Built in 0.11.0 (tests/test_phw10.py): Brightness/Contrast, Color Balance, Photo Filter, Selective Color, Desaturate, Dehaze, Clarity, Smart Sharpen, Frequency separation, skew, Pinch, Twirl, Polar, Mosaic.

Built in 0.12.0 (tests/test_phw11.py): Wave/Ripple, Spherize, ZigZag, Lens Correction, Crystallize, Color Halftone, Trace Contour, Diffuse, Wind, Oil Paint, Clouds, Radial spin/zoom, Surface Blur, Dodge/Burn/Sponge (tonebrush over a mask).

Built in 0.14.0 (tests/test_phw13.py): Variables, Tilt-Shift, Field Blur, Fibers, De-Interlace, NTSC Colors, Liquify twirl/pucker/bloat.

Built in 0.15.0 (tests/test_phw14.py): Iris Blur, Path Blur, Filter Gallery, Blur/Sharpen/Smudge brushes, Content-Aware Move, Export Layers/Artboards, Crop and Straighten Photos.

Built in 0.16.0 (tests/test_phw15.py): Gradient tool, gradient and pattern fill layers, Layer styles (colour/gradient overlay, inner shadow, inner/outer glow, bevel), Blend If, Replace Color, Focus Area, Eraser, Magic Eraser, Paint Bucket.

Built in 0.17.0 (tests/test_phw16.py): Content-Aware Extend, Shake Reduction (known trace), Indexed colour with dither choice, Satin style, History snapshots (`run --upto N`).

Next most valuable rung 1 builds (after 0.17.0): Vanishing Point, Artboards/Layer comps, Generator assets, Auto-Align Layers, Magnetic Lasso, Merge to HDR (Debevec), HDR Toning.
