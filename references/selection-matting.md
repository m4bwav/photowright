# Selection and matting

Checked 2026-11-16. Licences read from the GitHub licence API and Hugging Face model metadata on that date.

## Classic methods (rung 1-2, no model)

| Method | What it is | Where |
|---|---|---|
| Colour range / magic wand | Threshold the distance to a sampled colour (Lab beats RGB), globally (colour range) or as a connected flood from the seed (wand) | Pillow `ImageDraw.floodfill`; scikit-image `segmentation.flood` https://scikit-image.org/docs/stable/api/skimage.segmentation.html#skimage.segmentation.flood |
| GrabCut | Iterative graph cut over GMM colour models from a box or scribbles (Rother et al. 2004) | OpenCV `cv2.grabCut` https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html |
| Magnetic lasso / intelligent scissors | Shortest path over an edge-cost graph between clicks (Mortensen and Barrett 1995) | OpenCV `IntelligentScissorsMB` https://docs.opencv.org/4.x/df/d6b/classcv_1_1segmentation_1_1IntelligentScissorsMB.html |
| Luminosity masks | Masks from luminance bands (lights, darks, midtones, intersections) | pure NumPy |
| Closed-form matting | Sparse linear solve from a trimap (Levin et al. 2008) | pymatting (MIT) https://github.com/pymatting/pymatting |
| Guided filter refine | Edge-aware smoothing of a coarse mask against the image (He et al. 2010) | OpenCV contrib `ximgproc.guidedFilter` https://docs.opencv.org/4.x/da/d17/group__ximgproc__filters.html |

Pipeline: a model gives the coarse mask, erode/dilate gives a trimap, a matting step (pymatting or ViTMatte) solves hair. Foreground colour estimation (pymatting `estimate_foreground_ml`) removes fringe halos.

## Open models

| Model | Code | Weights | Default? | Source |
|---|---|---|---|---|
| SAM 2.1 (click/box) | Apache-2.0 | Apache-2.0, ungated | YES, click and box selection | https://github.com/facebookresearch/sam2 , https://huggingface.co/facebook/sam2.1-hiera-large |
| BiRefNet (subject cut-out) | MIT | MIT, ungated | YES, default cut-out | https://github.com/ZhengPeng7/BiRefNet , https://huggingface.co/ZhengPeng7/BiRefNet |
| ViTMatte (trimap matting, hair) | MIT | Apache-2.0 on HF | YES, hair refine | https://github.com/hustvl/ViTMatte , https://huggingface.co/hustvl/vitmatte-small-composition-1k |
| U2-Net / rembg | Apache-2.0 / MIT | U2-Net Apache-2.0 | YES, light CPU fallback | https://github.com/xuebinqin/U-2-Net , https://github.com/danielgatis/rembg |
| IS-Net / DIS | Apache-2.0 | Apache-2.0 (repo) | YES | https://github.com/xuebinqin/DIS |
| InSPyReNet | MIT | MIT (repo) | YES | https://github.com/plemeri/InSPyReNet |
| MODNet (portraits) | Apache-2.0 | Apache-2.0 (repo) | YES, portraits only | https://github.com/ZHKKKe/MODNet |
| RMBG-1.4 | Bria | bria-rmbg-1.4 licence: "source-available model for non-commercial use" | NO | https://huggingface.co/briaai/RMBG-1.4 |
| RMBG-2.0 | Bria | other licence, HF gate, commercial needs a Bria agreement | NO | https://huggingface.co/briaai/RMBG-2.0 |
| SAM 3 | Meta | Meta-gated | NO unless a measured gain | project rule |

rembg bundles several models; only its U2-Net, IS-Net and BiRefNet options qualify, its Bria option does not.

## On disk (D:/ComfyUI, listed 2026-11-16)

- `models/background_removal/birefnet.safetensors` (core ComfyUI background-removal folder).
- `custom_nodes/comfyui_layerstyle` bundles node code for BiRefNet, RMBG (Bria, excluded), SAM2, SAM-HQ, EVF-SAM and LaMa; no weights under `models/sams`, `models/sam2`, `models/rembg`.
- `models/detection/sam_3d_body_dinov3_bf16.safetensors` is Meta SAM 3D Body, not a selection model.
