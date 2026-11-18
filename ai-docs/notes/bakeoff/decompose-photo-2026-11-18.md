# decompose on a true photograph, with and without --prompt (2026-11-18)

Question: does a caption (`--prompt`) help Qwen-Image-Layered separate a real photo? Session 44 ran a game still and got coverage [1,1,1,0] (an opaque layer hid the rest), 32.6 dB, about 210 s.

## Image

"Bison grazing near Roosevelt Arch in the spring (41562271481).jpg", Yellowstone National Park (NPS), public domain (US government work).
Source: https://commons.wikimedia.org/wiki/File:Bison_grazing_near_Roosevelt_Arch_in_the_spring_(41562271481).jpg
Fetched as the 960 px Commons thumbnail, resized to 864x576 (Lanczos). Six bison in the foreground, the stone arch mid-distance, hills and a snowy slope behind. No people.

Files (outside the repo): `D:/m4bwa/Claude/Projects/Ai/photowright-jobs/decompose-photo/` (bison-864.png, noprompt.psd, prompt.psd, PNG layers and contact sheets).

## Runs

`python scripts/phw.py decompose bison-864.png --layers 4 --seed 7 -o X.psd --png X`, phw 0.25.1, ComfyUI 127.0.0.1:8199 (queue empty before each run), worked at 784x528, 20 steps.

| run | prompt | alpha coverage per layer | recomposite PSNR | hidden/empty notes | wall time |
|---|---|---|---|---|---|
| no prompt | (none) | 1.0, 0.057, 0.023, 0.054 | 27.92 dB | none | 215 s |
| caption | "Five American bison grazing on a dry grassy plain in the foreground; a stone arch gateway in the middle distance; rolling tan hills and a snowy mountain slope in the background." | 1.0, 0.063, 0.018, 0.053 | 28.21 dB | none | 224 s |

Both runs: layer 1 is the whole background (plain, arch, hills, mountain, bison removed and the ground painted in); layers 2-4 hold the six bison as clean cutouts, 1-2 per layer. The caption changed which bison went into which layer and nothing else. The arch was never split from the background in either run, even though the caption named it as a separate depth band. The caption also said five bison when there are six, and the model kept all six.

## Verdict

A caption does not help here. A true photo with distinct subjects separates well without one (unlike the game still in session 44), and the caption gives the same split, PSNR within 0.3 dB and about 4% more time. One image, one seed, so this is a single data point: try `--prompt` only when a run without it comes back with a hidden or empty layer, and do not expect it to pull out mid-ground structures. Recomposite PSNR on a photo (about 28 dB) is lower than on flat renders (32-36 dB) because the model repaints texture.
