# Learnings: photowright

Research: [RESEARCH.md](RESEARCH.md).

Procedural lessons for [skills/photowright/SKILL.md](skills/photowright/SKILL.md). Changes are logged in [CHANGELOG.md](CHANGELOG.md); test runs in [TESTS.md](TESTS.md). Trigger and Hypothesis are required.

## Active

### L-20261118-1 · 2026-11-17 · check-py-leaks-the-answer
- A baseline (no-plugin) action run read evals/check.py from its work folder, learnt the phw recipe format from it and passed the layered-PSD case. The evidence script must not be in the folder while the model works: run.py copies it in only after the run. Applies to any eval whose checker names the tool or format under test.

(build-time lessons are in ai-docs/log.md)

## 2026-11-18 from the everscout image-editing beat (scan 2) - for review
- Moebius (hustvl/Moebius, ECCV 2026): 0.2B inpainting model; repo licence Apache-2.0 (GitHub API), write-ups say weights too. Claimed near FLUX.1-Fill-dev quality at ~15x speed (claim, not measured). ComfyUI node: b2renger/ComfyUI_moebius_inpainting. Candidate rung-3 engine for remove/fill; check CPU speed and the HF weights licence before adopting.
- Background-removal licences unchanged in 2026: BiRefNet code and weights MIT; BRIA RMBG-1.4/2.0 non-commercial. BiRefNet stays the default.
- ImageMagick November 2026 advisories fixed in 7.1.2-35 (Windows policy bypass mixing / and \, raw decoder DoS, XMP resource limit). If phw shells out to ImageMagick, require 7.1.2-35+.
- libvips 8.18 (Dec 2025): UltraHDR gain-map load/save, camera RAW via libraw, Oklab colourspace.
- VTracer 1.0.0-alpha.4 (VTracer 2 engine) is out; check the phw subprocess wrapper still works with it.
