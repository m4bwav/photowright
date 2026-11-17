# Vector formats

Checked 2026-11-16. Sources per claim; "unverified" where not read today.

## SVG: the subset every program opens

`<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="80mm" viewBox="0 0 100 80">` with `<path d="..." fill="#rrggbb" fill-rule="evenodd"/>` only. Absolute `M L C Z` commands, presentation attributes instead of CSS `<style>`/`class`, no filters, masks, clipPaths, gradients, `<use>`, `<text>`, `<image>`, and transforms flattened. These path features sit inside SVG Tiny 1.2. Sources: https://www.w3.org/TR/SVGTiny12/paths.html ; https://www.w3.org/TR/SVG11/paths.html#PathData
Stdlib: string building or `xml.etree.ElementTree`.

## PDF

Minimal PDF 1.4: catalog, pages, one page with MediaBox in points, a content stream with `m l c h` and `f` (non-zero) or `f*` (even-odd), colour by `rg`. Needs an xref table of byte offsets; about 60 lines of stdlib (`zlib` optional). Spec: https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf

## EPS

PostScript with `%!PS-Adobe-3.0 EPSF-3.0` and `%%BoundingBox`, operators `moveto lineto curveto closepath fill` (`eofill` for even-odd). Plain text, about 30 lines. Spec: https://www.adobe.com/content/dam/acom/en/devnet/actionscript/articles/5002.EPSF_Spec.pdf (unverified URL)

## DXF

- **R12 (AC1009)**: most accepted by cutters, lasers and CNC. Entities `LINE`, `ARC`, `CIRCLE`, `POLYLINE`/`VERTEX`/`SEQEND` (with optional bulge arcs); no splines, so cubics are flattened. A minimal file can be just an ENTITIES section. Source: https://ezdxf.readthedocs.io/en/stable/dxfinternals/filestructure.html
- **R2000+ (AC1015)**: `LWPOLYLINE` (compact, bulges) and `SPLINE` (NURBS); needs HEADER, CLASSES, TABLES, OBJECTS and handles: hard by hand, ezdxf (MIT) writes it. https://ezdxf.readthedocs.io/
- R12 has no `$INSUNITS` (added in later versions), so units are implied; state mm. Prefer polylines over SPLINE for cutters; LightBurn reads splines.

## Import limits per program

| Program | Takes | Limits | Source |
|---|---|---|---|
| Cricut Design Space | SVG, DXF, PNG, JPG, GIF, BMP | groups/colours become layers; strokes not cut; heavy node counts slow it; size from width/height units | https://help.cricut.com/hc/en-us/articles/360009556313 |
| Silhouette Studio | DXF in Basic; SVG and PDF need Designer Edition or above | R12 DXF safest | https://www.silhouetteamerica.com/software |
| LightBurn | SVG, DXF, AI, PDF, EPS, PLT and more | colour to layer; text must be paths | https://docs.lightburnsoftware.com/ |
| Inkscape | SVG, PDF, EPS/PS (Ghostscript), DXF, AI | most permissive; also a CLI converter (GPL, external only) | https://inkscape.org/doc/ |
| Blender SVG import | paths and basic shapes | no text, gradients, patterns or filters; fills become filled curves | https://docs.blender.org/manual/en/latest/files/import_export/svg.html |

## Stdlib writer cost (rung 1)

SVG ~40 lines, EPS ~30, PDF ~60, DXF R12 ~50, all from one internal model: list of closed subpaths of lines and cubics with a fill colour, cubics flattened for DXF R12.
