# Rung 2: free, unrestricted tools

Checked 2026-11-16 on Mark's Windows 11 PC. Rule: open source, no account or key, output sellable; copyleft tools are called as external processes, never bundled or imported into photowright's code. Licences are as stated by each project at the source URL; recheck before a release. Install sizes are approximate Windows installer/package sizes.

## Installed here (probe 2026-11-16)

| Probe | Result |
|---|---|
| `python -c "import cv2"` | OpenCV 5.0.0 |
| `python -c "import skimage"` | scikit-image 0.26.0 (plus SciPy 1.18.1) |
| `python -c "import pyvips"` | missing |
| ffmpeg | yes, 9.0.1 (WinGet Gyan.FFmpeg) |
| magick, vips, gmic, gimp-console*, gimp, krita, inkscape, darktable-cli, rawtherapee-cli, enfuse, enblend, exiftool, potrace, vtracer | none on PATH |

Probe pattern: `Get-Command <exe>` / `where.exe <exe>`, then also check default install folders (`C:\Program Files\<Tool>\bin`) because Windows installers often skip PATH (GIMP, Krita, Inkscape, darktable, RawTherapee). Not done for the folders here beyond PATH.

## Tools

### OpenCV (cv2) - installed
- Licence: Apache 2.0 since 4.5.0. https://opencv.org/license/
- Adds: 10x faster blur/resize than Pillow (see rung1 timings), bilateral, guided and edge-preserving filters, morphology, inpainting (Telea, Navier-Stokes), seamlessClone (Poisson blending), perspective/homography, feature matching and stitching, CLAHE, HDR merge (Debevec, Mertens exposure fusion), denoise (fastNlMeans), contours, GrabCut selection, 16-bit and float32 multi-channel.
- Call: `import cv2` (BGR order, watch it). Install `pip install opencv-python-headless` (~40-60 MB wheel).
- Trap: `cv2.imread` fails silently (returns None) on non-ASCII Windows paths; use `cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_UNCHANGED)`.

### scikit-image - installed
- Licence: BSD-3. https://github.com/scikit-image/scikit-image/blob/main/LICENSE.txt
- Adds: colour spaces (Lab, LCh, HED), exposure (adapt_hist, match_histograms), restoration (denoise_tv, wavelet, rolling ball, unsupervised wiener), segmentation (SLIC, felzenszwalb, watershed, random walker), transform (warps, swirl, radon), feature detection. Pure Python/Cython, slower than OpenCV.
- Install ~30 MB plus SciPy.

