# Image fundamentals an editor must get right

Checked 2026-11-16. Each section ends with the rules photowright code must follow (R-numbers) and how Pillow handles that part.

Main sources (fetched 2026-11-16 unless marked):
- W3C Compositing and Blending Level 1: https://www.w3.org/TR/compositing-1/
- W3C PNG Third Edition: https://www.w3.org/TR/png-3/
- Pillow file formats: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html
- Pillow ImageCms: https://pillow.readthedocs.io/en/stable/reference/ImageCms.html
- Pillow ImageOps: https://pillow.readthedocs.io/en/stable/reference/ImageOps.html
- Pillow Image: https://pillow.readthedocs.io/en/stable/reference/Image.html
- Pillow concepts (modes, RGBa): https://pillow.readthedocs.io/en/stable/handbook/concepts.html
- sRGB: IEC 61966-2-1; transfer function as given at https://en.wikipedia.org/wiki/SRGB (not refetched)

## 1. Colour spaces and ICC profiles

- An ICC profile maps a device's numbers to a profile connection space (XYZ or Lab, D50). Converting between two profiles goes source -> PCS -> destination with a rendering intent. Source: https://www.color.org/iccprofile.xalter
- Pillow's ImageCms (LittleCMS) supports four intents: PERCEPTUAL = 0 (default), RELATIVE_COLORIMETRIC = 1, SATURATION = 2, ABSOLUTE_COLORIMETRIC = 3. `buildTransform` is the expensive step; reuse the transform across images. `createProfile` builds only "sRGB", "LAB" and "XYZ" (LAB defaults to D50). Source: ImageCms docs.
- The embedded profile arrives as bytes in `im.info["icc_profile"]`; wrap it with `ImageCms.ImageCmsProfile(io.BytesIO(data))`. Savers take `icc_profile=` for JPEG, PNG, TIFF, WebP and AVIF. Source: Pillow file formats.
- PNG colour chunks have a priority: cICP (1), iCCP (2), sRGB (3), cHRM+gAMA (4); the lowest number wins and the others are ignored. iCCP and sRGB must not both be present. Source: PNG 3.
- "Convert to profile" changes pixel numbers; "assign profile" only changes the label. Mixing them up is the commonest colour bug.

Rules:
- R1. On load, read `icc_profile`. If present and not sRGB, convert to the working space (sRGB for 8-bit, or linear sRGB / a wide space in float), and remember the original profile.
- R2. A file with no profile is treated as sRGB, and the report says so.
- R3. On save, embed the profile of the pixels being written. Exports for the web convert to sRGB first.
- R4. Never call `Image.convert("CMYK")` for print work: Pillow's built-in conversion is a naive formula without a profile. Use ImageCms with a real CMYK profile. (Pillow concepts page lists modes; the naive conversion behaviour should be verified by test in Step B.)
- R5. Build ImageCms transforms once per (profile pair, mode, intent) and cache them.

## 2. Gamma against linear light

- sRGB values are encoded with a transfer curve: linear = v/12.92 for v <= 0.04045, else ((v+0.055)/1.055)^2.4. Light adds in linear values, not encoded ones. Source: https://en.wikipedia.org/wiki/SRGB
- Pillow's `resize` does not linearise; it interpolates the encoded values. Users who need correct resizing convert to linear float, resize, and convert back. Sources: https://pillow.readthedocs.io/en/stable/reference/Image.html (resize section mentions no gamma handling); https://stackoverflow.com/questions/31300865/srgb-aware-image-resize-in-pillow
- The W3C blend modes are defined on the colour values as given; browsers blend in sRGB-encoded values. Photoshop-compatible blends therefore use encoded values; physically correct light mixing (exposure, blur, lens blur, glow, resize) uses linear. Source: compositing-1.
- Defaults to know: Pillow `resize` defaults to BICUBIC (NEAREST for modes "1" and "P"); `thumbnail` defaults to BICUBIC with `reducing_gap=2.0`, and `reducing_gap >= 3.0` is "indistinguishable from fair resampling in most cases". Source: Pillow Image docs.

Rules:
- R6. Resize, blur, exposure, defocus and any averaging of light run on linear float32 (NumPy), then re-encode.
- R7. Blend modes default to encoded values to match Photoshop and CSS, with an opt-in `--linear` flag.
- R8. Curves, Levels and LUTs are applied to encoded values (that is what their UI means).
- R9. Downscaling by large factors uses a box pre-reduce (or `reducing_gap`) before the final filter, to avoid aliasing.

## 3. Bit depth

