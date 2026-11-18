# Changelog: photowright

Every change to [skills/photowright/SKILL.md](skills/photowright/SKILL.md) and its companions, newest first, each with the reason. Reasons cite lessons in [LEARNINGS.md](LEARNINGS.md) (`L-`) and test runs in [TESTS.md](TESTS.md) (`T-`).

Entry shape: `### C-YYYYMMDD-n · date · one-line summary`, then `because:`, `files:`, and a sentence on what changed.

### C-20261117-2 · 2026-11-17 · 0.6.0: rung 3 routes through the local ComfyUI
- because: HANDOFF Next item 0 (wire rung 3 to the installed nodes)
- files: scripts/phw/comfy.py (new), scripts/phw/masks.py, scripts/phw/retouch.py, tests/test_comfy.py, skills/photowright/SKILL.md, references/comfyui-nodes.md
- `cutout --model birefnet` (core RemoveBackground), `fill`/`remove --model lama` (Acly inpaint nodes, big-lama) and `select --text` (Florence-2-large boxes into SAM 2.1 base_plus) run through ComfyUI over stdlib HTTP, record model and seed in the recipe step, paste back through the mask, and fall back to rung 1/2 with "fell back: <reason>". `--model` is an alias of `--method`.

### C-20261117-1 · 2026-11-17 · 0.5.0: plugin, hub skill, evals, README, SECURITY
- because: Step F of the continue prompt; T-20261117-1
- files: .claude-plugin/, skills/photowright/SKILL.md, evals/, README.md, SECURITY.md, LICENSE, evergreen companions, scripts/phw/core.py
- One hub skill (no siblings: the trigger evals did not show it losing prompts), an eval suite with decoys for artwright, pixelwright, brandwright and comfyui-gen, and a no-skill baseline. phw 0.5.0: raster saves now create the output's parent folder (an `-o out/x.jpg` into a missing folder crashed).
