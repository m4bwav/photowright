# Changelog: photowright

Every change to [skills/photowright/SKILL.md](skills/photowright/SKILL.md) and its companions, newest first, each with the reason. Reasons cite lessons in [LEARNINGS.md](LEARNINGS.md) (`L-`) and test runs in [TESTS.md](TESTS.md) (`T-`).

Entry shape: `### C-YYYYMMDD-n · date · one-line summary`, then `because:`, `files:`, and a sentence on what changed.

## Unreleased

### C-20261118-21 · 2026-11-18 · 0.25.0: decompose an image into RGBA layers (Qwen-Image-Layered, rung 3)
because: references/comfyui-nodes.md listed Qwen-Image-Layered (core, Apache-2.0) as installed on 8199 but not wired.
files: scripts/phw/comfy.py, scripts/phw/layered.py, scripts/phw/core.py, tests/test_phw22.py, skills/photowright/SKILL.md, references/comfyui-nodes.md, .claude-plugin/plugin.json
New `decompose IMG --layers N -o out.psd|out.ora|folder [--png DIR] [--prompt "caption"] [--seed N] [--steps 20]`: core Qwen-Image-Layered after the blueprint "Image to Layers (Qwen-Image-Layered)" at about 640x640 (multiples of 16), layers resized back with Lanczos, bottom first; reports alpha coverage per layer and the recomposite PSNR. Refuses a busy queue; falls back (and `--method colour` runs) to an own k-means colour split that flattens back exactly. Live on 8199: 3 layers in 177 s, recomposite 36.3 dB (ai-docs/notes/bakeoff/layered-live-2026-11-18.md).

### C-20261118-20 · 2026-11-18 · 0.24.0: relight --keep-detail (source detail over IC-Light's lighting)
because: the first live relight run (ai-docs/notes/bakeoff/relight-live-2026-11-18.md) showed IC-Light repaints the whole frame (high-pass correlation with the source 0.46; the car and tail emblem vanished).
files: scripts/phw/transform.py, tests/test_comfy.py, skills/photowright/SKILL.md, scripts/phw/core.py, .claude-plugin/plugin.json
New `relight --keep-detail SIGMA`: Gaussian lows of the relit frame plus the source's highs above SIGMA px; `invented_detail` is false when set. Live on 8199 with sigma 4: high-pass correlation 0.965 (was 0.455), same colour shift. A faint halo can show along hard edges where the lighting changes sharply.

### C-20261118-19 · 2026-11-18 · 0.23.0: relight by prompt and direction (IC-Light + Depth Anything V2 Small, rung 3)
because: references/comfyui-nodes.md listed IC-Light and controlnet_aux DA-V2 Small as installed on 8199 but not wired.
files: scripts/phw/comfy.py, scripts/phw/transform.py, scripts/phw/core.py, tests/test_comfy.py, skills/photowright/SKILL.md, references/comfyui-nodes.md, .claude-plugin/plugin.json
New `relight IMG --prompt "..." --light left|right|top|bottom|none [--seed N]`: kijai IC-Light v1 fc (`LoadAndApplyICLightUnet` + `ICLightConditioning`, iclight_sd15_fc on SD1.5 v1-5-pruned-emaonly) sampled from a direction gradient multiplied by the Depth Anything V2 Small depth (`DepthAnythingV2Preprocessor`, vits only for the licence), at about 0.33 MP in multiples of 64, resized back with Lanczos, alpha kept, `invented_detail` set. Refuses a busy queue like qwen-edit; falls back (and `--method own` runs) to an own directional gain ramp in linear light. Input names checked on /object_info 2026-11-18; no live render yet (GPU busy).

