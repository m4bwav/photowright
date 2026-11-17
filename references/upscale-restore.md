# Upscale, denoise, restore

Checked 2026-11-16.

## Resampling done right (rung 1)
- Decode sRGB to linear light, resize, encode back; resizing gamma-encoded values darkens fine detail. https://www.ericbrasseur.org/gamma.html
- Downscaling needs a kernel widened by the scale factor (antialiasing); Pillow's `resize` does this. https://pillow.readthedocs.io/en/stable/handbook/concepts.html#filters
- Lanczos-3 for photos, nearest for pixel art; premultiply alpha before resampling. https://www.libvips.org/API/current/libvips-resample.html
- Recovered vs invented: classic resampling invents nothing. Any model output is flagged invented in the recipe; measure it by downscaling the result back to source size and diffing against the source (large residual = hallucinated detail), and keep the source as its own layer.

## Denoise
| Tool | Licence | Default? | Source |
|---|---|---|---|
| Non-local means | OpenCV Apache-2.0 | YES | https://docs.opencv.org/4.x/d5/d69/tutorial_py_non_local_means.html |
| BM3D (`bm3d` package) | own terms, not verified commercial | NO until checked | https://pypi.org/project/bm3d/ |
| SCUNet | Apache-2.0 | YES | https://github.com/cszn/SCUNet |
| NAFNet | MIT | YES | https://github.com/megvii-research/NAFNet |

## Upscalers
| Model | Licence | Default? | Source |
|---|---|---|---|
| Real-ESRGAN (x4plus, anime6B) | BSD-3-Clause, weights in repo releases | YES | https://github.com/xinntao/Real-ESRGAN |
| SwinIR | Apache-2.0 | YES | https://github.com/JingyunLiang/SwinIR |
| HAT | Apache-2.0 | YES | https://github.com/XPixelGroup/HAT |
| 4x-UltraSharp | CC BY-NC-SA 4.0 | NO | https://openmodeldb.info/models/4x-UltraSharp |

Community upscalers on OpenModelDB each carry their own licence; check per model. https://openmodeldb.info/

## Face and old-photo restore
| Model | Licence | Default? | Source |
|---|---|---|---|
| GFPGAN | Apache-2.0 (third-party parts listed in LICENSE) | YES, flagged invented | https://github.com/TencentARC/GFPGAN/blob/master/LICENSE |
| CodeFormer | S-Lab License 1.0, non-commercial | NO | https://github.com/sczhou/CodeFormer/blob/master/LICENSE |
| Bringing Old Photos Back to Life | MIT | YES (old stack, heavy setup) | https://github.com/microsoft/Bringing-Old-Photos-Back-to-Life |

Face restorers change identity; output them as a separate masked layer flagged invented.

## On disk
`models/upscale_models` is empty. Only video latent upscalers (LTX, MiniMax H3). Face locators present: `ultralytics/bbox/face_yolov8m.pt`, `detection/mediapipe_face_fp32.safetensors`.