- Pillow modes: "L" and "RGB" are 8 bits per channel; "I;16" is 16-bit greyscale; "I" is 32-bit integer; "F" is 32-bit float. Multi-channel 16-bit RGB is not a native Pillow mode; 16-bit RGB PNG and TIFF arrive reduced to 8 bits per channel. Source: Pillow concepts page; Pillow file formats. (The 16-bit RGB reduction should be confirmed by test in Step B.)
- AVIF in Pillow: "Only 8-bit images can be saved", and all AVIF images decode as 8-bit RGB(A). Source: Pillow file formats.
- Photoshop's 16-bit mode stores 0..32768, not 0..65535. Source: https://helpx.adobe.com/photoshop/using/bit-depth.html (403 to fetcher; from Adobe's documented behaviour, recheck).
- 8-bit pipelines band when you stack several adjustments; quantise once at the end.

Rules:
- R10. Internal working format is NumPy float32 in 0..1 (linear or encoded, tagged). Convert to 8 or 16 bits only at save.
- R11. For 16-bit RGB input or output use tifffile, OpenCV (`cv2.IMREAD_UNCHANGED`) or pillow-heif rather than plain Pillow, and say so when it falls back to 8-bit.
- R12. Dither (or add tiny noise) when quantising smooth gradients to 8 bits.

## 4. Alpha: straight against premultiplied

- PNG "does not use premultiplied alpha", and gamma is not applied to alpha. Source: PNG 3.
- W3C: blending "must not use pre-multiplied color values"; Porter-Duff source-over is co = Cs x as + Cb x ab x (1 - as), or co = cs + cb x (1 - as) on premultiplied values. Source: compositing-1.
- Pillow has mode "RGBa" (premultiplied). `resize` with a non-NEAREST filter on "RGBA" or "LA" premultiplies internally and converts back, which prevents dark or coloured fringes from transparent pixels. Sources: Pillow concepts (RGBa); https://github.com/python-pillow/Pillow/pull/7888.
- AVIF saving has an `alpha_premultiplied` option. Source: Pillow file formats.

Rules:
- R13. Store straight alpha. Premultiply for any filter that averages neighbours (blur, resize, warp, sharpen), then un-premultiply, guarding alpha = 0.
- R14. Blend formulas take straight colour, then composite with Porter-Duff.
- R15. Never apply gamma or ICC transforms to the alpha channel.
- R16. Fully transparent pixels keep whatever colour they had in the input unless asked (WebP `exact` controls this; see section 7).

## 5. EXIF orientation

- Cameras store pixels sensor-side up and record rotation in EXIF tag 0x0112 (values 1-8). `ImageOps.exif_transpose(im)`: "If an image has an EXIF Orientation tag, other than 1, transpose the image accordingly, and remove the orientation data." With `in_place=True` it modifies the image and returns None; otherwise it returns a new image (a copy if nothing to do). Source: ImageOps docs.
- Orientation also appears in XMP (tiff:Orientation) and HEIF has its own transform boxes; an image can be rotated twice if both are honoured.

Rules:
- R17. Call `ImageOps.exif_transpose` immediately after open, before any geometry, selection coordinate or mask is computed.
- R18. Save with orientation 1 (exif_transpose already removes the tag); do not write the old orientation back.
- R19. Masks, layers and click coordinates passed by the user are in the displayed (transposed) frame.

## 6. Chroma subsampling

- JPEG stores colour at reduced resolution: 4:4:4 (none), 4:2:2, 4:2:0. Pillow's JPEG `subsampling` accepts "keep", "4:4:4", "4:2:2", "4:2:0"; `quality="keep"` and `subsampling="keep"` reuse the source's settings (JPEG input only). With `keep_rgb`, subsampling raises OSError. AVIF also has `subsampling`. Source: Pillow file formats.
- Subsampling smears thin coloured edges (red text on blue, pixel art, UI screenshots).

Rules:
- R20. Use 4:4:4 for graphics, text, pixel art and anything to be re-edited; 4:2:0 only for photos at final export.
- R21. Re-saving a JPEG with no edits copies the file; if pixels changed, reuse source quality tables only when asked.

## 7. Traps per format (Pillow behaviour)

All from the Pillow file formats page unless noted.

