# ComfyUI nodes and workflows as rung 3 backends

Checked 2026-11-17. Read-only survey: nothing installed. Rung 3 test: open weights, licence allows commercial use, no account, key or HF gate, no non-commercial clause; Meta-gated only with a clear measured gain.

Licences: node packs from the GitHub API (`spdx_id`), weights from the Hugging Face API tags and `gated` field, or the LICENSE file where named. Model rows already in [selection-matting.md](selection-matting.md), [retouch-fill.md](retouch-fill.md), [upscale-restore.md](upscale-restore.md) and [vectorize.md](vectorize.md) are referenced, not re-researched.

Note on GPL node packs: a GPL-3.0 node pack runs inside the user's ComfyUI; photowright only sends it a workflow over HTTP, so photowright's own licence is untouched. The pack's licence matters only if photowright vendors its code.

## Local install (D:/ComfyUI, 2026-11-17)

- Custom nodes relevant here: `comfyui_layerstyle` (LayerStyle: has BiRefNet, SAM, matting, colour nodes; the companion `LayerStyle_Advance` pack holds most AI nodes and is NOT installed), `comfyui_essentials` (image ops, remove background helpers), `comfyui-kjnodes`. No RMBG, SAM2, Florence2, inpaint-nodes, BrushNet, SUPIR, IC-Light, Depth Anything, ToSVG or layerdiffuse packs.
- Models already on disk: `background_removal/birefnet.safetensors` (core ComfyUI background removal node), `diffusion_models/qwen_image_edit_2509_int8`, `qwen_image_edit_2511_fp8` (two builds), `qwen_image_layered_fp8mixed`, `flux-2-klein-4b`, `flux-2-klein-base-4b`, `flux-2-klein-9b-fp8`, `seedvr2_3b_int8` and `seedvr2_7b_int8`, `pid_flux1/flux2_1024_to_4096` (upscale-in-latent, licence not checked here), `rt_detr_v4` detector, `upscale_models/` folder exists (contents not listed in detail).

## Wired in phw 0.6.0 (2026-11-17)

Node classes from GET /object_info on the live server: `LoadBackgroundRemovalModel` (bg_removal_name) + `RemoveBackground` -> MASK; `INPAINT_LoadInpaintModel` (model_name) + `INPAINT_InpaintWithModel` (inpaint_model, image, mask, seed); `Florence2ModelLoader` (model "Florence-2-large", reads models/LLM, no download) + `Florence2Run` (task caption_to_phrase_grounding, seed min 1, output 3 = JSON) + `Florence2toCoordinates` (index "" = every box) + `DownloadAndLoadSAM2Model` (sam2.1_hiera_base_plus.safetensors is on disk, so no download) + `Sam2Segmentation` (bboxes). Masks go in as a grey PNG through `LoadImage` + `ImageToMask` (red) and come back through `MaskToImage` + `PreviewImage` (temp folder, nothing left in output/). Code: scripts/phw/comfy.py. SeedVR2 upscale (2026-11-18): core nodes `SeedVR2Preprocess` + `VAEEncodeTiled` (vae `seedvr2_ema_vae_fp16.safetensors`) + `SeedVR2Conditioning` + `KSampler` (1 step, cfg 1, euler/simple) + `VAEDecodeTiled` + `SeedVR2PostProcessing` (lab), after the core blueprint `blueprints/Upscale Video (SeedVR2 3B Int8).json` minus its video and temporal-chunk nodes; unet `seedvr2_3b_int8_convrot` or `seedvr2_7b_int8_convrot` (diffusion_models on the Windows box only; the Mac has the nodes but no weights). Qwen-Image-Edit-2511 fill by instruction (phw 0.7.1, 2026-11-18, nodes checked on /object_info): `UNETLoader` (`qwen_image_edit_2511_fp8mixed.safetensors`) + `LoraLoaderModelOnly` (`Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors`) + `ModelSamplingAuraFlow` (shift 3.1) + `CFGNorm`; `CLIPLoader` (`qwen_2.5_vl_7b_fp8_scaled.safetensors`, type `qwen_image`); `VAELoader` (`qwen_image_vae.safetensors`); `TextEncodeQwenImageEditPlus` (clip, prompt, vae, image1) for positive and empty negative, each through `FluxKontextMultiReferenceLatentMethod` (`index_timestep_zero`); image and mask through `ImageScaleToTotalPixels` (1 MP, steps 8), `VAEEncode` + `SetLatentNoiseMask`, `KSampler` 4 steps cfg 1 euler/simple, `VAEDecode`. phw resizes the result back (Lanczos) and composites through the mask. It refuses a queue with jobs ahead (`PHW_COMFY_MAX_AHEAD`, default 0) instead of waiting. Live run not measured yet. Other installs (IC-Light, controlnet_aux DA-V2 Small, layerdiffuse) are installed but not wired yet.

## Table

