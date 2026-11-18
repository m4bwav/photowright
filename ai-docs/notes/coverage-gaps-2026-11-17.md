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
| Brightness/Contrast | 1 | gap (levels/curves can emulate) | `adjust` |
| Vibrance | 1 | gap | `adjust` |
| Color Balance | 1 | gap | `adjust` |
| Photo Filter | 1 | gap | `color` |
| Selective Color | 1 | gap | `color` |
| Shadows/Highlights | 1 | gap | `adjust` |
| HDR Toning | 2 | gap | `adjust` |
| Desaturate | 1 | partial (`adjust --bw` luminance; no (max+min)/2 mode) | `adjust` |
| Match Color / Color Transfer | 1 | gap (Reinhard Lab statistics) | `color --match` |
| Replace Color | 1 | partial (`select` colour range + `adjust --hue --mask`; no single command) | `color` |
| Auto Tone / Contrast / Color | 1 | gap | `adjust --auto` |
| Camera Raw basic panel | 2 | gap | none planned |
| Dehaze | 1 | gap (dark channel prior) | `adjust` |
| Clarity / Texture | 1 | gap | `adjust` |
| Indexed colour / palette for web | 1 | partial (convert palette, trace quantise; no dither choice) | `convert` |
| Blend If | 1 | gap | `layers` |
| Gradient tool, fill layers (gradient, pattern) | 1 | gap | `layers` |
| Inner Shadow, Outer/Inner Glow, Bevel, Satin, overlays | 1 | gap | `layers` |
| Smart Objects / Smart Filters / linked | 1 | partial (layered recipe re-renders) | `layers` |
| Artboards, Layer comps | 1 | gap | `layers` |
| Auto-Blend Layers | 2 | partial (stack focus mode) | `stack` |
| Auto-Align Layers | 2 | gap | `stack --align` |
| Merge to HDR Pro | 2 | gap (exposure fusion only) | `stack` |
| Apply Image / Calculations | 1 | gap | `layers` |
| Spot channels | 2 | gap | `save` |
| Magnetic Lasso | 2 | gap | `select` |
| Focus Area | 1 | gap (focus stack has the measure) | `select --focus` |
| Quick Selection | 2 | partial (GrabCut in cutout) | `select` |
| Spot Healing Brush | 2 | partial (`heal`) | `heal` |
| Content-Aware Move / Extend | 2 | gap | `fill` |
| Dodge / Burn / Sponge | 1 | gap | `adjust --mask` route |
| Blur / Sharpen / Smudge brushes, brush engine | 1 | gap (no strokes) | new `paint` |
| Eraser / Magic Eraser / Paint Bucket | 1 | partial (cutout colour key, flood select) | `mask`/`select` |
| Liquify | 1 | gap | `warp` |
| Frequency separation | 1 | gap | `filter` |
| Radial, Lens, Surface, Shape blur; Blur Gallery | 1 | gap (denoise bilateral is close to Surface Blur) | `filter` |
| Smart Sharpen | 1 | gap | `sharpen` |
| Shake Reduction | 2 | gap | `sharpen` |
| Add Noise | 1 | gap | `filter` |
| Emboss, Find Edges, Trace Contour | 1 | gap (Sobel exists in masks) | `filter` |
| Diffuse, Wind, Extrude, Tiles; Oil Paint; Pixelate family | 1 | gap | `filter` |
| Distort family (Pinch, Twirl, Polar ...) | 1 | gap | `warp` |
| Adaptive Wide Angle | 2 | gap | `perspective` |
| Lens Correction | 1 | gap | `perspective` |
| Vanishing Point | 1 | gap | `clone` |
| Clouds / Fibers, Lens Flare / Lighting | 1 | gap | `filter` |
| Filter Gallery | 1 | gap | `filter` |
| Custom kernel, De-Interlace, NTSC Colors | 1 | gap | `filter` |
| Content Credentials (C2PA) | 2 | gap | `convert` |
| Canvas Size, Trim / Reveal All | 1 | gap (crop only) | `crop` |
| Free Transform (skew) | 1 | gap | `perspective` |
| Crop and Straighten Photos | 1 | partial (stitch --mode scans) | `stitch` |
| Lens profile correction | 2 | gap | `perspective` |
| Make Work Path from selection | 2 | partial (trace of a mask) | `trace` |
| Variables (data-driven graphics) | 1 | gap | `batch` |
| Export layers / artboards; Generator assets | 1 | partial (`open` extract) | `open` |
| History / Snapshots | 1 | partial (recipes + log) | `run` |
| Layered TIFF, AVIF/HEIC/JXL, camera raw, PDF/EPS open, video layers | 2 | gap | `open`/`convert` |

Next most valuable rung 1 builds: Auto Tone/Contrast/Color, Vibrance, Shadows/Highlights, Match Color (Reinhard), Add Noise, Emboss/Find Edges, Canvas Size/Trim.
