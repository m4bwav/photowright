# GitHub wiki (2026-11-18, photowright 0.25.0)

Live at https://github.com/m4bwav/photowright/wiki, repo https://github.com/m4bwav/photowright.wiki.git (master, commit b5748be). Written with wikiwright's command-line page set.

- Pages: Home, Getting-Started, Commands, How-Recipes-Work, Tracing-to-Vectors, Tool-Rungs (stands in for Configuration: rungs, `--rung-max`, PHW_* variables), FAQ, Versions-and-Upgrading, Development, _Sidebar, _Footer.
- No Recipes page: "recipe" already means phw's JSON replay file; How-Recipes-Work covers it.
- Pages naming the version (update on each release): Home, Getting-Started, Commands, Versions-and-Upgrading, Development, _Footer.
- Examples verified by running them on `git archive v0.25.0` against tests/fixtures: [2026-11-18-wiki-verify.sh](2026-11-18-wiki-verify.sh), output [2026-11-18-wiki-verify.out.txt](2026-11-18-wiki-verify.out.txt). All exited 0. Not run: plugin install, rung 3 ComfyUI routes, evals.
- Facts found on the way (now on the wiki): `run` on a recipe differs from a step-by-step JPEG run by up to 2/255 on 3 pixels (lossy saves between steps); a taken output name becomes name-001; at rung 1 cutout uses its own NumPy flood fill; `export --drop ffffff` leaves out the white background; 86 commands.
- wikiwright trap: a `<!-- outputs: check -->` marker before a block with timings made `outputs` misread later blocks; leave the marker off.