### C-20261118-18 · 2026-11-18 · 0.22.0: Inkscape manual lessons for trace, simplify, vcheck and export
because: ai-docs/notes/inkscape-manual.md (session 35) listed build candidates 1-7, 9 and 12 as open.
files: scripts/phw/vtrace.py, scripts/phw/vector.py, scripts/phw/core.py, tests/test_phw21.py, skills/photowright/SKILL.md, .claude-plugin/plugin.json, ai-docs/notes/inkscape-manual.md
`trace` gains `--speckle A` (drop closed loops under A px^2), `--blur R` (Gaussian pre-blur for halftone screens), `--stack` (each colour also covers the ones above it), `--no-background` (drop the page layer) and `--scans N` (exactly N brightness steps with the thresholds reported; Inkscape gives N+1); the option flags force the own region tracer. The path parser converts arcs exactly to cubics (they were read as lines). `export --units mm|in` writes a viewBox in the same unit (1 user unit = 1 mm). A clip-path is reported in the notes instead of dropped silently. Already built: implicit repeats, H/V, S/T and open-path reports in the parser; simplify tolerance was already absolute (now proven by a test). Not built: clips as a boolean and text to outlines before DXF (no polygon boolean or font outliner at rung 1). tests/test_phw20.py restores PHW_RUNG_MAX and skips its rung 2 tests at rung 1 (the rung 1 suite had 8 failures from that leak).

### C-20261118-17 · 2026-11-18 · 0.21.0: PDF/EPS open, video frames (`frames`), page and frame suffixes
because: HANDOFF session 33 left PDF/EPS open and video layers as the only open coverage rows (8199 busy, so model-route checks waited again).
files: scripts/phw/docio.py, scripts/phw/core.py (sha256 strips a page suffix), scripts/phw/__init__.py, tests/test_phw20.py, skills/photowright/SKILL.md, .claude-plugin/plugin.json, ai-docs/notes/coverage-gaps-2026-11-17.md
Any command now opens `doc.pdf[2]` (pdftoppm or mutool), `art.eps` (Ghostscript) and `clip.mp4[48]` (ffmpeg) as rung 2 external programs, never bundled; `PHW_DOC_DPI` sets the render resolution; `frames VIDEO OUTDIR --every N --max K --width W` writes numbered PNG frames. Each refuses with the install hint when the program is absent or PHW_RUNG_MAX is below 2.

### C-20261118-16 · 2026-11-18 · 0.20.0: `camraw`, HEIC/JXL/camera raw read, `inspect --c2pa-verify`
because: HANDOFF session 32 named the remaining rung 2 rows next (8199 busy, so model-route checks waited again).
files: scripts/phw/rawio.py, scripts/phw/core.py (LOAD_HOOKS, inspect flag), scripts/phw/__init__.py, tests/test_phw19.py, skills/photowright/SKILL.md, .claude-plugin/plugin.json, ai-docs/notes/coverage-gaps-2026-11-17.md
`camraw` is the Camera Raw Basic panel as one recipe of the plugin's own ops in Camera Raw's order. Loading `.heic/.heif/.jxl` registers pillow-heif or pillow-jxl-plugin when present and otherwise refuses with the pip line; camera raw files (`.dng .cr2 .cr3 .nef .arw .raf .orf .rw2` ...) decode through rawpy to 16-bit sRGB. `inspect --c2pa-verify` hands the file to c2patool when it is on PATH.

### C-20261118-15 · 2026-11-18 · 0.19.0: `autoalign --model` rotation/scale/perspective, `hdrmerge --response recover`, layered TIFF, C2PA detection
because: HANDOFF session 31 named the two partial rows (Auto-Align rotation/perspective, HDR camera response) as next, then the rung 2 rows; layered TIFF and Content Credentials detection turned out doable in rung 1.
files: scripts/phw/hdr.py, scripts/phw/layered.py, scripts/phw/core.py, tests/test_phw18.py, tests/test_phw2.py, skills/photowright/SKILL.md, .claude-plugin/plugin.json, ai-docs/notes/coverage-gaps-2026-11-17.md
Auto-Align now takes --model rigid|similarity|homography (Fourier-Mellin log-polar guesses, then pyramid Gauss-Newton Lucas-Kanade; corners within 0.5 px of the true warp). Merge to HDR recovers the camera response (Debevec gsolve, per channel, saved/reused as JSON; under 5% radiance error on a cube-root camera where the sRGB guess is over 2x worse). `save x.tif` writes a layered TIFF (Photoshop tag 37724 holding PSD layer info; GIMP 3 opens the layers) and `open` reads it back. `lensprofile` corrects distortion and vignetting from a lensfun database the user points at (data never bundled; coefficients stored in the recipe). `inspect` reports Content Credentials (JPEG APP11, PNG caBX, JUMBF) with the claim generator.

