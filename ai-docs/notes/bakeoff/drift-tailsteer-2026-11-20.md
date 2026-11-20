# `phw drift` on the TailSteer example chains (2026-11-20)

Source: arXiv:2611.06741, TailSteer (Trajectory-Tail Steering for Drift-Resistant Multi-turn Image Editing). Harvest
notes: technique-harvest `ai-docs/sources/paper/2611.06741.md` (verdict adopt-partly: the drift meter and the
"composite back or restart" rule; the fine-tuned model itself is note only, non-commercial weights).

Input: the paper's released 640x480 example, one source image and two 20-turn chains (base model, then TailSteer),
kept in a scratch folder only (licence of the images unclear, so they are not committed; the repo test is synthetic,
tests/test_phw24.py). No masks (the example edits are local but no masks were released), CPU, about 2 s for 10 rounds.

`phw.py drift 000-source.webp 001..009` (base chain, against round 0):

| turn | dE76 med | dE00 med | b* shift | SSIM |
|---|---|---|---|---|
| 1 | 2.07 | 1.88 | +0.97 | 0.906 |
| 3 | 4.53 | 3.88 | +2.69 | 0.840 (flag trips) |
| 5 | 7.42 | 6.15 | +4.72 | 0.725 |
| 7 | 11.91 | 9.80 | +9.28 | 0.665 |

TailSteer chain (021..040): turn 3 dE76 2.07, turn 5 2.88, turn 7 3.82, all under 4; turn 8 is an intended global
change (dE76 17.2). With `--global 8`, turns 9-12 score 1.5-3.4 against turn 8 and the flag trips again at turn 13
(4.07), so even the drift-resistant model passes the limit after five more rounds.

Reading: the default limit of 4 (median dE76 outside the edits) separates the two models by turn 3, where the base
chain's yellow cast is visible. These numbers match the harvest reader's prototype (turn 3: 4.5 vs 2.0; turn 5: 7.39
vs 2.86 at 512 px, here 7.42 vs 2.88 at 640 px).
