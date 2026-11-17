# Research: photowright

Findings that back [skills/photowright/SKILL.md](skills/photowright/SKILL.md). Changes they caused are logged in [CHANGELOG.md](CHANGELOG.md); procedural lessons live in [LEARNINGS.md](LEARNINGS.md); test runs in [TESTS.md](TESTS.md); schedule and state in `evergreen.json`. Protocol: [MAINTENANCE.md](MAINTENANCE.md).

Topic: image editing tools (Photoshop features and free equivalents), matting and restore models, raster-to-vector tracers, vector and layered file formats. Tier `moderate`. Last refresh 2026-11-17; next due 2026-12-17.

## Current understanding

The sourced research lives in [references/](references/) (13 files, checked 2026-11-16/17) and licence rows in [kb/tools.json](kb/tools.json) (103 rows). This section is the summary a refresh checks.

- Settled: colour management, linear-light resampling, bit depth and alpha rules R1-R26 ([image-fundamentals.md](references/image-fundamentals.md)); Poisson blending, PatchMatch fill, GrabCut, homography ([retouch-fill.md](references/retouch-fill.md), [selection-matting.md](references/selection-matting.md), [transform-merge.md](references/transform-merge.md)); SVG subset, DXF R12, PDF and EPS ([vector-formats.md](references/vector-formats.md)); PSD and ORA layouts ([layered-formats.md](references/layered-formats.md)).
- Moving: matting and upscaling models (BiRefNet, Real-ESRGAN and successors, [upscale-restore.md](references/upscale-restore.md)); tracers (VTracer releases, Potrace, AI vectorizers, [vectorize.md](references/vectorize.md)); agent image-editing skills and MCP servers ([prior-art.md](references/prior-art.md)).
- Licence facts that bite: seam carving left out (Adobe patent flag); copyleft tools only as subprocesses; imagetracerpy and Photopea terms not yet verified at source.
- Community practice: the everscout `image-editing` beat (built 2026-11-17, not scanned yet).