### C-20261118-14 · 2026-11-18 · 0.18.0: `hdrmerge`, `hdrtone`, `autoalign`, `lasso`, `vpclone`, `widefix`, `comps`, `assets`
because: the gap note's build-next list after 0.17.0 (8199 busy, so the model-route checks waited again).
files: scripts/phw/hdr.py, scripts/phw/comps.py, scripts/phw/__init__.py, scripts/phw/core.py, tests/test_phw17.py, skills/photowright/SKILL.md, .claude-plugin/plugin.json, ai-docs/notes/coverage-gaps-2026-11-17.md.
Merge to HDR (Debevec radiance from brackets with known times, Reinhard or linear output, optional .npy radiance), HDR Toning (Reinhard with a log-detail boost), Auto-Align Layers (translation by phase correlation), Magnetic Lasso (intelligent scissors to a mask) Vanishing Point clone (homography between quads), Adaptive Wide Angle (fisheye to rectilinear, four lens models), Layer Comps (named visibility/opacity/position overrides, one PNG each) and Generator image assets (layers named like files, with % or WxH sizes), each with a numeric proof in tests/test_phw17.py.

### C-20261118-13 · 2026-11-18 · 0.17.0: `caextend`, `shake`, `indexed`, `layerstyle --satin`; live ComfyUI tests never hang
because: the gap note's build-next list after 0.16.0, and the full suite hung in tests/test_comfy.py while another session's render held 8199.
files: scripts/phw/extend.py, scripts/phw/fills.py, scripts/phw/core.py (run --upto), scripts/phw/__init__.py, scripts/phw/core.py, tests/test_phw16.py, tests/test_comfy.py, skills/photowright/SKILL.md, .claude-plugin/plugin.json.
Content-Aware Extend (copy + Poisson blend), Shake Reduction for a known straight trace (Richardson-Lucy), Indexed Color with a dither choice (none, Floyd-Steinberg, ordered Bayer, seeded noise; auto, web, grey, .hex/.gpl palettes) the Satin layer style and History snapshots (`run --upto N`), each with a numeric proof in tests/test_phw16.py. The live ComfyUI tests now skip when the queue is busy or the server takes over 3 s to answer, and cap each wait at PHW_COMFY_TEST_WAIT (240 s).

### C-20261118-12 · 2026-11-18 · 0.16.0: `gradient`, `pattern`, fill layers, `layerstyle`, `blendif`, `replacecolor`, `focusarea`, `erase`, `bucket`
because: the gap note's build-next list after 0.15.0 (ai-docs/notes/coverage-gaps-2026-11-17.md), rung 1 rows.
files: scripts/phw/fills.py, scripts/phw/compose.py, scripts/phw/__init__.py, scripts/phw/core.py, tests/test_phw15.py, skills/photowright/SKILL.md, .claude-plugin/plugin.json.
Gradient tool and gradient/pattern fill layers, layer styles (overlays, inner shadow, inner/outer glow, bevel), Blend If, Replace Color as one command, Focus Area select, Eraser, Magic Eraser and Paint Bucket, NumPy and Pillow only, each with a numeric proof in tests/test_phw15.py.

### C-20261118-11 · 2026-11-18 · 0.15.0: `blurgallery --iris/--path`, `filtergallery`, `paint`, `camove`, `export-layers`, `cropstraighten`
because: the gap note's build-next list after 0.14.0 (ai-docs/notes/coverage-gaps-2026-11-17.md), rung 1 rows.
files: scripts/phw/gallery.py, scripts/phw/toolbox.py, scripts/phw/__init__.py, scripts/phw/core.py, tests/test_phw14.py, skills/photowright/SKILL.md, .claude-plugin/plugin.json.
Iris and Path Blur, Filter Gallery (chain of phw edit commands with a preview sheet), Blur/Sharpen/Smudge brushes along strokes, Content-Aware Move, Export Layers/Artboards to Files and Crop and Straighten Photos, NumPy and Pillow only, each with a numeric proof in tests/test_phw14.py.

