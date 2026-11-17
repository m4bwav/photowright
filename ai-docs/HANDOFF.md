# HANDOFF: photowright

Status: Steps A-C done (2026-11-17), apart from the beat report; Step D (build phw.py) next. Repo private m4bwav/photowright (main).

Continue prompt: [plans/photowright-continue-prompt.md](plans/photowright-continue-prompt.md)

## Mark's request (2026-11-16)

"Add photoshop like skills and vectoring a raster", then: "It should do photoshop like activities, but photoshop itself maybe optional. Mostly I want to wean it on options that are freely available without restriction and scripts/tools of its own development". Read as the tool ladder in the prompt.

## Where things are

- references/: 13 research files (feature map ~190 rows = coverage table; fundamentals rules R1-R26; rung1, rung2, layered formats, bridge, prior art, selection, retouch, upscale, transform, vectorize, vector formats).
- kb/tools.json: 103 licence rows, verified at source 2026-11-17 except imagetracerpy and Photopea terms.
- Summary of findings: last entry of [log.md](log.md).

## Waiting on Mark

- Askwright set `photowright-setup-2026-11-17`: folder [ask/photowright-setup-2026-11-17](../ask/photowright-setup-2026-11-17) (`ask.py read` it). Asks for the name, public timing, the Photoshop bridge and version, the first-job projects, and installing Potrace/Inkscape/GIMP. Carry on with the guesses in [plans/design.md](plans/design.md) section 8.

## Next

1. If the beat line below says pending, check that `~/.everscout` has the image-editing beat; if it does not, rerun everscout-beat.
2. Step D in a worktree: scripts/phw.py, with commands in the prompt's order (doctor, explain, inspect, convert first). Reuse the bake-off rasterizer and pixel-exact tracer from ai-docs/notes/bakeoff/bakeoff_trace.py. Run vtracer in a subprocess.
3. Own region tracer with holes (bar: overlap 0.95 or more on logo and icon) before it is used as the fallback.
4. Step G: start ai-docs/notes/books.md.
Beat image-editing: pending (subagent running 2026-11-17)
