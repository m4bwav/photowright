# Ladder evals, rung 4 off (2026-11-18, session 33)

Unit suite (phw 0.20.0) run with PHW_RUNG_MAX=3, grouped by the goal's eight feature groups with
[evals/ladder_report.py](../../evals/ladder_report.py) (keyword match on the test name, so a test lands in one group only;
"batch" also holds recipe and replay tests). Every group passes; the 3 skips are live ComfyUI tests (8199 busy with H3).
The same suite with no limit: 258 run, OK (3 skipped).

| group | ok | fail | error | skip |
|---|---|---|---|---|
| adjust | 38 | 0 | 0 | 0 |
| compose | 19 | 0 | 0 | 0 |
| transform | 25 | 0 | 0 | 0 |
| retouch | 14 | 0 | 0 | 1 |
| select | 17 | 0 | 0 | 2 |
| batch | 70 | 0 | 0 | 0 |
| files | 23 | 0 | 0 | 0 |
| vectorize | 21 | 0 | 0 | 0 |
| other | 21 | 0 | 0 | 0 |

Ran 258: OK (skipped=3)
zone plate 4x shrink RMS vs Lanczos: prefiltered 0.0773, raw 0.3726


Not yet covered by this run: the model-judged skill evals (evals/run.py, claude -p) were last run 2026-11-17 (T-20261117-3);
re-run them before release. Rung 3 features each have a rung 1/2 fallback (see design.md); live rung 3 measures
(SeedVR2, qwen-edit) still wait for an idle 8199.