| Backend | Node pack (licence) | Model weights (licence, gate) | Size (approx.) | Rung 3 | photowright command | Installed |
|---|---|---|---|---|---|---|
| Core "Remove background" + BiRefNet | ComfyUI core (GPL-3.0) | BiRefNet MIT, ungated; BiRefNet_HR-matting MIT | ~0.9 GB | PASS | cutout | YES (birefnet.safetensors); WIRED in phw 0.6.0 (`cutout --model birefnet`) |
| ComfyUI-RMBG (1038lab), 2.2k stars, active | GPL-3.0 | bundles many: BiRefNet (MIT) PASS, SAM2 PASS, GroundingDINO PASS; RMBG-2.0 FAIL (Bria, gated, NC), RMBG-1.4 FAIL (NC), InSPyReNet PASS | per model 0.2-1 GB | PASS only with an allow-list of models | cutout, select subject, select by text | no |
| ComfyUI-segment-anything-2 (kijai) | Apache-2.0 | SAM 2.1 Apache-2.0, ungated | 0.15-0.9 GB | PASS | select (click/box), video masks | YES (2.1 base_plus, large); WIRED in phw 0.6.0 (`select --text`, base_plus) |
| ComfyUI-Florence2 (kijai) | MIT | Florence-2-large MIT, ungated | ~1.5 GB | PASS | select by text (grounding boxes, then SAM 2.1), captions | YES (models/LLM/Florence-2-large); WIRED in phw 0.6.0 (`select --text`) |
| comfyui_segment_anything (storyicon): GroundingDINO + SAM | Apache-2.0 | GroundingDINO-base Apache-2.0, ungated; SAM 1 Apache-2.0 | ~0.9 GB + SAM | PASS | select by text | no |
| comfyui-inpaint-nodes (Acly) | GPL-3.0 | LaMa Apache-2.0 PASS; Fooocus patch OpenRAIL PASS; MAT CC BY-NC FAIL | LaMa ~0.2 GB, Fooocus ~1.3 GB + SDXL | PASS (LaMa, Fooocus+SDXL); not MAT | fill / remove | YES (big-lama.pt only); WIRED in phw 0.6.0 (`fill`/`remove --model lama`) |
| ComfyUI-BrushNet (nullquant) | Apache-2.0 | BrushNet SDXL/SD1.5 weights: licence not verified on a card (code Apache-2.0); needs an SD base (OpenRAIL) | ~1.5-2.5 GB | UNVERIFIED | fill (generative) | no |
| Qwen-Image-Edit-2511 (core nodes) | ComfyUI core | Apache-2.0, ungated | fp8 ~20 GB + text encoder | PASS | fill / remove by instruction, relight by prompt, restore | YES (2511 fp8mixed + Lightning 4-step LoRA, qwen_2.5_vl_7b_fp8_scaled, qwen_image_vae); WIRED in phw 0.7.1 (`fill`/`remove --model qwen-edit --prompt`) |
| Qwen-Image-Layered (core) | ComfyUI core | Apache-2.0, ungated | fp8 ~20 GB | PASS | layer decomposition (split to PSD layers) | YES |
| FLUX.2 klein 4B (edit, core) | ComfyUI core | Apache-2.0, ungated | ~8 GB | PASS | fill, edit, relight by reference | YES |
| FLUX.2 klein 9B | ComfyUI core | "other" (FLUX non-commercial), HF gated | ~9 GB fp8 | FAIL | - | YES (keep out of photowright) |
| FLUX.1 Kontext dev / FLUX.1 Fill dev | ComfyUI core | FLUX.1 dev NC licence, gated | ~12-24 GB | FAIL | - | no |
| SeedVR2 3B / 7B (numz ComfyUI-SeedVR2_VideoUpscaler, or core) | Apache-2.0 | Apache-2.0, ungated | 3B ~7 GB, 7B ~16 GB (int8 smaller) | PASS | upscale, restore (one-step diffusion SR, works on stills) | YES (weights) |
| ComfyUI_UltimateSDUpscale (ssitu) | GPL-3.0 | depends on base: SDXL OpenRAIL++ PASS; with Real-ESRGAN/SwinIR/HAT PASS; 4x-UltraSharp FAIL | - | PASS with a PASS base | upscale (tiled, big images) | no |
| ComfyUI-SUPIR (kijai) | NOASSERTION | SUPIR: SupPixel proprietary licence, non-commercial | ~5 GB + SDXL | FAIL | - | no |
| DiffBIR | Apache-2.0 (code) | weights v2.1 licence not verified on a card | ~5 GB | UNVERIFIED | restore | no |
| CodeFormer face restore nodes | various | S-Lab NC | - | FAIL | - | no |
| GFPGAN (via ComfyUI core upscale/face nodes or ReActor-style packs) | - | Apache-2.0 | 0.35 GB | PASS (flag invented detail) | restore faces | no |
| ComfyUI-IC-Light (kijai) / IC-Light-Native (huchenlei) | Apache-2.0 both | IC-Light v1 (SD1.5): HF card front matter creativeml-openrail-m, ungated; IC-Light v2 (Flux) not open | ~1.7 GB + SD1.5 | PASS (v1 only) | relight | no |
| ComfyUI-DepthAnythingV2 (kijai) | no licence file (all rights reserved by default) | V2-Small Apache-2.0 PASS; V2-Base and V2-Large CC BY-NC-4.0 FAIL | Small ~0.1 GB | Model PASS (Small only); use via comfyui_controlnet_aux instead | depth for relight | no |
| comfyui_controlnet_aux (Fannovel16) | Apache-2.0 | depth (DA-V2 Small PASS), normal maps (DSINE: check), lineart | small | PASS for Small depth | depth / normal for relight | no |
| ComfyUI-ToSVG (Yanick112) | MIT | none: wraps VTracer (MIT) | tiny | PASS | trace (colour) | no |
| ComfyUI-layerdiffuse (huchenlei) | Apache-2.0 | layerdiffusion-v1 creativeml-openrail-m, ungated | ~0.7 GB + SDXL/SD1.5 | PASS | generate transparent layers, foreground/background split | no |
| StarVector 1B im2svg (no mature ComfyUI pack seen) | Apache-2.0 | Apache-2.0, ungated | ~3 GB | PASS (outside ComfyUI) | trace icons/diagrams | no |

