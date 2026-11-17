# HANDOFF: photowright

Status: Step F part 1 done (phw 0.5.0, 2026-11-17): plugin manifest, hub skill `photowright` (no siblings), evergreen companions, eval suite (12/15 cases with the skill; decoys 4/4; action 3/3 with, 1/3 baseline), README with banner, SECURITY.md, merged to main. Not tagged, not public, no wiki. Next: Mark's Step E answers in set `photowright-stepE-jobs-2026-11-17`, then evergreen-worth, wiki, public repo plus release plus install. Repo private m4bwav/photowright (main).

Continue prompt: [plans/photowright-continue-prompt.md](plans/photowright-continue-prompt.md)

## Mark's request (2026-11-16)

"Add photoshop like skills and vectoring a raster", then: "It should do photoshop like activities, but photoshop itself maybe optional. Mostly I want to wean it on options that are freely available without restriction and scripts/tools of its own development". Read as the tool ladder in the prompt.

## Where things are

- references/: 13 research files (feature map ~190 rows = coverage table; fundamentals rules R1-R26; rung1, rung2, layered formats, bridge, prior art, selection, retouch, upscale, transform, vectorize, vector formats).
- kb/tools.json: 103 licence rows, verified at source 2026-11-17 except imagetracerpy and Photopea terms.
- Summary of findings: last entry of [log.md](log.md).

## Waiting on Mark

- OPEN 2026-11-17: askwright set `photowright-stepE-jobs-2026-11-17`, folder [ask/photowright-stepE-jobs-2026-11-17](../ask/photowright-stepE-jobs-2026-11-17) (`ask.py read` it). Six questions: keep/redo for the retouch, card composite, sprite batch, Electrum pixel trace, sun emblem DXF, and VTracer vs own tracer for the emblem. Jobs live outside the repo in D:/m4bwa/Claude/Projects/Ai/photowright-jobs/ (1-retouch, 2-composite, 3-batch, 4-trace; review/ holds the before/after sheets). artwright-judge blind pairs skipped: only one pair existed and it is on the page as a compare question.

- ANSWERED and closed 2026-11-17 (see log): askwright set `photowright-setup-2026-11-17`: folder [ask/photowright-setup-2026-11-17](../ask/photowright-setup-2026-11-17) (`ask.py read` it). Asks for the name, public timing, the Photoshop bridge and version, the first-job projects, and installing Potrace/Inkscape/GIMP. Carry on with the guesses in [plans/design.md](plans/design.md) section 8.

## Next

1. Step G done 2026-11-17: Szeliski read and distilled (ai-docs/notes/szeliski.md). Next: build its 10 proposals, each test first (adjust luminance curves and equalise, bilateral denoise, warp prefilter, pyramid composite, median stack, fill/stitch doc lines, upscale invented flag). The rest of ai-docs/notes/books.md are leads.
2. Step E: first real jobs, one per kind from Mark's five projects (Arvum sprites, SpaceDeckBuilder2 cards, polywright print/laser, AI film stills, markdavidrogers.com images): a photo retouch, a layered composite, a batch over a folder (phw batch, dry run first), a trace to a clean vector (phw trace + vcheck + export, DXF for laser). Each goes through the bars, then to Mark on an askwright page. Whatever fails becomes a test.
   Batch 4 notes: VTracer always runs in a subprocess and a crash falls back to the own region tracer (rung 1), which beats VTracer on logo, icon and line art with fewer nodes. The own photo trace clears 0.80 by a thin margin (0.804, k=32). Node budgets are 2x the TRUE VTracer counts (the bake-off regex inflated them). EPS is structure-tested only (Inkscape needs Ghostscript). Potrace is still not installed (backend refuses with the link). `run` was not extended to stack/stitch recipes (they store `others` as absolute paths and replay through apply_steps already, untested).
3. Step F rest: (a) act on Mark's Step E answers (set photowright-stepE-jobs-2026-11-17); (b) evergreen-worth on skills/photowright; (c) the three failing triggers (remove-object, psd, dxf: file-less prompts, no skill fires; see TESTS.md T-20261117-1); (d) wiki (wikiwright), make the repo public, tag 0.5.0 release, install, add to Ai/plugin-backlog/existing-plugins.md. Banner done: .github/images/banner.jpg (Z-Image, Mac, seed 22).
4. Last (Mark's ruling): `bridge` to free editors (GIMP batch, Krita, Photopea); the Photoshop route is documentation only.
5. First everscout scan of image-editing (everscout-scan) when convenient.
Beat image-editing: built 2026-11-17 at Ai/indie-ai-scout/beats/image-editing (32 sources, 58 entities, 22 questions, 10 books). Owner items there: study outline approval, 4 candidate metrics, engagement (off). Not scanned yet.

## Szeliski book
Done 2026-11-17: PDF downloaded (personal use, no reposting) to Ai/technique-harvest/books-cache/szeliski; notes in technique-harvest/ai-docs/books/szeliski-cvaa-2e/notes.md; photowright summary and proposals in ai-docs/notes/szeliski.md.