| Format | Traps | Rule |
|---|---|---|
| JPEG | Lossy each save; quality 0-95 (default 75), above 95 wastes bytes; reads L, RGB, CMYK (Adobe CMYK JPEGs are often inverted); truncated files fail unless `ImageFile.LOAD_TRUNCATED_IMAGES`; no alpha | Save once at the end; pass `icc_profile`, `exif`; flatten alpha onto a chosen matte |
| PNG | Straight alpha (PNG 3); `compress_level` 0-9 default 6; colour chunk priority cICP > iCCP > sRGB > gAMA (PNG 3); "P" mode with `transparency` is easy to lose on convert; writes modes 1, L, LA, I, P, RGB, RGBA | Convert "P" with transparency via RGBA; keep iCCP |
| TIFF | Compressed TIFF needs libtiff; multi-page with `save_all`; layered Photoshop TIFF data is ignored; may hold 16-bit and float | Use tifffile for 16/32-bit and multi-sample data |
| WebP | `lossless`, `quality` default 80, `alpha_quality`, `method`, `exact` (keep RGB under transparent pixels); lossy WebP is always 4:2:0 (https://developers.google.com/speed/webp/docs/riff_container) | Use lossless for graphics; `exact=True` when alpha will be edited later |
| AVIF | Pillow saves 8-bit only and decodes as 8-bit; first frame only by default; `alpha_premultiplied`, `range`, `subsampling` | Warn on HDR or 10/12-bit sources |
| HEIC/HEIF | Not in Pillow core; pillow-heif registers an opener (BSD-3-Clause; libheif and the HEVC codec carry their own licences, see kb). Patent-encumbered HEVC | Open through pillow-heif; export to another format by default |
| GIF | 256-colour palette per frame, 1-bit transparency, frames read as "P" and may become RGB/RGBA after the first; `disposal`, `duration`, `loop` | Quantise with dither deliberately; never use GIF as an intermediate |
| BMP | Reads/writes 1, L, P, RGB; alpha BMPs are a variant, not reliably written; no profile | Treat as legacy input only |
| PSD | Pillow is read-only and only for Photoshop 2.5/3.0-era files; layers come as frames without blend modes, effects or masks | Use psd-tools for reading layers; writing PSD is a rung 2 question (Step A item 5) |

General: Pillow raises `DecompressionBombWarning` above `Image.MAX_IMAGE_PIXELS` and `DecompressionBombError` above twice that (Pillow Image docs). R22: keep the limit on; let the user raise it with a flag.

## 8. Metadata (EXIF, XMP, IPTC)

- EXIF (camera data, orientation, GPS) lives in APP1 in JPEG, the eXIf chunk in PNG (PNG 3), and is passed with `exif=` on save for JPEG, PNG, TIFF, WebP, AVIF. `im.getexif()` returns an editable Exif object. Sources: Pillow file formats; Pillow Image docs.
- XMP is an XML packet; `im.getxmp()` returns a dict and needs defusedxml. WebP and AVIF accept `xmp=` on save. Source: Pillow Image docs; Pillow file formats.
- IPTC-IIM (captions, credits, keywords) lives in Photoshop APP13; Pillow exposes only `IptcImagePlugin.getiptcinfo` and does not write it. The IPTC Photo Metadata Standard now maps these to XMP. Sources: https://pillow.readthedocs.io/en/stable/reference/plugins.html ; https://www.iptc.org/standards/photo-metadata/iptc-standard/
- ExifTool reads and writes all three across formats; licence "same terms as Perl itself" (https://exiftool.org/).
- GPS location in EXIF is a privacy leak when sharing.
- C2PA Content Credentials record AI edits; https://c2pa.org/specifications/

Rules:
- R23. By default keep EXIF (minus orientation, R18), ICC, and XMP on edits; strip GPS and serial numbers on any "export for web/share" path, and say what was stripped.
- R24. Update EXIF pixel dimensions and thumbnail after resizes or crops, or drop the embedded thumbnail (it otherwise shows the old image).
- R25. For full IPTC/XMP round trips call ExifTool (rung 2) when present, copying tags from source to output after the save.
- R26. Record generative-model edits in an XMP note (and C2PA when the tool exists) so AI involvement is never hidden.

## 9. Order of operations on load and save

Load: open -> check pixel limit -> `exif_transpose` -> read ICC -> convert to working space -> float32 straight alpha.
Save: composite -> (linear to encoded if needed) -> convert to output profile -> quantise with dither -> embed ICC, EXIF, XMP -> encode with format-specific options above.

## 10. Resampling kernel notes (phw 0.7.0)

- Pillow's BICUBIC uses the Keys cubic with a = -0.5 (libImaging/Resample.c, `bicubic_filter`), the value that reproduces linear ramps exactly; a = -1 (some older tools) overshoots more. No change needed in phw. Sources: Pillow source https://github.com/python-pillow/Pillow/blob/main/src/libImaging/Resample.c ; Szeliski, Computer Vision: Algorithms and Applications, 2nd ed. (2022), https://szeliski.org/Book/.
- Levels, curves and equalisation on each RGB channel wash colour out after a strong gamma; phw applies them to luma and scales the colour by the luma ratio (`--on luminance`, the default since 0.7.0). Measured in tests/test_phw6.py on a six-patch colour chart. Source: Szeliski, Computer Vision: Algorithms and Applications, 2nd ed. (2022), https://szeliski.org/Book/.
