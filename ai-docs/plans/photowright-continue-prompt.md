# photowright: the image editing and vectorizing plugin continue prompt

Work from `D:\m4bwa\Claude\Projects\Ai\photowright`. The name is a working name; changing it is a small ruling, decide and flag it in the log (rasterwright is the other candidate). Skill descriptions must say editing an existing image and tracing it to vectors, and never claim what the neighbours own: critique and ranking (artwright), pixel art (pixelwright), brand palettes and logos from nothing (brandwright), generating new images (comfyui-gen).

## Goal

Build an evergreen plugin that does what a person does in Photoshop, from the command line, and turns raster images into vectors. Mark's words: "Add photoshop like skills and vectoring a raster", then "It should do photoshop like activities, but photoshop itself maybe optional. Mostly I want to wean it on options that are freely available without restriction and scripts/tools of its own development".

That second sentence sets the order every route is tried in. Call it the tool ladder:

1. **The plugin's own code**: Python standard library first, then small permissive packages (Pillow, NumPy) probed at run time. This rung must cover the everyday work alone.
2. **Free tools with no restriction**: open-source licence, no account, no key, no gate, no non-commercial clause, usable in work Mark may sell. Called as an external program or optional package when present, never bundled if the licence is copyleft.
3. **Free local models with open weights** under the same test (the licence of the weights, not only of the code), run through comfyui-gen or a small runner, and only where code alone cannot do the job (cut-outs of hair, filling a hole, upscaling).
4. **Photoshop and other paid or closed tools**: an optional bridge, off by default, used only when the user has it and asks. No feature may exist only on this rung, and no eval may need it.

Every command reports which rung it used. A tool or model that fails the rung 2 or 3 test is listed in the references with the reason and is never a default.

What the plugin does:

- **Adjust**: crop, straighten, resize, canvas, rotate, flip; levels, curves, exposure, white balance, hue and saturation, colour grading and LUTs, black and white, channel mixing; sharpen, blur, denoise; colour profiles and bit depth handled correctly.
- **Compose**: layers, blend modes, opacity, layer masks, clipping, groups, adjustment layers, text and shapes, drop shadows and strokes, all from one edit recipe that can be replayed.
- **Select and mask**: by colour range, by luminance, by edge, by shape, by subject (a model); feather, grow, shrink, refine; the mask is a file the next step reads.
- **Retouch**: background removal, spot healing, clone, patch, content-aware fill and object removal, red eye, dust and scratches, old photo repair.
- **Transform**: perspective and lens correction, warp, content-aware scale, upscale, panorama stitch, focus and exposure stacking, HDR merge.
- **Batch**: the same recipe over a folder, with a dry run, a contact sheet of before and after, and nothing overwritten.
- **Files**: read and write layered files so a person can finish by hand: PSD and OpenRaster at least, and whatever GIMP and Krita open; metadata kept or stripped on request.
- **Vectorize**: trace a logo, icon, line art, drawing, photo or pixel sprite to SVG: quantize first, pick the tracer by image kind, simplify and fit curves, exact squares for pixel art, centreline tracing for line art; export SVG, PDF, EPS and DXF clean enough for a cutter, a laser and a 3D extrude through polywright.

The work ends when every group above passes its evals with the top rung turned off (rungs 1 to 3 only), the plugin is released and installed, its beat and harvest targets exist, and every book Mark has supplied is distilled. Then HANDOFF.md says `Status: finished`.

## 1. Load state

1. Read `ai-docs/HANDOFF.md` and the end of `ai-docs/log.md`, trimmed at the source: `git show origin/main:ai-docs/HANDOFF.md | head -12`, its `## Waiting on Mark` and `## What waits on Mark` sections, and `git show origin/main:ai-docs/log.md | tail -8` (a full dump of prompt, HANDOFF and log cost 11-13k tokens in each of eight 2026-11-18 sessions). Compare HANDOFF.md's age with run logs and commits, and trust the newer evidence.
2. If HANDOFF.md says the build has not started, also read, before designing anything:
   - the `evergreen-new` skill and one sibling's layout (`Ai/mapwright` or `Ai/fractalwright`) for the house shape: hub SKILL.md, one stdlib-first script, references loaded on demand, LEARNINGS, evals with a baseline, `harvest.json`, README banner, SECURITY.md, wiki;
   - the "Image editing and vectorizing plugin" entry in `Ai/plugin-backlog/new-plugins.md`;
   - the plugins this one calls and must not duplicate: artwright (`aw.py` measures and critiques, never edits; artwright-judge ranks blind pairs), pixelwright (`pxw.py`: grid snap, palette lock, outlines, tiles, sprite animation), brandwright (brand marks and palettes), comfyui-gen (image models on both hosts; inpaint, upscale and segmentation workflows already wired there), labwright (which host is idle), polywright (SVG to a mesh or a print), chartwright (data charts), sitewright (site images), cinewright (stills and frames from films), askwright (decision pages), everscout (beats), readwright (books);
   - what already exists on this machine that the plugin may reuse instead of rewriting: the SAM scripts under the chainwright plugin cache (`roof_snow_sam.py`), pixelwright's region masks and palette code, artwright's colour and composition measures.