### C-20261118-10 · 2026-11-18 · 0.14.0: `variables`, `blurgallery`, `fibers`, `deinterlace`, `ntsc`, `liquify --mode twirl|pucker|bloat`
because: the gap note's build-next list (ai-docs/notes/coverage-gaps-2026-11-17.md), rung 1 rows.
files: scripts/phw/datamerge.py, scripts/phw/gallery.py, scripts/phw/kernels.py, scripts/phw/__init__.py, tests/test_phw13.py, skills/photowright/SKILL.md, scripts/phw/core.py, .claude-plugin/plugin.json.
Variables (CSV data sets over a layers recipe, manifest-skipped reruns, bad rows reported), Tilt-Shift and Field Blur, Fibers, De-Interlace, NTSC Colors and the Twirl/Pucker/Bloat liquify brushes, NumPy only, each with a numeric proof in tests/test_phw13.py.

### C-20261118-9 · 2026-11-18 · 0.13.0: `apply-image`, `fx`, `lensblur`, `liquify`, `filter --kernel`, `canvas --reveal-all`
because: the gap note's build-next list (ai-docs/notes/coverage-gaps-2026-11-17.md); 8199 busy again, so rung 1 rows instead of the model measurements.
files: scripts/phw/kernels.py, scripts/phw/filters.py, scripts/phw/tonal.py, scripts/phw/__init__.py, tests/test_phw12.py, skills/photowright/SKILL.md, scripts/phw/core.py, .claude-plugin/plugin.json.
Twelve rung 1 rows (Custom kernel, Reveal All, Apply Image/Calculations, Texture, Pointillize, Extrude, Tiles, Lens Blur, Shape Blur, Lens Flare, Lighting Effects, Liquify push), NumPy only, each with a numeric proof in tests/test_phw12.py.

### C-20261118-8 · 2026-11-18 · 0.12.0: `warpfx`, `stylize`, `blurfx`, `tonebrush` commands
because: the gap note's build-next list (ai-docs/notes/coverage-gaps-2026-11-17.md); 8199 busy again, so rung 1 rows instead of the model measurements.
files: scripts/phw/stylize.py, scripts/phw/__init__.py, tests/test_phw11.py, skills/photowright/SKILL.md, scripts/phw/core.py, .claude-plugin/plugin.json.
Seventeen rung 1 rows (Wave, Ripple, Spherize, ZigZag, Lens Correction, Crystallize, Color Halftone, Trace Contour, Diffuse, Wind, Oil Paint, Clouds, Radial spin, Radial zoom, Surface Blur, Dodge/Burn, Sponge), NumPy only, each with a numeric proof in tests/test_phw11.py.

### C-20261118-7 · 2026-11-18 · 0.11.0: `grade`, `detail`, `distort`, `pixelate` commands and a module-shadowing guard
because: the gap note's build-next list (ai-docs/notes/coverage-gaps-2026-11-17.md), and session 24's trap (a module named like a core function was silently replaced by it).
files: scripts/phw/grading.py, scripts/phw/__init__.py, tests/test_phw10.py, skills/photowright/SKILL.md, scripts/phw/core.py, .claude-plugin/plugin.json.
Fourteen rung 1 rows (Brightness/Contrast, Color Balance, Photo Filter, Selective Color, Desaturate, Dehaze, Clarity, Smart Sharpen, Frequency separation, Pinch, Twirl, Polar, Skew, Mosaic), NumPy only, each with a numeric proof; ModuleShadowing test fails if a module in scripts/phw shares a name with a public core attribute.

### C-20261118-6 · 2026-11-18 · 0.10.0: `tone`, `effect` and `canvas` commands for the next rung 1 gaps
because: the coverage gap note's build-next list (ai-docs/notes/coverage-gaps-2026-11-17.md): Auto Tone/Contrast/Color, Vibrance, Shadows/Highlights, Match Color, Add Noise, Emboss, Find Edges, Canvas Size, Trim.
files: scripts/phw/tonal.py, scripts/phw/__init__.py, tests/test_phw9.py, skills/photowright/SKILL.md, scripts/phw/core.py, .claude-plugin/plugin.json.
NumPy only; Match Color stores the reference's Lab statistics in the step so a replay needs no reference file. Module is `tonal.py` because `core.tone` already exists and `from . import tone` silently returned that function. Proofs in tests/test_phw9.py.

