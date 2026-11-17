# Layered file formats

Checked 2026-11-16. Items marked *unverified* were not confirmed from a primary source in this pass; check before relying on them.

## PSD and PSB

- Adobe publishes the format: *Adobe Photoshop File Formats Specification* (November 2019), https://www.adobe.com/devnet-apps/photoshop/fileformatashtml/ (mirror: https://paulbourke.net/dataformats/psdpsb/psdpsb.html). Five sections: header, colour mode data, image resources, layer and mask information, merged image data. PSB is the same layout with 8-byte lengths in places and up to 300,000 px per side.
- Each layer record stores the signature `8BIM` and a four-byte blend key (`norm`, `mul `, `lum ` ...), opacity, clipping, flags, channel list and an optional mask block (https://leadtools.com/help/sdk/main/api/layerinfo.html, https://www.adobe.com/devnet-apps/photoshop/fileformatashtml/).
- Groups are not a tree in the file: they are flat layers bracketed by a section-divider record (`lsct` additional info, type 1/2 open/closed group, 3 = bounding divider). Text (`TySh`), effects (`lfx2`), adjustment layers (`levl`, `curv`, `hue2` ...) and smart objects (`SoLd`/`PlLd`) are all "additional layer information" blocks keyed by four-letter codes; the descriptor encoding they use is the hard part (same spec).
- Merged image data at the end is the composite most readers show; a writer must supply it (or Photoshop re-composites; other readers may show blank).

### Open readers and writers

| Tool | Licence | Read | Write | Loses / limits | Source |
|---|---|---|---|---|---|
| psd-tools (Python) | MIT | full low-level structure, PSD and PSB | low-level structure; layer list editable | composition of many layer effects limited; no text editing in type layers | https://pypi.org/project/psd-tools/ , https://psd-tools.readthedocs.io/ |
| pytoshop (Python) | BSD-3 *unverified* | yes | yes, raster layers, masks, groups | old, little maintenance *unverified* | https://pypi.org/project/pytoshop |
| PhotoshopAPI (C++ with Python bindings) | BSD-3-Clause | layers, groups, masks, 8/16/32-bit, PSB | yes, fast | no text, effects or adjustment layers | https://photoshopapi.readthedocs.io/ |
| ag-psd (JS/TS) | MIT (mirror; confirm LICENSE on GitHub) | layers, groups, text, adjustment layers, smart objects, vector masks, effects | writes the same tree back | text bitmap not redrawn (Photoshop shows update prompt); no paragraph/character styles; no zip-compressed, indexed, 16-bit or pattern-overlay effects | https://github.com/Agamnentzar/ag-psd |
| GIMP 3 | GPL-3 | layers, groups, masks, most blend modes | layers, groups, masks | text and effects rasterised; adjustment layers dropped *unverified* | https://www.gimp.org/ |
| Krita | GPL-3 | layers, groups, masks, some effects (layer styles) | same | text rasterised; adjustment layers become filter layers or are dropped *unverified* | https://docs.krita.org/en/general_concepts/file_formats/file_psd.html |
| Photopea (web) | proprietary, free with ads | broadest non-Adobe PSD support incl. text, effects, smart objects | PSD | browser only; no licence to embed headless | https://www.photopea.com/ |

## Other layered formats

- **OpenRaster (.ora)**: zip with an uncompressed first entry `mimetype` = `image/openraster`, `stack.xml` (UTF-8, RelaxNG schema), PNG per layer, `mergedimage.png`, `Thumbnails/thumbnail.png`. Stacks nest as groups; `isolation` on stacks; `composite-op` based on SVG compositing (`svg:multiply`, `svg:screen` ... plus non-separable hue/saturation/color/luminosity); `opacity`, `visibility`, `x`, `y`. No masks, text, effects or adjustment layers in the baseline (alpha-preserve and filter effects are proposals). https://www.openraster.org/baseline/layer-stack-spec.html , https://www.openraster.org/proposals/filter-effects.html . Read and written by GIMP, Krita, MyPaint *unverified per app version*.
- **XCF (GIMP native)**: tile-based, zlib in practice, documented in GIMP's source tree (`devel-docs/xcf.txt`, https://gitlab.gnome.org/GNOME/gimp/-/blob/master/devel-docs/xcf.txt). Keeps everything GIMP has (layers, groups, masks, text with markup, paths, GEGL non-destructive filters in GIMP 3). Format changes between versions; no reason to write it ourselves.
- **KRA (Krita native)**: zip with `mimetype`, `maindoc.xml` (layer tree), per-layer tiled binary data and `mergedimage.png` (https://docs.krita.org/en/general_concepts/file_formats/file_kra.html). Keeps filter, fill, clone, vector and file layers, masks. Only Krita reads it fully.
- **Layered TIFF**: baseline TIFF has pages, not layers. Photoshop stores its full layer data in private tag 37724 (`ImageSourceData`), which is PSD layer-and-mask data inside a TIFF (spec above, section "TIFF tag"; `psdtags` reads/writes it: https://www.cgohlke.com/docs/psdtags/). Other apps see only the composite.

## Round-trip table (through the open tool, back to Photoshop)

Y kept, P partly, N lost or rasterised. Based on the sources above; cells marked * are unverified.

| Path | Raster layers | Masks | Blend modes | Groups | Text (editable) | Effects | Adjustment layers |
|---|---|---|---|---|---|---|---|
| psd-tools edit and save | Y | Y | Y | Y | P (kept as blob, not editable) | P (kept, not rendered) | P (kept, not rendered) |
| PhotoshopAPI | Y | Y | Y | Y | N | N* | N* |
| ag-psd | Y | Y | Y | Y | P (warn prompt) | P | Y |
| GIMP 3 open/export PSD | Y | Y | P | Y | N* | N* | N* |
| Krita open/export PSD | Y | Y | P | Y | N* | P* | N* |
| Photopea | Y | Y | Y | Y | Y | Y (most) | Y (most) |
| OpenRaster | Y | N | P (SVG set) | Y | N | N | N |
| Layered TIFF (tag 37724) | Y (via PSD block) | Y | Y | Y | as PSD | as PSD | as PSD |

## Own writers in stdlib + NumPy

**PSD writer, minimal (raster layers, layer masks, opacity, blend modes, groups, merged composite)**: feasible and modest. Needed: big-endian `struct` packing; header; empty colour-mode block; minimal image resources (or none); layer records with channel ids (-1 alpha, 0..2 RGB, -2 user mask); mask block (rect, default colour, flags); blend key from a fixed table; Pascal name padded to 4 bytes plus `luni` Unicode name; `lsct` dividers for groups with the closing `</Layer group>` record; channel data RAW (compression 0), PackBits RLE (1; a short loop over rows) or ZIP (2, or 3 with prediction) via stdlib `zlib`, per the spec's channel image data section; merged image data, which needs our own compositor (we will have one anyway). Estimate: about 400 to 600 lines of Python, one agent session plus tests; verify by reading back with psd-tools and opening in Photopea and Photoshop if present. PSB variant is a flag plus 8-byte lengths. 16-bit is straightforward; 32-bit and CMYK out of scope. Text, effects, adjustment and smart-object layers need the Action Descriptor encoding: do not write these ourselves; keep them by passing through blocks read with psd-tools when editing an existing file.

**ORA writer**: trivial, about 100 lines with `zipfile` and a PNG encoder (`zlib` + `struct`, or Pillow if allowed). Must store `mimetype` first and uncompressed. Good as the honest open interchange; masks need baking into layer alpha.

Recommendation: rung 1 writes ORA and minimal PSD itself; reading arbitrary PSD uses psd-tools (MIT, rung 2); Photopea or Photoshop only to verify.
