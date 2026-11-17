# photowright design note (Step C)

Date: 2026-11-17. Inputs: the 13 files in [references/](../../references/), [kb/tools.json](../../kb/tools.json) (licence rows verified 2026-11-17, two still open), and the tracer bake-off in [notes/bakeoff/](../notes/bakeoff/results.md). Open choices go to Mark on an askwright page; the guesses below stand until he answers.

## 1. The edit recipe

One folder per job:

```
<job>/
  source/            untouched input, read-only by convention; sha256 recorded
  recipe.json        {"version":1, "source":{"file","sha256"}, "steps":[...]}
  masks/             mask PNGs (8-bit, 0-255), written by select/mask steps
  out/               outputs, never written over: name-NNN.ext
  log.jsonl          one line per run: step, rung, tool, tool version, seconds, output hash
```

A step is `{"op":"adjust.curves", "params":{...}, "mask":"masks/sky.png"|null, "layer":"name"|null, "seed":int|null}`. When a step runs, the tool, rung and version are written to log.jsonl. They are not written into recipe.json, so the same recipe can replay on another machine. `phw.py run` replays the recipe and compares output hashes with the last log line. Replaying on the same rung gives identical pixels; a different rung is reported as a drift, not an error. The source file is never opened for writing.

## 2. The core (rung 1)

- Pixels are processed as NumPy float32 in 0..1. Resize, blur, exposure and blending happen in linear light (fundamentals rules R1-R26). Output is converted back to the source profile and bit depth on purpose.
- Rung 1 is Pillow + NumPy. OpenCV, SciPy and scikit-image are already installed here and are permissive, but they count as rung 2 optional backends: no feature may need them unless it has a rung 1 fallback.
- Coverage: by the counts in the rung 1 survey, rung 1 alone covers the adjust, compose (all W3C blend modes plus the Photoshop extras), select (colour, luminance, shape, flood), batch, files (PSD/ORA writer) and pixel-trace groups. Retouch can use simple diffusion fill, and transform covers perspective and resampling. Subject masks, hair matting, large fills and upscaling need rung 3.
- Speed: Pillow and NumPy timings on a 4000x3000 image are in rung1-own-code.md and are fast enough for one-shot edits. Batch work uses the same code.

## 3. Own tools (written by the plugin)

| Piece | Why own | Size (agent estimate) |
|---|---|---|
| Layer compositor + W3C/Photoshop blend modes | Pillow's ImageChops modes do not match the reference formulas | ~300 lines |
| PSD writer (layers, masks, opacity, blend, groups) | psd-tools reads PSD but has limited write support; psdtags is BSD but only covers TIFF tags | ~400-600 lines |
| OpenRaster read/write | tiny zip + XML | ~100 lines |
| Recipe runner, batch, sheet, diff | the plugin's contract | ~300 lines |
| Pixel-exact tracer | measured: overlap 0.9999 on the sprite, and VTracer segfaults on it | ~200 lines (bake-off version is 25) |
| Region tracer with holes + curve fit (Potrace-like, written from the paper only) | rung 1 fallback when VTracer is absent | ~500 lines |
| Vector checker (`vcheck`) and SVG render-back | no SVG rasterizer installed here; the bake-off rasterizer already works | ~200 lines |
| Centreline tracer (skeletonize, then fit) | no permissive tracer does it well (AutoTrace is GPL, external only) | ~250 lines |

Script: `scripts/phw.py`. The name is free; all short names in Ai/ were checked on 2026-11-17.

## 4. Tracer choice (measured, [results.md](../notes/bakeoff/results.md))

| Image | VTracer 0.6.15 | own quant+contour | own pixel-exact |
|---|---|---|---|
| logo | **0.982**, 109 nodes | 0.853 | n/a |
| icon | **0.977**, 137 nodes | 0.452 (holes lost) | n/a |
| line art | **0.951**, 734 nodes | 0.620 | n/a |
| sprite 16x16 at 8x | segfault | 0.947 | **0.9999**, exact squares |
| photo | **0.839**, 13.5k nodes, 639 KB | 0.617 | n/a |

Decisions:
- The default tracer for logos, icons, line art and photos is VTracer (MIT, rung 2, `pip install vtracer`). Each call runs in its own process, because the 0.6.15 binding segfaults in `colormode="binary"` and in `mode="none"` (Windows, Python 3.14). That is a learning and a test.
- Pixel art always goes to the plugin's own pixel-exact tracer.
- The plugin's own region tracer must handle holes (contour hierarchy plus even-odd fill) before it is the fallback. Its bar is overlap ≥ 0.95 on logo and icon.
- Proposed bars: overlap ≥ 0.97 for logo/icon, ≥ 0.94 for line art, ≥ 0.80 for photo, 1.0 (≥ 0.999) for sprites. Node budgets start at 2x the VTracer counts above.
- The Potrace CLI (GPL) is only an optional external program, never bundled. It was not measured because it is not installed and installing a desktop program waits on Mark.

## 5. Model routes (rung 3)

| Job | Default | Licence (kb) | Route | Fallback (rung 1/2) and what it loses |
|---|---|---|---|---|
| click/box select | SAM 2.1 | Apache-2.0 | comfyui-gen or small runner, Windows GPU | colour/flood select: no semantic edges |
| subject cut-out | BiRefNet (already on disk) | MIT | comfyui-gen | GrabCut (OpenCV): poor on hair |
| fill / object removal | LaMa | Apache-2.0 | small runner | Telea/NS inpaint (OpenCV), diffusion fill: smears large holes |
| upscale | Real-ESRGAN | BSD-3 | comfyui-gen | Lanczos in linear light: no new detail (which is honest) |

Excluded as defaults (licence or gate): RMBG-1.4/2.0, MAT, FLUX Fill dev, CodeFormer, 4x-UltraSharp, SAM 3 (Meta-gated), BM3D (non-commercial, moved to rung 3 on 2026-11-17). Model downloads check labwright's free-space floor first.

## 6. Skills

There is one hub (`photowright`) to start, with siblings `photowright-edit` and `photowright-vectorize`. A sibling is split off only if the trigger evals show the hub losing prompts to neighbours. The catalogue lint decides at Step F.

## 7. Scope edges

These stay with the neighbours: critique and ranking (artwright), pixel-art cleanup and sprite animation (pixelwright; photowright only traces pixel art to vectors), brand marks from nothing (brandwright), generating new images (comfyui-gen; photowright calls it for rung 3 models), SVG to mesh or print (polywright). Old-photo repair and object removal move here.

## 8. Open, for Mark (askwright)

1. The name: photowright (guess) or rasterwright.
2. Public or private repo (guess: private until release, then public like its siblings).
3. Is a Photoshop bridge wanted at all, and which version does he have? (guess: build last, off by default)
4. Which of his projects to serve first for Step E (guess: Arvum Electrum sprites for the trace, a family-free photo for retouch)
5. Installing Potrace / Inkscape / GIMP for the comparison runs (guess: no; VTracer and own code only)
