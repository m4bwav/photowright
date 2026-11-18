# Szeliski, Computer Vision: Algorithms and Applications (2nd ed.): what it means for photowright

Read 2026-11-17 (chapters 2, 3, 8 and 10; 7 and 9 by title only). Full paraphrased notes, section list and checks:
D:/m4bwa/Claude/Projects/Ai/technique-harvest/ai-docs/books/szeliski-cvaa-2e/notes.md. The PDF is personal-use
only and stays in technique-harvest/books-cache; nothing from it is copied here.

Most of the book's classic methods are already in phw (linear light, premultiplied neighbour filters, Lanczos,
Laplacian-pyramid stacks, Poisson heal, PatchMatch and exemplar fill, RDP simplify). What it adds is reasons and
failure modes. Every rule below is "book rule, unverified" until a phw test agrees.

## Proposed changes (all built in phw 0.7.0, 2026-11-17; tests in tests/test_phw6.py)

1. BUILT: adjust: curves, levels and gamma applied to luminance by default on colour images (per-channel washes colour
   out); keep per-channel as an option. Check: chroma on a colour chart after a strong gamma.
2. BUILT: adjust: equalisation with a strength 0..1 and a tiled local mode whose tile curves are interpolated (no block
   seams).
3. BUILT: denoise: a bilateral method that compares whole colours in Lab (per-band comparison fringes colour).
4. BUILT: perspective and warp: prefilter where the warp shrinks the image by more than about 2x (inverse mapping alone
   aliases). Check: zone plate shrunk 4x against a prefiltered reference.
5. BUILT: resize: Pillow's bicubic already uses a = -0.5 (reproduces ramps); document it, no code change.
6. BUILT: compose: a pyramid blend option for pastes whose exposures differ (a plain feather leaves a step).
7. BUILT: stack: a per-pixel median mode for clean plates (people walking through aligned frames).
8. BUILT: fill routing (docs): thin defects to diffusion inpainting, texture to patch fill, holes across straight lines to
   priority-ordered exemplar fill, big semantic holes to a model.
9. BUILT: stitch (docs): flat projection only under about 90 degrees of view; cylindrical or spherical beyond.
10. BUILT: upscale: any single-image super-resolution is invented detail and is flagged in the recipe like generative fill.

Not changed: seam carving stays out (patent flag); the stitcher stays OpenCV (the book's graph-cut seams and bundle
adjustment are what the Stitcher already does).
