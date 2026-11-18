# Relight live run (2026-11-18, session 39)

First live run of `phw relight --method iclight` on 8199 (idle, 0 jobs ahead). Source: photowright-jobs/1-retouch/src/crashsite_fin_t95.png (864x480, dusk, plane tail). Outputs and sheet: D:/m4bwa/Claude/Projects/Ai/photowright-jobs/5-relight/.

| take | rung | time | result |
|---|---|---|---|
| `--prompt "warm sunset light, soft shadows" --light left --seed 7` | 3 | 13.5 s (cold load) | warm low sun from the left, sky and grass repainted; PSNR vs source 15.51 dB, 99.8% of pixels changed |
| `--prompt "cold blue moonlight" --light right --seed 7` | 3 | 4.1 s (warm) | blue night grade, bright frosted grass on the right |
| `--method own --light left` | 1 | <1 s | directional brightness ramp only, source otherwise kept |

Findings:
- The route works end to end with no code change; the work size (768x448) is upscaled back to 864x480.
- IC-Light (SD1.5) invents detail: the tail's markings are lost and the grass texture is new. The `invented_detail: true` step flag and the "check faces, text and fine detail" note are right; do not use it where the subject's detail must survive (logos, faces, text) without a mask-back.
- Possible follow-up (not built): `--keep-detail`, which puts the source's high frequencies back over the relit low frequencies (frequency separation exists in `detail`), so only the lighting changes.

## --keep-detail (0.24.0, session 40)

Same source, prompt, light and seed, 8199 idle. Measures vs source: PSNR, and correlation of the 4 px high-pass bands.

| run | PSNR | high-pass corr | mean RGB shift |
|---|---|---|---|
| `--keep-detail 0` (plain IC-Light) | 14.26 dB | 0.455 | +0.127 +0.109 +0.095 |
| `--keep-detail 4` | 14.32 dB | 0.965 | +0.127 +0.109 +0.095 |

The lighting is identical; the car, tail emblem and cloud wisps come back. A faint halo shows along the tail's edge against the sky, where the relit lows change sharply. Outputs and crop sheet: photowright-jobs/5-relight/kd0.png, kd4.png, kd-sheet.png.