3. Standing rules are not repeated here. Their sources: `C:/Users/m4bwa/.claude/CLAUDE.md` (pull requests, merging, releases, attribution, worktrees, file links, wrap-up), the chainwright SKILL.md, and the memory index (package size budget, local servers over Artifacts, estimates in agent time, small rulings, tests always allowed, the model download floor, Krea 2 provenance, Meta-gated models, kill by PID only, queue on a busy GPU, README banner).

## 2. Read answers

For any askwright set HANDOFF.md names, run `ask.py read`, act on answered questions and close them. "Not sure" and unanswered questions stay open; never fill them with the guess.

## 3. Order of work

This is one chain. The session that runs this prompt is the master: it hands each batch (a research topic, a book, a tool test, a build step in its own worktree) to a subagent, keeps only the short report and the file pointers, and hands on to a fresh session only when its own context runs low. Take the next item HANDOFF.md names, then the next step below. Update HANDOFF.md at each milestone.

### Step A. Research, written to `references/` and `kb/` with a source on every claim

One subagent per topic, in parallel. Every tool, package, model and file format named gets a row in `kb/tools.json`: licence of the code, licence of the weights or data, whether it needs an account, key or gate, whether output may be sold, install size, which rung it sits on, and the date checked. Licences are read from the source, never from memory.