### C-20261118-5 · 2026-11-18 · 0.9.0: `filter` and `color` commands for rung 1 gaps in the coverage table
because: coverage sweep (ai-docs/notes/coverage-gaps-2026-11-17.md) found Gaussian/Box/Motion Blur, High Pass, Maximum/Minimum, Offset, Invert, Posterize, Threshold, Solarize, Channel Mixer and Gradient Map rows (all rung 1) unbuilt.
files: scripts/phw/filters.py, scripts/phw/__init__.py, tests/test_phw8.py, scripts/phw/core.py, .claude-plugin/plugin.json.
New `filter` (blur gaussian|box|motion, --high-pass, --maximum, --minimum, --offset) and `color` (--invert, --posterize, --threshold, --solarize, --mixer, --gradient-map) commands, NumPy only, encoded values, --mask and --recipe like every op; proofs in tests/test_phw8.py.

### C-20261117-3 · 2026-11-17 · opt-in VTracer 1.x CLI backend after a measured photo win
because: bake-off (ai-docs/notes/bakeoff/vtracer1-2026-11-17.md): VTracer 1.0.0-alpha.4 `--preset poster` scores 0.884 vs 0.840 overlap on the photo, in budget; default 1.0 output equals 0.6.15.
files: scripts/phw/vtrace.py, tests/test_phw4.py, kb/tools.json, references/vectorize.md.
`trace --backend vtracer1` runs the 1.x CLI found via PHW_VTRACER or PATH (photo with --preset poster) and falls back to the own tracer with a note; auto stays on 0.6.15 while 1.0 is alpha.

### C-20261117-9 · 2026-11-17 · 0.8.0: bridge to free editors (GIMP run and compare, Krita, Photopea/Photoshop scripts)
because: Mark's ruling (bridge last, free editors, Photoshop documentation only); measured GIMP 3 reading ORA layers in linear light (mean 8.9, max 60 of 255 off).
files: scripts/phw/bridge.py, tests/test_phw7.py, skills/photowright/SKILL.md.
New `bridge` command; GIMP script forces the blend space so its flatten matches phw within 0.4/255 for ORA and PSD in both spaces.

### C-20261118-4 · 2026-11-18 · 0.7.2: stack/stitch recipes replay after the job folder moves
- because: HANDOFF batch 4 note "`run` was not extended to stack/stitch recipes (they store `others` as absolute paths ... untested)"; design.md says a recipe folder replays to the same pixels
- files: scripts/phw/core.py, scripts/phw/transform.py, tests/test_phw6.py, .claude-plugin/plugin.json
- With `--recipe`, stack and stitch now store the other inputs relative to the recipe folder plus `others_sha256`; `apply_steps` resolves relative `others` against the recipe folder; `run` adds a note naming any other input that is missing or changed. Old recipes with absolute paths still replay. Test: stack recipe copied to a new folder replays bit-identical; changing one input names it in the notes.

### C-20261118-3 · 2026-11-18 · 0.7.1: fill --model qwen-edit --prompt (rung 3, Qwen-Image-Edit-2511)
- because: HANDOFF next item "wire fill by instruction (Qwen-Image-Edit-2511)"; weights, Lightning LoRA, text encoder and VAE are on the 8199 server, core nodes (Apache-2.0, references/comfyui-nodes.md)
- files: scripts/phw/comfy.py, scripts/phw/retouch.py, tests/test_comfy.py, skills/photowright/SKILL.md, references/comfyui-nodes.md, references/retouch-fill.md, .claude-plugin/plugin.json, scripts/phw/core.py
- `phw fill|remove --model qwen-edit --prompt "..." [--seed N]` builds the core 2511 graph (Lightning 4 steps, SetLatentNoiseMask), resizes the result back and composites through the mask, so outside pixels are the source's bit for bit. The step records rung 3, model, LoRA, seed, prompt and invented_detail: true. Server down, rung hidden, node or model missing, or any job already queued (`PHW_COMFY_MAX_AHEAD`, default 0): falls back to the rung 1/2 fill with a `fell back:` note. Chose a `--model` value on `fill` over a new `edit --instruction` command: it reuses region flags, the mask composite and the fallback path. Offline tests only; live run not measured (8199 busy with an H3 render).

