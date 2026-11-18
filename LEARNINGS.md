# Learnings: photowright

Research: [RESEARCH.md](RESEARCH.md).

Procedural lessons for [skills/photowright/SKILL.md](skills/photowright/SKILL.md). Changes are logged in [CHANGELOG.md](CHANGELOG.md); test runs in [TESTS.md](TESTS.md). Trigger and Hypothesis are required.

## Active

### L-20261118-1 · 2026-11-17 · check-py-leaks-the-answer
- A baseline (no-plugin) action run read evals/check.py from its work folder, learnt the phw recipe format from it and passed the layered-PSD case. The evidence script must not be in the folder while the model works: run.py copies it in only after the run. Applies to any eval whose checker names the tool or format under test.

(build-time lessons are in ai-docs/log.md)
