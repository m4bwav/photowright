# Inkscape manual lessons (Tavmjong Bah, GFDL), read 2026-11-18 session 35

Source: http://tavmjong.free.fr/INKSCAPE/MANUAL/html/ (HTTP only; HTTPS refused, WebFetch fails, curl works). Covers Inkscape 0.48-0.92. [inference] = our note, not the manual.

Build candidates (each test first):
1. Trace node-count fixture: raster circle gives about 42 corner nodes (alphamax 0), 25 (alphamax 1), 5 (plus opttolerance 0.2). Trace-Options.html
2. Speckle suppression: no closed subpath below the minimum area remains. Trace-Options.html
3. Multi-scan stack mode: stacked paths cover the ones above them (no seam gaps); unstacked paths do not overlap; remove-background drops the bottom path. Trace-Multi.html
4. Brightness steps: state the threshold list and give exactly N scans (Inkscape runs N+1, a known bug). Trace-Multi.html
5. Halftone input: a pre-blur option lowers nodes on a screened print. Trace.html
6. Simplify tolerance in absolute document units, not relative to the selection size. Paths-Editing.html
7. vcheck: parse implicit repeats and H/V/S/T/A; report open paths that a boolean would close implicitly. FileFormat-Path.html, Paths-Combining.html
8. SVG: write fill-rule evenodd explicitly (or wind holes opposite); test that a hole pixel renders transparent. Plain SVG only, no sodipodi/inkscape namespaces. Attributes-Fill-Stroke.html, File-Export.html
9. Physical units: width/height in mm plus a matching viewBox (1 unit = 1 mm); Inkscape px = 96 dpi (90 before 0.92). Coordinates.html
10. EPS: check that the %%BoundingBox header is what is expected (Inkscape always uses the tight box). File-Export.html
11. DXF: polylines/LWPOLYLINE only, Beziers flattened, dashes split into subpaths, opens in ezdxf; [inference] $INSUNITS=4, Y flipped, contours closed, hairlines only in SVG/PDF.
12. [inference] Apply clips as a boolean before DXF export; text goes to outlines for cutters.

Already built (checked against scripts/phw/vector.py): 8 (evenodd written and honoured, plain SVG), 10 (EPS BoundingBox is the page), 11 (DXF R12 closed POLYLINE, curves flattened, y up, mm). $INSUNITS is an R2000+ header variable, so it is left out of the R12 writer on purpose. Open: 1-7, 9, 12.

Built in 0.22.0 (session 37, tests/test_phw21.py): 1 (circle fixture: 38/12/9 nodes at tol 0.3/0.6/1.5), 2 (`--speckle`), 3 (`--stack`, `--no-background`), 4 (`--scans N`, exactly N), 5 (`--blur`: halftone 3448 to 55 nodes at r=3), 7 (arcs now exact cubics; repeats, H/V/S/T, open paths were already parsed), 9 (mm viewBox). 6 was already absolute (px), now tested. 12 not built: no polygon boolean or font outliner at rung 1; a clip-path is now reported in the notes.