1. **What Photoshop does**: the full feature map (tools, adjustments, filters, layer features, smart objects, actions, neural filters, generative fill) and, for each, what the operation is underneath: the maths or the model. This list is the coverage table the build is scored against.
2. **Image fundamentals an editor must get right**: colour spaces and ICC profiles, gamma and linear light (resize and blend in linear), bit depth, alpha (straight against premultiplied), EXIF orientation, chroma subsampling, the traps in each common file format, and metadata.
3. **Rung 1 survey**: what the standard library, Pillow and NumPy can do alone, how fast, and where they stop; the blend mode formulas as published by Adobe and the W3C compositing spec; curves, LUTs and colour grading in code.
4. **Rung 2 survey**: the free command-line and scriptable editors and libraries (ImageMagick, libvips, G'MIC, OpenCV, scikit-image, GIMP in batch mode, Krita's scripting, Inkscape's command line, darktable and RawTherapee for raw files, Hugin and enfuse for stitching and stacking, ExifTool). For each: licence, what it adds over rung 1, how to probe and call it, and its traps on Windows.
5. **Layered file formats**: PSD and PSB (the published spec, what the open readers and writers support and lose), OpenRaster, XCF, KRA, layered TIFF; which round-trips keep layers, masks, blend modes, text and effects.
6. **Selection and matting**: classic methods (colour range, GrabCut, flood, edge) and open models for subject cut-outs and hair. Check each model's weight licence one by one: several popular background-removal models are non-commercial or gated and belong off the default list. SAM 2.1 is the ungated default for click and box selection; a Meta-gated model is raised only with a clear measured gain.
7. **Retouch and fill**: healing and patch algorithms (Poisson blending, PatchMatch, Telea, Navier-Stokes), open inpainting models and their licences, object removal, what content-aware fill does, and when code beats a model.
8. **Upscale, denoise, restore**: classic resampling done right, open upscalers, denoisers and face or old-photo restorers with their licences, and how to tell invented detail from recovered detail.
9. **Transform and merge**: perspective and lens correction, seam carving, panorama stitching, focus stacking, exposure fusion and HDR.
10. **Vectorizing**: how tracing works (edge and region methods, curve fitting, corner detection, colour layering against cutting), the open tracers and their licences and strengths (Potrace, VTracer, AutoTrace, the pixel-art vectorizers, centreline tracers), the AI vectorizers and which are open, path simplification, and what makes an SVG clean for a cutter, a laser, a font or a 3D extrude.
11. **Vector formats and their readers**: SVG subsets that every program opens, PDF, EPS, DXF, and the cutter and laser programs' import limits.
12. **The Photoshop bridge**: the ways to drive Photoshop from outside (UXP, ExtendScript, the COM interface on Windows, the cloud API, existing MCP servers), what each needs, and the same for Affinity and Photopea where they can be scripted. Reading only; nothing here is installed or run without Mark.
13. **Prior art**: existing image-editing and vectorizing skills, plugins and MCP servers, so the plugin does not duplicate one and borrows what works.

### Step B. Beat and harvest targets

- Create an everscout beat for image editing and vectorizing with everscout-beat: verified sources (open-source editor and tracer projects, photo retouching and vector communities, GitHub), entities, a question bank and a literature list. Findings land in LEARNINGS for review, never straight in the skill.
- Add `harvest.json` to the plugin so the technique harvest (`Ai/technique-harvest`, `evergreen.py harvest targets --json`) picks it up.

### Step C. Design note, then decisions

Write `ai-docs/plans/design.md`. It must settle, by measurement and not by taste:

- **The edit recipe**: one folder per job holding the untouched source, an ordered list of steps (operation, parameters, mask, layer, seed, tool and rung used, tool version) and the outputs. Replaying it gives the same pixels. The source is never modified.
- **The core**: how much rung 1 covers against the coverage table from topic 1, at what speed and install size. A rung 2 tool becomes a named optional backend only where it wins a measured test; ImageMagick or libvips is not assumed.
- **The own-tools list**: which pieces the plugin writes for itself because nothing free does them well or small enough (candidates: the layer compositor, the PSD and OpenRaster writer, the recipe runner, a pixel-exact tracer, a centreline tracer, the vector cleaner). Each is weighed against calling an existing tool, on quality, size and licence.
- **Tracer choice**: the open tracers and the plugin's own run against each other on a fixed set (logo, icon, line art, photo, pixel sprite), scored by the proof bars below.
- **Model routes**: which rung 3 models run through comfyui-gen and which need a small runner, on which host, with what download size.
- **Skills**: one hub, or a hub with siblings (edit, vectorize); let the catalogue lint and the trigger evals decide.
- **Scope edges**: what stays with the neighbours listed in section 1 and what moves here.

Open choices go on an askwright page (name, public or private repo, whether a Photoshop bridge is wanted at all and which version he has, which of his projects to serve first); carry on with the guesses meanwhile.

### Step D. Build the script, each command proven before the next

One command-line script with a short name no sibling uses (taken: `aw.py`, `arw.py`, `cw.py`, `fw.py`, `lw.py`, `mpw.py`, `mw.py`, `pw.py`, `pxw.py`, `qw.py`, `rw.py`, `sw.py`, `tw.py`; check the rest first). Commands, in this order:

- `doctor` (what is installed, which rung each feature will use, what is missing), `explain` (a term, a blend mode, a tool), `inspect` (size, mode, profile, bit depth, alpha, layers, metadata), `convert`.
- `adjust` (levels, curves, exposure, balance, hue and saturation, grade, LUT), `crop`, `resize`, `rotate`, `sharpen`, `denoise`.
- `select` and `mask` (colour, luminance, edge, shape, subject; feather, grow, shrink, combine), `cutout` (background removal).
- `layers` (build a composite from a recipe: blend modes, opacity, masks, text, shapes, effects), `open` and `save` for layered files.
- `heal`, `clone`, `fill` (content-aware), `remove` (an object), `restore`.
- `warp`, `perspective`, `upscale`, `stitch`, `stack`.
- `run` (replay a recipe), `batch` (a recipe over a folder, dry run first), `sheet` (before and after, or variations side by side), `diff` (what changed between two images, and where).
- `trace` (raster to vector, with a kind: logo, line, pixel, photo, centreline), `simplify`, `vcheck` (the vector bars below), `export` (SVG, PDF, EPS, DXF).
- `bridge` (optional: hand a recipe to Photoshop or another closed editor when present; refuses politely when absent).

Proof bars, numbers and not opinions:

- **Adjustments**: each operation matches a reference result within a stated tolerance; a round trip (apply and invert) returns the source within tolerance; resizing and blending happen in linear light; the colour profile survives or is converted on purpose, never dropped.
- **Blend modes**: each mode matches the published formula on a test grid, and matches a Photoshop-made reference file where one is on disk.
- **Layered files**: a file written by the plugin opens in GIMP or Krita with the same layer names, order, opacity, masks and blend modes; a file read and written back keeps them.
- **Masks and cut-outs**: overlap with hand-made masks on a fixed set is measured and stated per method; nothing outside the mask changes by one pixel.
- **Retouch and fill**: pixels outside the region are identical; the seam is measured (gradient at the border against the surroundings).
- **Upscale and restore**: scored against a held-back original; text and faces are flagged where detail is invented.
- **Batch**: no source file is overwritten; a second run changes nothing; a failed file is reported and the rest finish.
- **Vectorize**: the SVG rendered back overlaps the raster above a stated share; path, node and colour counts are under a budget per image kind; no open paths where closed are needed, no stray points, no self-intersections; a pixel sprite traces to exact squares; the file opens in Inkscape and a browser; the DXF holds only what a cutter accepts.
- **The ladder**: the whole suite passes with rung 4 absent; each rung 3 feature has a rung 1 or 2 fallback that says what it loses.
- Pictures a person will judge go through artwright-judge blind pairs first, then to Mark on an askwright page.

### Step E. First real uses

Before release, do one job Mark would keep in each of four kinds, picked from his own projects (HANDOFF.md names them once he has answered): a photo retouch, a layered composite, a batch over a folder, and a trace to a clean vector. Each goes through the bars, then to him on an askwright page. What fails becomes a test.

### Step F. Skill, evals, release

Hub skill (and siblings only if the design note says so), eval suite with a no-skill baseline (evergreen-test) including decoys for critique, pixel art, brand work and image generation so the neighbours keep their prompts, worth check (evergreen-worth), README with banner, SECURITY.md, wiki (wikiwright), then repository, release and install as the standing rules say. Add the plugin to `Ai/plugin-backlog/existing-plugins.md` when released and keep its `new-plugins.md` entry's status line current.

### Step G. Books

Keep `ai-docs/notes/books.md`: the books worth distilling (image processing, retouching, colour, vector drawing), with a status per title. When one turns up on disk (`Ai/technique-harvest/scripts/book_harvest.py find`), a reader subagent distills it with readwright under `Ai/technique-harvest/ai-docs/books/BUILD-BRIEF.md`; only tested rules enter the skill. Free online titles are fetched and read without waiting.

## 4. Stop before anything that needs the owner

Put the question on an askwright page, record the set in HANDOFF.md, and carry on with other work. These wait on Mark:

- making the repository public, and the final name;
- installing or running Photoshop, any other paid or closed editor, or any downloaded third-party desktop program (GIMP, Krita, Inkscape and the like); reading their docs and file formats is free, and a tool already on the machine may be called;
- any account, API key, subscription or paid plan;
- any model whose weights are gated, non-commercial or of unclear licence, and any model download that would break the download floor's free-space rule;
- editing family photos or any picture of a real person in a way that leaves this machine, and sending any of his images to an outside service;
- shipping or redistributing fonts, brushes, textures, LUTs, test images or sample files whose licence is not clearly open; test images are made by the plugin or taken from public-domain sources with the source recorded;
- bundling copyleft code or binaries in the plugin (call them as external programs instead);
- anything the "tests always allowed" grant excludes: disk space, security, legal questions, renders that tie up a GPU for hours;
- any unattended or scheduled run;
- publishing to a package registry or the Claude directory;
- buying books.

## 5. Stop early

If HANDOFF.md says `Status: finished`, or nothing can move without Mark, say what waits and stop. Waiting on a review of pictures never ends a session while research, tests, evals or books remain.

## 6. Hand over

Run the wrap-up (evergreen-wrapup, if installed; a failure is reported and never blocks), update `ai-docs/log.md` and `ai-docs/HANDOFF.md`, and only then print the start command: `Execute D:/m4bwa/Claude/Projects/Ai/photowright/ai-docs/plans/photowright-continue-prompt.md`, with the folder to start in (`D:/m4bwa/Claude/Projects/Ai`). State goes in HANDOFF.md, never in this file.