### libvips / pyvips - not installed
- Licence: libvips LGPL-2.1-or-later (https://github.com/libvips/libvips/blob/master/LICENSE); pyvips MIT (https://github.com/libvips/pyvips/blob/master/LICENSE.txt).
- Adds: demand-driven streaming, so huge images (gigapixel, deep zoom tiles) in small memory, often the fastest resize/thumbnail; HEIF, JXL, OpenSlide, PDF via poppler; 16-bit and float pipelines.
- Call: `pip install pyvips[binary]` ships prebuilt libvips (~15-20 MB wheel); or Windows zip from GitHub releases (~40 MB) with `vips.exe`. Probe `vips --version`.
- Trap: with the non-binary pyvips on Windows you must add the vips `bin` to PATH or `os.add_dll_directory` before import. LGPL dynamic linking is fine for calling.

### ImageMagick - not installed
- Licence: ImageMagick License (Apache-2.0-style, permissive). https://imagemagick.org/script/license.php
- Adds: 200+ formats, `-compose` blend modes (incl. Photoshop-style ones), distortions, `-fx` expressions, Hald CLUT (`-hald-clut`), `-clut`, montage, text, PSD read/write layers, Q16-HDRI float build.
- Call: IM7 `magick in.png -resize 50% out.png`. Probe `magick -version`. Install ~80-120 MB (Q16-HDRI x64 installer).
- Windows traps: never call bare `convert` (that is `C:\Windows\System32\convert.exe`, the FAT-to-NTFS disk tool); always `magick`. `%` in `-resize 50%` needs `%%` in .bat files. Ghostscript needed separately for PDF/EPS. Policy.xml may block some coders.

### G'MIC - not installed
- Licence: CeCILL (GPL-compatible) for the CLI/plugin, CeCILL-C (LGPL-like) for libgmic. https://gmic.eu/ and https://github.com/GreycLab/gmic/blob/master/COPYING
- Adds: 500+ filters (artistic, frequency separation, inpainting/"patch-based" fill, film emulation CLUT library of ~1000 LUTs, upscalers, denoisers); same filters as the GIMP/Krita plugin.
- Call: `gmic in.png fx_...` or `gmic in.png -blur 3 -o out.png`. Probe `gmic version`. Windows CLI zip ~20-30 MB.
- Trap: syntax changes between majors; pin version in recipes. Copyleft: call externally only.

### GIMP batch mode - not installed
- Licence: GPL-3.0-or-later. https://www.gimp.org/about/
- Adds: XCF, scripted use of any GIMP plugin (incl. G'MIC, Resynthesizer heal-selection, content-aware-ish fill), PSD import/export.
- Call (GIMP 3): `gimp-console-3.0 -i --batch-interpreter python-fu-eval -b "..." --quit`; GIMP 2.10 uses Script-Fu `gimp-console-2.10 -i -b '(...)' -b '(gimp-quit 0)'`. https://developer.gimp.org/resource/script-fu/  Install ~300-400 MB.
- Traps: exe names carry the version; not on PATH by default (`C:\Program Files\GIMP 3\bin`); slow startup (several seconds, font/plugin scan); quoting Python inside `-b` from PowerShell is painful, write a script file.

### Krita scripting - not installed
- Licence: GPL-3.0. https://krita.org/en/about/license/ (GPL per https://invent.kde.org/graphics/krita)
- Adds: painting engine, layers with PSD-like blend modes, KRA/ORA/PSD layered write, animation.
- Call: `krita --export in.kra --export-filename out.png` for conversion; full scripting is Python inside Krita (`krita --nosplash` with a plugin), not true headless. https://docs.krita.org/en/reference_manual/linux_command_line.html  Install ~200-300 MB.
- Trap: scripting needs the GUI process; poor fit for automation beyond export.

### Inkscape CLI - not installed
- Licence: GPL-2.0-or-later. https://inkscape.org/about/license/
- Adds: SVG render/convert to PNG/PDF at any DPI, text to paths, actions pipeline.
- Call (1.x): `inkscape in.svg --export-type=png --export-dpi=300 -o out.png`; `--actions="..."`. https://inkscape.org/doc/inkscape-man.html  Install ~150-200 MB.
- Trap: on Windows use `inkscape.com` (console) not `inkscape.exe` to get stdout; 0.92 flags differ completely from 1.x.

### darktable-cli - not installed
- Licence: GPL-3.0. https://github.com/darktable-org/darktable/blob/master/LICENSE
- Adds: scene-referred RAW development (filmic/sigmoid, colour calibration, denoise profiled, lens correction via lensfun), XMP sidecar recipes.
- Call: `darktable-cli in.CR3 [edits.xmp] out.jpg --core --conf ...`. https://docs.darktable.org/usermanual/stable/en/special-topics/program-invocation/darktable-cli/  Install ~150 MB.
- Trap: a running darktable GUI locks the library; pass `--core --library :memory:` for parallel runs.

### RawTherapee CLI - not installed
- Licence: GPL-3.0. https://github.com/Beep6581/RawTherapee/blob/dev/LICENSE
- Adds: RAW development with .pp3 profiles, excellent demosaic options.
- Call: `rawtherapee-cli -o out.jpg -p profile.pp3 -c in.NEF` (`-c` must be last). https://rawpedia.rawtherapee.com/Command-Line_Options  Install ~100 MB.

### Hugin, enblend, enfuse - not installed
- Licence: GPL-2.0-or-later (Hugin https://hugin.sourceforge.io/ ; enblend-enfuse https://enblend.sourceforge.net/).
- Adds: panorama stitching (`pto_gen`, `cpfind`, `autooptimiser`, `nona`), exposure fusion (`enfuse`), focus stacking (`enfuse --hard-mask --contrast-weight=1`), seam blending (`enblend`). `align_image_stack` aligns brackets.
- Install: Hugin bundle ~60-100 MB includes enblend/enfuse. Trap: not on PATH; tools live in `C:\Program Files\Hugin\bin`. OpenCV's Mertens fusion covers simple exposure fusion at rung 1.5 without it.

### ExifTool - not installed
- Licence: same as Perl (Artistic or GPL). https://exiftool.org/#license
- Adds: read/write every metadata standard (EXIF, XMP, IPTC, ICC, maker notes), strip metadata, copy tags, AI-provenance/C2PA-adjacent XMP fields.
- Call: `exiftool -j in.jpg` (JSON); `exiftool -all= -o out.jpg in.jpg`. Install ~10 MB.
- Windows trap: the download is `exiftool(-k).exe`; rename to `exiftool.exe` or it waits for a keypress. Since 12.88 the zip includes an `exiftool_files` folder that must sit next to the exe.

### potrace / vtracer - not installed
- potrace: GPL-2.0-or-later, bitmap to vector (B/W). https://potrace.sourceforge.net/  ~1 MB. Input must be PBM/BMP.
- vtracer: MIT, colour raster to SVG. https://github.com/visioncortex/vtracer  `pip install vtracer` or `vtracer --input in.png --output out.svg`. ~5 MB.

### Other notable
- **ffmpeg** (installed): LGPL-2.1+ / GPL depending on build (the Gyan "full" build is GPL). https://ffmpeg.org/legal.html  Good for format conversion, image sequences, `lut3d` filter (applies .cube), `zscale` colour transforms.
- **libjxl `cjxl`/`djxl`**: BSD-3, JPEG XL encode. https://github.com/libjxl/libjxl
- **oxipng / pngquant**: oxipng MIT (https://github.com/shssoichiro/oxipng) lossless PNG shrink; pngquant is GPL-3 (https://pngquant.org/) lossy palette, call externally.
- **mozjpeg `cjpeg`**: BSD-style IJG licence, smaller JPEGs. https://github.com/mozilla/mozjpeg
- **OpenImageIO `oiiotool`**: Apache 2.0, EXR/HDR and OCIO colour-managed pipelines. https://github.com/AcademySoftwareFoundation/OpenImageIO
- **LibreOffice/Scribus**: out of scope (layout).
- Models (rembg, upscalers, inpainting nets) belong to rung 3, not here.

## Design findings
1. OpenCV + scikit-image are already installed and permissive: make them the default rung-2 path (pip-installable, in-process, no copyleft).
2. Everything copyleft (GIMP, Krita, Inkscape, G'MIC CLI, darktable, RawTherapee, Hugin, potrace, pngquant, GPL ffmpeg) is subprocess only, probed at runtime, never vendored.
3. The probe must look in Program Files as well as PATH, and must never call bare `convert`.
4. ImageMagick and pyvips[binary] are the best two installs to suggest: small, permissive, and they fill big gaps (formats, PSD layers, huge images).
5. RAW development is only available via darktable-cli or RawTherapee (both GPL, external); recipes should store their XMP/.pp3 sidecars so edits are reproducible.
