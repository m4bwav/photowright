# HANDOFF: photowright

2026-11-18 (session 24): 8199 busy again (SeedVR2/qwen-edit unmeasured). Built phw 0.10.0: `tone`, `effect`, `canvas` commands, 9 more rung 1 coverage rows (tests/test_phw9.py); suite 161 pass, rung-1-only 151 + 10 skip. Next rung 1 builds are listed at the bottom of [notes/coverage-gaps-2026-11-17.md](notes/coverage-gaps-2026-11-17.md) (Brightness/Contrast, Color Balance, Photo Filter, Selective Color, Dehaze, Clarity, Smart Sharpen, frequency separation, skew, distort family, pixelate).

2026-11-18 (session 23): 8199 busy with an H3 render again (SeedVR2/qwen-edit still unmeasured). Built phw 0.9.0 (PR #24, merged): new `filter` and `color` commands, 12 rung 1 coverage rows (gaussian/box/motion blur, high pass, max/min, offset, invert, posterize, threshold, solarize, channel mixer, gradient map), tests/test_phw8.py; full suite 151 pass, PHW_RUNG_MAX=1 141 pass + 10 skip. Gap list with ~58 rows still open and a build-next order: [notes/coverage-gaps-2026-11-17.md](notes/coverage-gaps-2026-11-17.md) (next: Auto Tone/Contrast/Color, Vibrance, Shadows/Highlights, Match Color, Add Noise, Emboss/Find Edges, Canvas Size/Trim). Token tip: load state with `git show origin/main:ai-docs/log.md | tail -8`, not the whole log (~11k tokens per session wasted).

Status: phw 0.8.0 + opt-in `trace --backend vtracer1` (2026-11-17 session 22: VTracer 1.0 bake-off, see [notes/bakeoff/vtracer1-2026-11-17.md](notes/bakeoff/vtracer1-2026-11-17.md)). Session 21: `bridge` built and GIMP-proven; first everscout scan done, see log. Earlier: phw 0.7.0 merged (2026-11-18: all 10 Szeliski proposals built, PR #15; worth follow-ups done, PR #16: description 152 tokens, new layered-PSD action case, baseline now fails every action). NOT public or tagged: going public waits on Mark. 2026-11-18: upscale --method seedvr2 wired (offline tests only; live run unmeasured, 8199 busy with an H3 render). Next: live-measure SeedVR2 vs Lanczos on a held-back original when 8199 is idle, live-measure `fill --model qwen-edit` (wired 2026-11-18, 0.7.1, offline tests only), IC-Light relight, (0.7.2 2026-11-18: stack/stitch recipes replay after a folder move; 8199 still busy with H3 at that session's start), layered, re-run evergreen-worth heavy for a final KEEP, wiki after public, bridge last, first everscout scan.

Continue prompt: [plans/photowright-continue-prompt.md](plans/photowright-continue-prompt.md)

## Mark's request (2026-11-16)

"Add photoshop like skills and vectoring a raster", then: "It should do photoshop like activities, but photoshop itself maybe optional. Mostly I want to wean it on options that are freely available without restriction and scripts/tools of its own development". Read as the tool ladder in the prompt.

## Where things are

- references/: 13 research files (feature map ~190 rows = coverage table; fundamentals rules R1-R26; rung1, rung2, layered formats, bridge, prior art, selection, retouch, upscale, transform, vectorize, vector formats).
- kb/tools.json: 103 licence rows, verified at source 2026-11-17 except imagetracerpy and Photopea terms.
- Summary of findings: last entry of [log.md](log.md).

## Waiting on Mark

- ANSWERED and closed 2026-11-17 (all keep; tracer same): askwright set `photowright-stepE-jobs-2026-11-17`, folder [ask/photowright-stepE-jobs-2026-11-17](../ask/photowright-stepE-jobs-2026-11-17) (`ask.py read` it). Six questions: keep/redo for the retouch, card composite, sprite batch, Electrum pixel trace, sun emblem DXF, and VTracer vs own tracer for the emblem. Jobs live outside the repo in D:/m4bwa/Claude/Projects/Ai/photowright-jobs/ (1-retouch, 2-composite, 3-batch, 4-trace; review/ holds the before/after sheets). artwright-judge blind pairs skipped: only one pair existed and it is on the page as a compare question.

- ANSWERED and closed 2026-11-17 (see log): askwright set `photowright-setup-2026-11-17`: folder [ask/photowright-setup-2026-11-17](../ask/photowright-setup-2026-11-17) (`ask.py read` it). Asks for the name, public timing, the Photoshop bridge and version, the first-job projects, and installing Potrace/Inkscape/GIMP. Carry on with the guesses in [plans/design.md](plans/design.md) section 8.

## Next

0. Wiki after Mark makes the repo public. Worth follow-ups (log). Rung 3 DONE 2026-11-17 in 0.6.0 (scripts/phw/comfy.py, tests/test_comfy.py): cutout --model birefnet, fill/remove --model lama, select --text (Florence-2 + SAM 2.1 base_plus). SeedVR2 upscale wired 2026-11-18 (comfy.graph_seedvr2, core nodes; weights only on the Windows box). Qwen-Image-Edit fill wired 2026-11-18 (0.7.1, `fill --model qwen-edit --prompt`). Still to wire: relight (IC-Light+DA-V2 Small), layers (layerdiffuse/Qwen-Image-Layered). references/comfyui-nodes.md Installed column updated 2026-11-18 (IC-Light, controlnet_aux DA-V2 Small, layerdiffuse confirmed on /object_info and disk). 8199 was busy with an H3 render again at the 2026-11-18 nodes session: SeedVR2 and qwen-edit still unmeasured.

1. Step G: Szeliski proposals ALL BUILT 2026-11-18 (0.7.0). Was: build its 10 proposals, each test first (adjust luminance curves and equalise, bilateral denoise, warp prefilter, pyramid composite, median stack, fill/stitch doc lines, upscale invented flag). The rest of ai-docs/notes/books.md are leads.
2. Step E: first real jobs, one per kind from Mark's five projects (Arvum sprites, SpaceDeckBuilder2 cards, polywright print/laser, AI film stills, markdavidrogers.com images): a photo retouch, a layered composite, a batch over a folder (phw batch, dry run first), a trace to a clean vector (phw trace + vcheck + export, DXF for laser). Each goes through the bars, then to Mark on an askwright page. Whatever fails becomes a test.
   Batch 4 notes: VTracer always runs in a subprocess and a crash falls back to the own region tracer (rung 1), which beats VTracer on logo, icon and line art with fewer nodes. The own photo trace clears 0.80 by a thin margin (0.804, k=32). Node budgets are 2x the TRUE VTracer counts (the bake-off regex inflated them). EPS is structure-tested only (Inkscape needs Ghostscript). Potrace is still not installed (backend refuses with the link). Stack/stitch recipes: fixed 2026-11-18 in 0.7.2 (others stored relative with sha256, replay after a folder move tested).
3. Step F rest: (a) act on Mark's Step E answers (set photowright-stepE-jobs-2026-11-17); (b) evergreen-worth on skills/photowright; (c) done 2026-11-17 (T-20261117-2, all triggers pass); (d) wiki (wikiwright), make the repo public, tag 0.5.0 release, install, add to Ai/plugin-backlog/existing-plugins.md. Banner done: .github/images/banner.jpg (Z-Image, Mac, seed 22).
4. DONE 0.8.0: `bridge` (GIMP run+compare, Krita emitted since not installed, Photopea/Photoshop scripts). Open: live Krita check if it is ever installed (needs Mark).
5. DONE first everscout scan and VTracer 1.0 bake-off 2026-11-17 (1.0 default = 0.6.15; `--preset poster` wins photo 0.884 vs 0.840, wired opt-in as `--backend vtracer1`; own tracer still wins logo/icon/line; 1.0 pixel mode 29% fewer nodes on the sprite, not wired). open-vectorizer not run (MIT, no weights, but no binaries; needs Rust): retest when a release ships. Next: consider vtracer1 as auto default once 1.0 leaves alpha or reaches PyPI; beat needs reddit.reader set and committing in indie-ai-scout (owner items).
Beat image-editing: built 2026-11-17 at Ai/indie-ai-scout/beats/image-editing (32 sources, 58 entities, 22 questions, 10 books). Owner items there: study outline approval, 4 candidate metrics, engagement (off). Not scanned yet.

## Szeliski book
Done 2026-11-17: PDF downloaded (personal use, no reposting) to Ai/technique-harvest/books-cache/szeliski; notes in technique-harvest/ai-docs/books/szeliski-cvaa-2e/notes.md; photowright summary and proposals in ai-docs/notes/szeliski.md.
