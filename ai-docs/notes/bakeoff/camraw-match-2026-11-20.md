# camraw --match bake-off (2026-11-20, 0.27.0)

Source: arXiv:2610.36896 (PREEN, exemplar colour style transfer with smartphone editor presets). Harvest notes:
technique-harvest `ai-docs/sources/paper/2610.36896.md`. Bench script: [camraw_match_bench.py](camraw_match_bench.py).

Method: the left half of an image graded with hidden camraw sliders is the reference, the right half the source,
the right half graded with the same sliders the truth. dE76 mean to the truth; 320 px working copies, fit on 160 px.

## Same scene (12 trials over 6 images: dark-photo fixture + 5 ComfyUI renders)

| | none | Reinhard (`tone --match`) | `camraw --match` |
|---|---|---|---|
| mean dE76 | 8.86 | 5.56 | 4.94 |
| median dE76 | 7.02 | 4.41 | 4.73 |

Fit beats Reinhard on 9 of 12; about 6 s per fit (Hooke-Jeeves, 400 to 1250 evaluations). After the fit the Lab
signature residual (RMS) was at most 1.56, L overlap at least 0.68, a/b overlap at least 0.71.

Test fixture (tests/test_phw25.py, dark-photo halves, three hidden grades): none 7.73/5.64/5.15, Reinhard
1.07/1.87/1.71, fit 0.26/0.22/0.39.

## Different scene (6 pairs)

Residual RMS 3.0 to 7.8, L overlap 0.19 to 0.57, a/b overlap 0.03 to 0.65. Thresholds chosen between the two sets:
warn when RMS > 2.5, or L overlap < 0.5, or a/b overlap < 0.5. Photo matched to the logo fixture: RMS 14.9, a/b
overlap 0.001. Small sample: widen the thresholds if real same-scene references trip it.

## Not done

Highlights and shadows stay out of the default fit (their 30 px local op is slow in the loop; `--sliders` can add
them). Texture, clarity and dehaze are not fitted (local and structural, not colour statistics).
