# Tests: photowright

Companions: [RESEARCH.md](RESEARCH.md), [CHANGELOG.md](CHANGELOG.md), [LEARNINGS.md](LEARNINGS.md).

Test runs for [skills/photowright/SKILL.md](skills/photowright/SKILL.md) and `scripts/phw.py`. Unit tests live in `tests/` (`python -m unittest discover -s tests`, again with `PHW_RUNG_MAX=1`), skill cases in `evals/evals.json` (`python evals/run.py`, `--baseline` for the no-skill arm; evidence in `evals/check.py`). A test passes on evidence, never on a transcript's claim.

Entry shape: `### T-YYYYMMDD-n · date · harness · env · passed/total`, then one line per notable result, then `led to:`. Newest first.

## Runs

### T-20261117-3 · 2026-11-17 · evals/run.py, claude -p --plugin-dir (sonnet) · Windows · triggers 35/36 runs, decoys 12/12, actions 3/3 cases; baseline new case 0/2
- After the worth follow-ups (C-20261118-1): description cut from ~248 to ~152 tokens (606 characters), DXF and PSD usage moved to references/.
- Triggers (2 of 3 to pass): all 8 pass; 23/24 runs (batch 2/3, one run fired no skill). Decoys: 12/12 runs pass, 4/4 cases (artwright, pixelwright-make and comfyui-gen took theirs; brand fired nothing).
- Action, with skill: layered-psd PASS (2 runs), dxf-laser PASS, cutout PASS 3 of 4 runs (one run left the corner opaque although its recipe was `cutout --method key`, which gives alpha 0 when run by hand; the model's file was not phw's output).
- New case action-layered-psd replaces action-trace-logo (which the bare model passed). Its first two baseline runs PASSED: the bare model read evals/check.py in the work folder, which names phw and the recipe format, and wrote a matching recipe. run.py now copies check.py in only for the evidence step (L-20261118-1 `check-py-leaks-the-answer`). Baseline after the fix: 0/2. Earlier baselines of dxf and cutout were taken with check.py present and failed anyway.
- led to: C-20261118-1

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
