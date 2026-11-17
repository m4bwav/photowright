# Tests: photowright

Companions: [RESEARCH.md](RESEARCH.md), [CHANGELOG.md](CHANGELOG.md), [LEARNINGS.md](LEARNINGS.md).

Test runs for [skills/photowright/SKILL.md](skills/photowright/SKILL.md) and `scripts/phw.py`. Unit tests live in `tests/` (`python -m unittest discover -s tests`, again with `PHW_RUNG_MAX=1`), skill cases in `evals/evals.json` (`python evals/run.py`, `--baseline` for the no-skill arm; evidence in `evals/check.py`). A test passes on evidence, never on a transcript's claim.

Entry shape: `### T-YYYYMMDD-n · date · harness · env · passed/total`, then one line per notable result, then `led to:`. Newest first.

## Runs

### T-20261117-2 · 2026-11-17 · evals/run.py, claude -p --plugin-dir (sonnet) · Windows · 3/3 failing triggers fixed (9/9 runs)
- Cause of T-20261117-1's three failures: the prompts named no file, so the model asked for one instead of loading any skill. Real requests come with the file, so the cases now name fixtures: remove-object uses dark-photo.jpg ("remove the yellow ball", matching what is in the file; a prompt about a stranger who is not in the picture still failed 2/3), psd uses the new fixture tests/fixtures/poster.psd (2 layers, written by phw layers), dxf uses logo.png. Each 3/3. Description unchanged.
- led to: no skill change.

### T-20261117-1 · 2026-11-17 · evals/run.py, claude -p --plugin-dir (sonnet, Claude Code 2.1.281) · Windows · 12/15 cases (31/39 runs), baseline 1/3 action
- Triggers (2 of 3 to pass): brighten 3/3, remove-bg 3/3, perspective 3/3, batch 3/3, vectorize 3/3. Failing: remove-object 1/3, psd 0/3, dxf 0/3. In every failing run no skill fired at all (the model answered in chat and asked for the file, which these prompts do not give); no neighbour took them. A description retune ("even before the file is shared", more examples) gave remove-object 1/3, psd 0/3, dxf 1/3 and pushed the description over 1024 characters, so it was reverted.
- Decoys (0 of 3 to pass): critique 0/3 (artwright fired once), pixel 0/3 (pixelwright-make 5 of 6 runs), brand 0/3, generate 0/3 (comfyui-gen 3/3). All pass.
- Action, with skill: trace-logo PASS (vcheck overlap 0.998, 3 paths), dxf-laser PASS (EXTMAX x 50.0 mm), cutout PASS (alpha corners 0, centre 255; recipe replays with `phw run`).
- Baseline, no plugin: trace-logo PASS (own script), dxf-laser FAIL, cutout FAIL. A first baseline run was void: the work folder held a copy of scripts/phw.py and the bare model used it; run.py no longer copies scripts/.
- Catalogue: `tidy.py lint` 0 findings; `tidy.py check` probe: nearest listed skill to this description is pixelwright at TF-IDF 0.11 (threshold 0.30).
- Siblings: not split. The design rule splits -edit or -vectorize only when the hub loses prompts to neighbours, and it lost none.
- Unit tests: 104 pass normally and with PHW_RUNG_MAX=1.
- led to: C-20261117-1
