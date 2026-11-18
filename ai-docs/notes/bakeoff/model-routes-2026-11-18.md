# Model routes bake-off: SeedVR2 upscale and qwen-edit fill (2026-11-18)

Status: **GPU half MEASURED 2026-11-18 (session 35, 8199 idle).** Results in the section below. Earlier status: 127.0.0.1:8199 was idle at the start (queue empty), but a MiniMax H3
render from another session started within a minute of the first SeedVR2 submit and held the GPU
(15.4 GB, 100 %) past the 10-minute wait limit. The client was stopped; the SeedVR2 prompt for
`text_small.png` stayed in the ComfyUI queue (deleting it was refused by the permission layer), so it
will run after the H3 job and its output is unused. qwen-edit and `--model lama` were not submitted.

2026-11-18 (session 29, second run): 8199 busy again at start (H3 render in `queue_running`); GPU routes still unmeasured.

## Test images
- `astronaut.png` 512x512: skimage.data.astronaut (NASA photo, public domain).
- `coffee.png` 400x400 crop of skimage.data.coffee (CC0, Rachel Michetti).
- `text.png` 512x384: plugin-made test card (Pillow, Arial 28 and 14 px on a grey ramp).
Each was downscaled 4x with Pillow LANCZOS, then upscaled 4x back; metrics vs the original (skimage 0.26).

## CPU baselines (done)
| image | Lanczos 4x PSNR | SSIM | invented-detail flag |
|---|---|---|---|
| text | 18.20 | 0.7465 | False |
| astronaut | 25.23 | 0.8166 | False |
| coffee | 24.73 | 0.7391 | False |
Lanczos runtime: ~0.4 s per image (CLI wall).

Fill rung 1 (auto -> own PatchMatch, patch 7, 5 levels) on astronaut, rect 300,60,60,60:
changed px outside the mask 0; inside 3599/3600; seam border 0.0529, around 0.0197, ratio 2.68.

## To run when 8199 is idle
Same files, same commands (scratch script recreates them from skimage + Pillow):
`phw upscale X_small.png --scale 4 --method seedvr2`, sample `nvidia-smi` each second, and
`phw fill astronaut.png --rect 300,60,60,60 --model qwen-edit --prompt "fill with the background"` and
`--model lama`; compare to the table above. Check the queue holds nothing else first (`/queue`) and
re-check right before each submit: H3 renders start without warning.

## GPU results (session 35, 8199 idle, queue empty before each submit)
SeedVR2 3B int8 (`seedvr2_3b_int8_convrot`), seed 0, 4x from the same `_small.png` files:
| image | SeedVR2 PSNR | SSIM | vs Lanczos | wall (first run loads the model) |
|---|---|---|---|---|
| text | 25.46 | 0.8755 | +7.3 dB, +0.13 SSIM | 25 s (22.6 s server) |
| astronaut | 22.74 | 0.7608 | -2.5 dB, -0.06 | 7 s |
| coffee | 24.75 | 0.7164 | +0.0 dB, -0.02 | 2 s |
Reading: SeedVR2 wins clearly on text and hard edges; on photos it invents texture, so pixel metrics
drop or tie while it may look sharper. Keep `--method auto` on Lanczos and SeedVR2 opt-in with the
invented-detail flag, as built.

Fill on astronaut rect 300,60,60,60 (seam border / around = ratio; lower is better, own = 2.68):
| route | changed outside mask | inside | ratio | wall |
|---|---|---|---|---|
| `--model lama` | 0 | 3594/3600 | **1.565** | 11 s |
| `--model qwen-edit --prompt "fill with the background"` | 0 | 3594/3600 | 9.15 | 33 s |
Reading: LaMa beats the own PatchMatch seam (1.57 vs 2.68); qwen-edit leaves a visible seam (9.15) on a
small removal, so it stays for prompted, content-changing fills only. Recommended: when a rung 3 fill is
allowed and no prompt is given, prefer lama. Both keep every pixel outside the mask.
