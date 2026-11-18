# Changelog: photowright

Every change to [skills/photowright/SKILL.md](skills/photowright/SKILL.md) and its companions, newest first, each with the reason. Reasons cite lessons in [LEARNINGS.md](LEARNINGS.md) (`L-`) and test runs in [TESTS.md](TESTS.md) (`T-`).

Entry shape: `### C-YYYYMMDD-n · date · one-line summary`, then `because:`, `files:`, and a sentence on what changed.

## Unreleased

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
