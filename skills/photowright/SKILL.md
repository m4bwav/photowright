---
name: photowright
description: "Photoshop-like edits on an existing image from the command line, free tools first: levels, colour, crop, resize, sharpen, background removal, heal, object removal, content-aware fill, restore, perspective, upscale, panoramas, layers, PSD, batch over a folder; and tracing raster to SVG, PDF or DXF for a laser cutter. Use on 'brighten this photo', 'remove the background', 'fix the perspective', 'open this PSD', 'vectorize my logo'. Also 'refresh photowright'. Not critique or ranking (artwright), pixel art (pixelwright), brand marks from nothing (brandwright) or new images (comfyui-gen)."
license: MIT
metadata:
  version: 0.7.0
---

# photowright

Outcome: the user's image, edited or traced, written to a new file (never over the original), with the steps kept as a recipe that replays, and a short report of which tool did each step and how it was checked.

`PHW` means `python <plugin root>/scripts/phw.py`, where the plugin root is two folders above this SKILL.md. Run it; do not read it. `PHW <command> -h` gives the flags; `--json` gives machine-readable results.

## Step 0: tools and the ladder

Run `PHW doctor` once per machine. It lists what is installed and which rung each feature uses:

1. Own code: Python, Pillow, NumPy. Always there; every feature has a rung-1 path or refuses with a reason.
2. Free, unrestricted tools: OpenCV, scikit-image, SciPy, VTracer (in a subprocess), Potrace, Inkscape, GIMP.
3. Open-weight local models (matting, upscaling) when installed.
4. Photoshop: optional, documentation only ([references/photoshop-bridge.md](../../references/photoshop-bridge.md)). Never required, never suggested as the first route.

Every result lists the rung and tool used for each step (`used`). Report it in one line ("rung 2: OpenCV GrabCut"). `--rung-max 1` (or `PHW_RUNG_MAX=1`) proves a job runs on own code alone. Never install a tool without asking; name it and its licence from [kb/tools.json](../../kb/tools.json).

## Step 1: which job

| The user wants | Commands | Read first, only if needed |
|---|---|---|
| Look: brightness, colour, crop, size, sharpness, noise | `inspect`, `adjust`, `crop`, `rotate`, `resize`, `sharpen`, `denoise`, `convert` | [image-fundamentals.md](../../references/image-fundamentals.md) (linear light, profiles, bit depth) |
| Select, mask, cut out, background removal | `select`, `mask`, `cutout` | [selection-matting.md](../../references/selection-matting.md) |
| Fix: spots, objects, red eye, scratches, old photo | `heal`, `clone`, `remove`, `fill`, `restore` | [retouch-fill.md](../../references/retouch-fill.md) |
| Geometry and merge: warp, perspective, upscale, stack, panorama | `warp`, `perspective`, `upscale`, `stack`, `stitch` | [transform-merge.md](../../references/transform-merge.md), [upscale-restore.md](../../references/upscale-restore.md) |
| Layers, PSD, ORA, blend modes, text, shadows | `layers <recipe>`, `open` | [layered-formats.md](../../references/layered-formats.md): read before building or opening a PSD |
| Many files at once | `batch` (dry run until `--apply`), `run` to replay a recipe | |
| Show the change | `sheet` (before/after), `diff` (heatmap and numbers) | |
| Raster to vector | `trace --kind logo\|icon\|line\|photo\|pixel\|centreline`, then `vcheck`, `simplify`, `export` | [vectorize.md](../../references/vectorize.md), [vector-formats.md](../../references/vector-formats.md) |
| "Can photowright do X like Photoshop?" | `explain <term>` | [photoshop-feature-map.md](../../references/photoshop-feature-map.md) |

## Step 2: edit

1. `PHW inspect <file>` first: size, mode, ICC profile, bit depth, alpha, orientation, layers.
2. Run the command with `-o <new file>` and `--recipe <name>.json` when the user may want it again. Outputs are never overwritten; a taken name becomes `name-NNN`.
3. Edits work in linear light with the profile carried through. JPEG has no alpha: a cutout goes to PNG, WebP or TIFF.
   Tone and merge options (0.7.0): `adjust --levels/--curves/--equalize` act on luminance by default (`--on channels` for the old per-channel look); `adjust --equalize [0..1] --tiles N` is local equalisation without block seams; `denoise --method bilateral` keeps edges and colours (Lab); `warp` and `perspective` prefilter where they shrink more than 2x (`--no-prefilter` to skip); a layer with `"pyramid": true` pastes multiband (no step when exposures differ); `stack --mode median` makes a clean plate. Fill routing: thin scratches `--method membrane`/`telea`, texture `patch`, big semantic holes `--model lama`. Stitch is flat (fine under about 90 degrees of view); wider panoramas need cylindrical or spherical projection (Hugin).
   Rung 3 (local models through the ComfyUI at PHW_COMFY_URL, default 127.0.0.1:8199): `cutout --model birefnet`, `fill`/`remove --model lama`, `fill --model qwen-edit --prompt "what goes there"` (Qwen-Image-Edit-2511 inside the mask; refuses a busy queue), `select --text "the dog"`. Cutout and fill fall back to rung 1/2 and say "fell back: <reason>"; select by text has no fallback.
4. Show the result: `PHW sheet before after -o sheet.png` and look at it yourself before saying it is done; `PHW diff` when the change should be local (a heal must not touch the rest).
5. For a folder: `PHW batch <recipe> <folder> --out <out folder>` prints the plan; run again with `--apply` only after the dry run looks right.

## Step 3: trace to vectors

1. Pick the kind: `logo` and `icon` for flat colour, `line` for ink and scans, `photo` for many colours, `pixel` for hard pixel edges, `centreline` for single-stroke lines (engraving, plotters).
2. `PHW trace <image> --kind <kind> -o <file>.svg` checks itself: render-back overlap against the source, node, path and colour budgets, open paths and self-intersections. A failed bar is reported, never hidden. `--backend own` forces own code; VTracer always runs in a subprocess and a crash falls back to the own tracer.
3. Too many nodes: `PHW simplify`. Then `PHW vcheck <svg> --source <image>` again.
4. Export: `PHW export <svg> --format svg|pdf|eps|dxf`. For a cutter (DXF, units, size) read [vector-formats.md](../../references/vector-formats.md) first.

## Scope edges

- Judging, ranking or critiquing an image, or "which is better": artwright. Photowright can make the sheet that artwright judges.
- Pixel art, sprites, grid snapping, palettes: pixelwright (and artwright-pixel to measure). A `--kind pixel` trace of existing pixel art is fine here.
- A logo or brand mark from nothing, brand palettes: brandwright. Tracing an existing logo is here.
- A new image from a prompt, inpainting with a diffusion model: comfyui-gen. Removing an object with content-aware fill is here.
- 3D models: polywright. Video: cinewright.

## Maintenance

Evergreen unit: state in [evergreen.json](../../evergreen.json), protocol in [MAINTENANCE.md](../../MAINTENANCE.md). Research: [RESEARCH.md](../../RESEARCH.md). Changes: [CHANGELOG.md](../../CHANGELOG.md). Lessons: [LEARNINGS.md](../../LEARNINGS.md). Tests: [TESTS.md](../../TESTS.md) and [evals/evals.json](../../evals/evals.json). On 'refresh photowright', run the evergreen-refresh skill on this unit.
