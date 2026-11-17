# photowright

Image editing (Photoshop-like, from the command line) and raster-to-vector tracing, as an evergreen plugin. Working name.

- State: [ai-docs/HANDOFF.md](ai-docs/HANDOFF.md); log: [ai-docs/log.md](ai-docs/log.md); continue prompt: [ai-docs/plans/photowright-continue-prompt.md](ai-docs/plans/photowright-continue-prompt.md).
- Tool ladder: own code (stdlib, Pillow, NumPy) first; free unrestricted tools second; open-weight local models third; Photoshop optional and never required.
- Research lives in `references/` (one file per topic, a source on every claim) and `kb/tools.json` (licence rows).
- Neighbours keep their jobs: artwright critiques, pixelwright does pixel art, brandwright brand marks, comfyui-gen generates.
- Code: `scripts/phw.py` is the CLI entry; the code is the package `scripts/phw/` (core: batch 1 edits and recipes; masks: select, mask, cutout; compose: blend modes and layers; layered: PSD/ORA open and save; retouch: heal, clone, fill, remove, restore; transform: warp, perspective, upscale, stitch, stack; batchops: batch, sheet, diff; vector: SVG model, render-back, curve fit, vcheck, simplify, export SVG/PDF/EPS/DXF; vtrace: trace kinds, VTracer in a subprocess, own region/pixel/centreline tracers). Seam carving is left out on purpose (Adobe patent flag, references/transform-merge.md s4). Tests: `python -m unittest discover -s tests`, and again with `PHW_RUNG_MAX=1`; `PHW_SKIP_GIMP=1` skips the GIMP check.
- Plugin (Step F, 0.5.0): `.claude-plugin/`, one hub skill `skills/photowright/SKILL.md` (no siblings: trigger evals did not ask for them), evergreen companions at the root (RESEARCH, CHANGELOG, LEARNINGS, TESTS, evergreen.json, MAINTENANCE). Skill evals: `python evals/run.py` (with the plugin) and `--baseline` (without); action evidence in `evals/check.py`; fixtures in `tests/fixtures/`.