### C-20261118-2 · 2026-11-18 · upscale --method seedvr2 (rung 3, ComfyUI core SeedVR2)
- because: HANDOFF next item "wire remaining rung 3 routes"; SeedVR2 3B/7B int8 weights and the core SeedVR2 nodes are on the 8199 server (Apache-2.0 code and weights, references/comfyui-nodes.md)
- files: scripts/phw/comfy.py, scripts/phw/transform.py, tests/test_comfy.py
- `phw upscale --method seedvr2 [--size 3b|7b] [--seed N]` runs one still through the core blueprint's graph (Lanczos to size, SeedVR2Preprocess, tiled VAE, one KSampler step, PostProcessing lab colour fix). The step records model, seed and invented_detail: true and notes to check text and faces; alpha stays Lanczos. Server down or rung hidden: falls back to Lanczos with a `fell back:` note. Offline tests mock the server; the live run is not yet measured (server was busy with a long render).

### C-20261118-1 · 2026-11-17 · worth follow-ups: separating action case, shorter description, DXF/PSD detail on demand
- because: evergreen-worth lite run (ai-docs/log.md 2026-11-17); T-20261117-3; L-20261118-1
- files: evals/evals.json, evals/check.py, evals/run.py, skills/photowright/SKILL.md, references/layered-formats.md, references/vector-formats.md
- action-trace-logo (passed without the skill) is replaced by action-layered-psd: a 2-layer PSD with names, Multiply and 70% opacity plus a layers recipe that `phw run` rebuilds. The description is about 150 tokens with the same neighbour exclusions. The `phw layers` recipe shape and the DXF `--units mm --dpi` sizing moved into "Using phw" sections of the two references. run.py hides check.py from the model until the evidence step.

### C-20261117-3 · 2026-11-17 · 0.7.0: Szeliski proposals built
- because: ai-docs/notes/szeliski.md proposals 1-10; tests/test_phw6.py
- files: scripts/phw/core.py, scripts/phw/transform.py, scripts/phw/compose.py, tests/test_phw6.py, tests/test_phw.py, skills/photowright/SKILL.md, references/image-fundamentals.md, references/retouch-fill.md, references/transform-merge.md
- levels, curves and the new equalize act on luminance by default (`--on channels` keeps the old look; recipes without `on` replay per channel); `--equalize S --tiles N` with interpolated tile curves; `denoise --method bilateral` (Lab Delta E, rung 1); warp and perspective prefilter by mip-mapping where they shrink >2x (zone plate 4x: RMS 0.077 against 0.373 unfiltered); layer `"pyramid": true` multiband paste; `stack --mode median`; upscale records `invented_detail`. Docs: Pillow bicubic a = -0.5, fill routing, stitch projection limit.

### C-20261117-2 · 2026-11-17 · 0.6.0: rung 3 routes through the local ComfyUI
- because: HANDOFF Next item 0 (wire rung 3 to the installed nodes)
- files: scripts/phw/comfy.py (new), scripts/phw/masks.py, scripts/phw/retouch.py, tests/test_comfy.py, skills/photowright/SKILL.md, references/comfyui-nodes.md
- `cutout --model birefnet` (core RemoveBackground), `fill`/`remove --model lama` (Acly inpaint nodes, big-lama) and `select --text` (Florence-2-large boxes into SAM 2.1 base_plus) run through ComfyUI over stdlib HTTP, record model and seed in the recipe step, paste back through the mask, and fall back to rung 1/2 with "fell back: <reason>". `--model` is an alias of `--method`.

### C-20261117-1 · 2026-11-17 · 0.5.0: plugin, hub skill, evals, README, SECURITY
- because: Step F of the continue prompt; T-20261117-1
- files: .claude-plugin/, skills/photowright/SKILL.md, evals/, README.md, SECURITY.md, LICENSE, evergreen companions, scripts/phw/core.py
- One hub skill (no siblings: the trigger evals did not show it losing prompts), an eval suite with decoys for artwright, pixelwright, brandwright and comfyui-gen, and a no-skill baseline. phw 0.5.0: raster saves now create the output's parent folder (an `-o out/x.jpg` into a missing folder crashed).
