# Vectorizing (raster to vector tracing)

Checked 2026-11-16. Every claim carries its source. "Unverified" marks what was not read from source today.

## How tracing works

- **Region (area) tracing**: segment the image into regions of one colour, trace each region's outline, fill it. Potrace, VTracer, ImageTracer and Inkscape Trace Bitmap work this way. Good for logos, cut files, flat art. Sources: https://potrace.sourceforge.net/potrace.pdf ; https://www.visioncortex.org/vtracer-docs
- **Edge / centreline tracing**: find the stroke's skeleton (thinning) and emit open paths, for line art, handwriting, pen plotters and single-line engraving. AutoTrace `--centerline` does this. Source: https://github.com/autotrace/autotrace
- **Potrace's algorithm** (Selinger 2003, https://potrace.sourceforge.net/potrace.pdf):
  1. *Path decomposition*: walk the boundary between black and white pixels on the pixel-corner lattice, giving closed paths; a turn policy settles ambiguous diagonals; `turdsize` drops specks.
  2. *Optimal polygon*: among polygons whose edges stay within tolerance of the path ("straight" subpaths), find the one with fewest segments, then the minimum-penalty one (dynamic programming).
  3. *Vertex adjustment and corner detection*: each vertex moves within its unit square; `alphamax` (default 1) decides smooth curve vs sharp corner.
  4. *Bezier fitting*: each smooth vertex becomes a cubic Bezier; optional `opticurve` joins neighbouring curves within `opttolerance`.
- **Colour layering**: *stacked* paints larger shapes under smaller ones (no seam gaps, but overlaps: a cutter would cut every layer fully); *cutout* makes non-overlapping shapes with holes (right for vinyl layers, risk of hairline gaps). VTracer: `--hierarchical stacked|cutout`. Source: https://github.com/visioncortex/vtracer

## Open tracers (licences read from source 2026-11-16)

| Tool | Licence | Strengths | Source |
|---|---|---|---|
| Potrace 1.16 | GPL-2.0+ (commercial licence sold separately) | best smooth curves for one-colour art; SVG/PDF/EPS/DXF out | https://potrace.sourceforge.net/ |
| VTracer 0.6.x | **MIT** (LICENSE file read; GitHub API spdx MIT) | colour images, stacked/cutout, spline/polygon/pixel modes, fast Rust; `pip install vtracer` wheel 0.84 MB (0.6.15 win_amd64 cp314, measured) | https://github.com/visioncortex/vtracer |
| AutoTrace | programs GPL-2.0, `libautotrace` LGPL-2.1+ (README read) | centreline mode, colour, DXF/EPS/SVG out | https://github.com/autotrace/autotrace |
| ImageTracer.js | Unlicense / public domain (LICENSE read) | simple readable algorithm with built-in quantization; free to port | https://github.com/jankovicsandras/imagetracerjs |
| imagetracerpy | public domain per author (no licence file found by GitHub API; unverified) | pure Python port; slow | https://github.com/jankovicsandras/imagetracerpy |
| Inkscape Trace Bitmap | GPL-2.0+ | Potrace inside, multiscan colour, Pixel art tab (libdepixelize) | https://inkscape.org/doc/tutorials/tracing/tutorial-tracing.html |
| Kopf-Lischinski "Depixelizing Pixel Art" (SIGGRAPH 2011) | paper; libdepixelize in Inkscape (licence unverified) | smooth vectors from sprites | https://johanneskopf.de/publications/pixelart/ |
| Pixel-exact square tracer | own code (rung 1) | lossless, axis-aligned polygons per colour | design below |

Centreline alternative at rung 1-2: scikit-image `skeletonize` (BSD-3) then chain pixels into polylines and simplify. https://scikit-image.org/docs/stable/auto_examples/edges/plot_skeleton.html

## AI vectorizers (rung 3)

