# Retouch and fill

Checked 2026-11-16.

## Algorithms (rung 1-2)

| Method | Use | Source |
|---|---|---|
| Poisson / seamless clone | Healing brush: copy texture, match colour in the gradient domain to the border (Perez et al. 2003) | OpenCV `seamlessClone` https://docs.opencv.org/4.x/df/da0/group__photo__clone.html |
| Telea fast marching | Dust, scratches, thin wires | OpenCV `INPAINT_TELEA` https://docs.opencv.org/4.x/df/d3d/tutorial_py_inpainting.html |
| Navier-Stokes | Same scale as Telea, smoother | OpenCV `INPAINT_NS` (same page) |
| PatchMatch | Randomised nearest-patch search, the basis of Content-Aware Fill (Barnes et al. 2009, Adobe co-authors) | https://gfx.cs.princeton.edu/pubs/Barnes_2009_PAR/ |
| Exemplar-based (Criminisi 2004) | Patch fill in priority order along isophotes, keeps straight lines | https://www.microsoft.com/en-us/research/publication/region-filling-and-object-removal-by-exemplar-based-image-inpainting/ |
| Biharmonic | Smooth fill | https://scikit-image.org/docs/stable/auto_examples/filters/plot_inpaint.html |

Content-Aware Fill samples pixels from the rest of the image with a user-editable sampling area; Generative Fill is the Firefly model instead. https://helpx.adobe.com/photoshop/using/content-aware-fill.html

When code beats a model: small holes, textures (sky, grass, wall), dust and scratches, repeating patterns; deterministic and pixel-exact outside the mask, no GPU. Use a model for large holes, structure across the hole, or semantic content (people, faces).

## Models (rung 3)

| Model | Code | Weights | Default? | Source |
|---|---|---|---|---|
| LaMa / big-lama | Apache-2.0 | Apache-2.0 | YES, object removal | https://github.com/advimman/lama , https://huggingface.co/smartywu/big-lama |
| MAT | CC BY-NC 4.0 | CC BY-NC 4.0 | NO, non-commercial | https://github.com/fenglinglwb/MAT/blob/main/LICENSE |
| SD 1.5 inpainting | CreativeML OpenRAIL-M | OpenRAIL-M (use restrictions, commercial allowed) | YES, with use rules | https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-inpainting |
| SDXL inpainting 0.1 | OpenRAIL++ | OpenRAIL++, ungated | YES, generative fill | https://huggingface.co/diffusers/stable-diffusion-xl-1.0-inpainting-0.1 |
| Fooocus inpaint patch | OpenRAIL | OpenRAIL | YES, with SDXL | https://huggingface.co/lllyasviel/fooocus_inpaint |
| FLUX.1 Fill [dev] | FLUX.1 [dev] non-commercial licence | gated | NO | https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev |

Every generative fill goes into the recipe flagged as invented, with model and seed.

## On disk
No `models/inpaint` folder. `comfyui_layerstyle` has a LaMa node (`py/lama.py`); no weights present.

## Fill routing (phw 0.7.0)

Thin defects (scratches, wires, dust) go to diffusion inpainting (`fill --method membrane` or `telea`); texture (grass, gravel, wall) to patch fill (`--method patch`); holes that cross straight lines to priority-ordered exemplar fill (patch, structure first); big semantic holes (a person, a car) to a model (`--model lama`, rung 3), or by instruction (`--model qwen-edit --prompt "..."`, rung 3, invents content). Source: Szeliski, Computer Vision: Algorithms and Applications, 2nd ed. (2022), https://szeliski.org/Book/.
