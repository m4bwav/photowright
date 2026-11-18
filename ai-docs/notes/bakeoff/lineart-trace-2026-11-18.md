# Centreline bake-off: own tracer vs lineart-trace 0.2.0 (2026-11-18, session 50)

lineart-trace 0.2.0 (MIT, https://github.com/UCB-BioE-Anderson-Lab/lineart-trace, commit ea50ebd) ran from `photowright-lab/lineart-venv` (Mark installed it). Own: `phw trace --kind centreline` (rung 1, own Zhang-Suen; scikit-image absent). Scored with `phw vcheck --kind centreline` (16x render-back overlap with the source).

Inputs, made by [lineart_make.py](lineart_make.py) (drawn at 4x, Lanczos to 400x300): a spiral, a sketch (A, circle, arc, sine stroke), a 6x5 grid. `scan` is the sketch with a 35 % lighting falloff and noise sigma 12, scored against the clean sketch. Runner: [lineart_run.py](lineart_run.py) (`lineart-trace IN --svg -q -o OUT`).

| image | own overlap | lt overlap | own nodes | lt nodes | own s | lt s |
|---|---|---|---|---|---|---|
| spiral | 0.975 | 0.967 | 24 | 19 | 1.6 | 0.34 |
| sketch | 0.972 | 0.967 (1 stray point, fails vcheck) | 45 | 44 | 1.5 | 0.31 |
| grid | 0.949 | 0.918 | 98 | 102 | 1.3 | 0.40 |
| scan | 0.972 | 0.966 (0.965 with --denoise) | 45 | 42 | 1.3 | 0.30 |

Times are whole-process wall clock; the own figure is mostly Python + NumPy start-up for the phw CLI.

Verdict: keep the own tracer as the centreline route; do not add lineart-trace as a rung 2 option (no quality gain, it is not on PyPI, and it pulls opencv-python). Worth noting from it: it writes a measured stroke width with round caps and joins, a full `<svg>` only with `--svg` (the default output is a bare `<g>` fragment), and a white `<rect width="100%">` background that crashed our SVG reader (fixed in 0.25.2).
