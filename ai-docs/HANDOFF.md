# HANDOFF: photowright

Status: Step A research done (2026-11-16); Step B next. Repo private m4bwav/photowright (main).

Continue prompt: [plans/photowright-continue-prompt.md](plans/photowright-continue-prompt.md)

## Mark's request (2026-11-16)

"Add photoshop like skills and vectoring a raster", then: "It should do photoshop like activities, but photoshop itself maybe optional. Mostly I want to wean it on options that are freely available without restriction and scripts/tools of its own development". Read as the tool ladder in the prompt.

## Where things are

- references/: 13 research files (feature map ~190 rows = coverage table; fundamentals rules R1-R26; rung1, rung2, layered formats, bridge, prior art, selection, retouch, upscale, transform, vectorize, vector formats).
- kb/tools.json: 103 licence rows. Rows marked "verify"/"unverified" must be re-read at the source before Step C relies on them (rung 2 tools, transform tools, Adobe links, GIMP/Krita PSD losses, psdtags, Photopea, imagetracerpy).
- Summary of findings: last entry of [log.md](log.md).

## Waiting on Mark

Nothing yet. First askwright page (name, public/private, Photoshop bridge wanted and which version, which projects first) is made in Step C.

## Next

1. Verification pass: one subagent re-reads every "verify"/"unverified" licence row at its source and fixes kb/tools.json.
2. Step B: everscout beat for image editing and vectorizing (everscout-beat); harvest.json (copy mapwright's shape).
3. Step C: ai-docs/plans/design.md, measured (tracer bake-off needs vtracer: `pip install vtracer` is MIT, allowed), then the askwright page.