## Recommendations

1. Already usable today, no install: core background removal with the installed BiRefNet (cutout), Qwen-Image-Edit-2511 (fill/remove/edit by instruction), Qwen-Image-Layered (layer split), FLUX.2 klein 4B (edit), SeedVR2 3B/7B (upscale and restore).
2. Small installs that pass: kijai ComfyUI-segment-anything-2 + ComfyUI-Florence2 (text-prompted selection: Florence-2 boxes into SAM 2.1); Acly comfyui-inpaint-nodes with LaMa and Fooocus (classic remove/fill); ComfyUI-ToSVG (VTracer in a graph); kijai or huchenlei IC-Light (v1) with Depth Anything V2 Small from comfyui_controlnet_aux.
3. ComfyUI-RMBG is the most active cut-out pack but ships failing models (RMBG-2.0, RMBG-1.4); photowright must pin an allow-list (BiRefNet, InSPyReNet, SAM2, GroundingDINO) and refuse the Bria rows.

## Fail list

FLUX.1 Fill/Kontext dev and FLUX.2 klein 9B (BFL non-commercial, gated); SUPIR (SupPixel non-commercial); CodeFormer (S-Lab NC); MAT (CC BY-NC); RMBG-1.4/2.0 (Bria NC, 2.0 gated); Depth Anything V2 Base/Large (CC BY-NC); 4x-UltraSharp (CC BY-NC-SA). Unverified: BrushNet weights, DiffBIR weights, IC-Light v1 (card is a front-matter stub only), kijai DepthAnythingV2 pack (no licence file), the installed `pid_flux*` upscalers.

## Sources

- GitHub API `repos/<owner>/<repo>` license field, 2026-11-17: 1038lab/ComfyUI-RMBG, kijai/ComfyUI-segment-anything-2, kijai/ComfyUI-Florence2, storyicon/comfyui_segment_anything, Acly/comfyui-inpaint-nodes, nullquant/ComfyUI-BrushNet, kijai/ComfyUI-SUPIR, ssitu/ComfyUI_UltimateSDUpscale, kijai/ComfyUI-IC-Light, huchenlei/ComfyUI-IC-Light-Native, kijai/ComfyUI-DepthAnythingV2, Yanick112/ComfyUI-ToSVG, huchenlei/ComfyUI-layerdiffuse, chflame163/ComfyUI_LayerStyle, Fannovel16/comfyui_controlnet_aux, numz/ComfyUI-SeedVR2_VideoUpscaler, XPixelGroup/DiffBIR, ByteDance-Seed/SeedVR.
- Hugging Face API `api/models/<id>` tags and gated, 2026-11-17: depth-anything/Depth-Anything-V2-{Small,Base,Large}, microsoft/Florence-2-large, IDEA-Research/grounding-dino-base, Qwen/Qwen-Image-Edit-2511, Qwen/Qwen-Image-Layered, black-forest-labs/FLUX.1-Kontext-dev, black-forest-labs/FLUX.2-klein-{4B,9B}, ByteDance-Seed/SeedVR2-{3B,7B}, LayerDiffusion/layerdiffusion-v1, ZhengPeng7/BiRefNet_HR-matting, lllyasviel/ic-light (README front matter), starvector/starvector-1b-im2svg.
- SUPIR LICENSE: https://github.com/Fanghua-Yu/SUPIR/blob/master/LICENSE (SupPixel proprietary).
