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
