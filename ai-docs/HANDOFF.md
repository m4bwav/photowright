# HANDOFF: photowright

Status: Step D batch 3 merged (heal, clone, fill, remove, restore in scripts/phw/retouch.py; warp, perspective, upscale, stitch, stack in scripts/phw/transform.py) on top of batches 1-2; 75 tests pass normally and with PHW_RUNG_MAX=1. Next: batch 4 (run/batch/sheet/diff, then trace/simplify/vcheck/export). Repo private m4bwav/photowright (main).

Continue prompt: [plans/photowright-continue-prompt.md](plans/photowright-continue-prompt.md)

## Mark's request (2026-11-16)

"Add photoshop like skills and vectoring a raster", then: "It should do photoshop like activities, but photoshop itself maybe optional. Mostly I want to wean it on options that are freely available without restriction and scripts/tools of its own development". Read as the tool ladder in the prompt.

## Where things are

- references/: 13 research files (feature map ~190 rows = coverage table; fundamentals rules R1-R26; rung1, rung2, layered formats, bridge, prior art, selection, retouch, upscale, transform, vectorize, vector formats).
- kb/tools.json: 103 licence rows, verified at source 2026-11-17 except imagetracerpy and Photopea terms.
- Summary of findings: last entry of [log.md](log.md).

## Waiting on Mark

- ANSWERED and closed 2026-11-17 (see log): askwright set `photowright-setup-2026-11-17`: folder [ask/photowright-setup-2026-11-17](../ask/photowright-setup-2026-11-17) (`ask.py read` it). Asks for the name, public timing, the Photoshop bridge and version, the first-job projects, and installing Potrace/Inkscape/GIMP. Carry on with the guesses in [plans/design.md](plans/design.md) section 8.

## Next

1. Step G: Szeliski 2nd ed. is free online; a reader subagent distills it (BUILD-BRIEF). The rest of ai-docs/notes/books.md are leads.
2. Step D batch 4 in a worktree: `run` (exists for single-image recipes; extend to stack/stitch recipes, which store `others` as absolute paths), `batch` (recipe over a folder, dry run first, never overwrite, second run changes nothing), `sheet`, `diff`; then `trace`, `simplify`, `vcheck`, `export`. Batch 3 notes: fill --method lama and upscale --method realesrgan are stubs naming the comfyui-gen route; stitch refuses at rung 1; seam carving left out (patent flag). OpenCV Stitcher fails on some synthetic scenes (status 1) and once asserted inside OpenCV 5.0; seamlessClone needs the region grown 3 px (a full-box mask changes almost nothing). Trace: reuse the bake-off rasterizer and pixel-exact tracer from ai-docs/notes/bakeoff/bakeoff_trace.py; run vtracer in a subprocess. GIMP 3 batch binary: %LOCALAPPDATA%/Programs/GIMP 3/bin/gimp-console-3.exe (core.gimp_console() finds it; layered.gimp_layers() lists what GIMP reads). cutout --method birefnet is a stub naming the comfyui-gen route.
3. Own region tracer with holes (bar: overlap 0.95 or more on logo and icon) before it is used as the fallback.
4. First everscout scan of image-editing (everscout-scan) when convenient.
Beat image-editing: built 2026-11-17 at Ai/indie-ai-scout/beats/image-editing (32 sources, 58 entities, 22 questions, 10 books). Owner items there: study outline approval, 4 candidate metrics, engagement (off). Not scanned yet.

## Szeliski book
The download form needs a name and an email. Mark allowed his name and email (2026-11-17) if the terms carry no legal risk, checked with lexwright. The lexwright disclaimer gate is waiting for him to type "I agree". Terms seen: personal use, no reposting.