| Model | Code | Weights | Notes | Source |
|---|---|---|---|---|
| StarVector 1B / 8B | Apache-2.0 | Apache-2.0 (HF tag) | image-to-SVG code LLM; icons, diagrams; not photos | https://github.com/joanrod/star-vector ; https://huggingface.co/starvector/starvector-8b-im2svg |
| OmniSVG | Apache-2.0 | Apache-2.0 (HF tag); built on Qwen2.5-VL, check base terms | text/image to SVG | https://github.com/OmniSVG/OmniSVG ; https://huggingface.co/OmniSVG/OmniSVG |
| LIVE | Apache-2.0 | none: per-image optimization through DiffVG | slow, few clean layers | https://github.com/ma-xu/LIVE |
| DiffVG | Apache-2.0 | n/a, differentiable rasterizer | base of LIVE, VectorFusion, SVGDreamer; C++/CUDA build | https://github.com/BachiLi/diffvg |

Verdict: classic tracers win for cutter and laser files; AI is for "redraw as a clean icon".

## Colour quantization before tracing

- Median cut (Heckbert 1982): split the colour box on its longest axis at the median. Pillow `quantize(method=MEDIANCUT)`, also `MAXCOVERAGE`, `FASTOCTREE`, `LIBIMAGEQUANT`. https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.quantize
- Wu (1991, Graphics Gems II) variance-minimising quantizer: better than median cut, ~200 lines with NumPy cumulative moments.
- k-means in NumPy: best quality, slower; seed from median cut.
- Before tracing: median filter or blur to remove anti-alias fringe colours; after: merge regions under a minimum area (VTracer `filter_speckle`).

## Path simplification

- Ramer-Douglas-Peucker: split at the farthest point beyond epsilon. https://en.wikipedia.org/wiki/Ramer%E2%80%93Douglas%E2%80%93Peucker_algorithm
- Visvalingam-Whyatt: repeatedly drop the point with smallest triangle area; smoother results. https://en.wikipedia.org/wiki/Visvalingam%E2%80%93Whyatt_algorithm
- Schneider, "An Algorithm for Automatically Fitting Digitized Curves" (Graphics Gems 1990): least-squares cubic Bezier, split at max error, Newton reparameterization. Reference C: https://github.com/erich666/GraphicsGems/blob/master/gems/FitCurves.c

## What makes an SVG clean per target

- **Cutters (Cricut, Silhouette)**: closed filled paths, no strokes (outline them), no stacked duplicates, one colour per layer, no tiny islands, real units in width/height. https://help.cricut.com/hc/en-us/articles/360009556313 ; https://www.silhouetteamerica.com/
- **Laser (LightBurn)**: colour maps to layer; closed shapes for fill/engrave, lines for cut/score; no duplicate overlapping paths (double burns); real units. https://docs.lightburnsoftware.com/
- **Font glyph**: one compound path, outer contours and holes in opposite winding (TrueType: outer clockwise), no overlaps, points at extremes. https://learn.microsoft.com/en-us/typography/opentype/spec/glyf
- **3D extrude (Blender)**: closed, non-self-intersecting paths; holes as subpaths; Blender fills nested curves. https://docs.blender.org/manual/en/latest/files/import_export/svg.html

## Own tracer feasibility (rung 1)

- **Pixel-exact tracer: easy, high value.** Label pixels by colour; boundary edges come from NumPy differences along rows and columns; chain edges into closed loops on the corner lattice (outer and hole loops), merge collinear runs. Lossless, cutter- and pixel-art-safe. About 150-250 lines; this lattice walk is also Potrace's step 1.
- **Potrace-like smooth tracer: feasible, medium.** Lattice path + RDP or Visvalingam + corner-angle rule + Schneider fit is about 400-600 lines and good enough for logos. The full optimal-polygon DP with alphamax and opticurve is 1,000+ lines and must be written clean-room from the paper (reading Potrace's GPL source would taint the code). Potrace itself stays rung 2, called as a subprocess, never bundled.
- **Default colour tracer: VTracer (MIT)**, sub-1 MB wheel, safe to depend on or bundle.

## Installed here (checked 2026-11-16, Windows)

potrace: no. vtracer CLI: no; `import vtracer`: no (wheel downloadable). autotrace: no. inkscape: no (not on PATH).
Update 2026-11-17: vtracer 0.6.15 pip-installed; Inkscape 1.4.4 at C:/Program Files/Inkscape/bin/inkscape.com (not on PATH); its CLI action `object-trace:{scans},{smooth},{stack},{remove_background},{speckles},{smooth_corners},{optimize}` traces from the command line (phw trace --backend inkscape). Measured results of the built tracers: ai-docs/log.md, 2026-11-17 batch 4.
