# Transform and merge (Step A topic 9)

Date: 2026-11-16. Licences are named with the LICENSE page they come from. This pass did not re-fetch those pages live, so each one is marked `verify` in kb/tools-a5.json and the build step must re-open the link before shipping.

## 1. Perspective correction
- **Algorithm**: a 3x3 homography maps four source corners to a rectangle. Solve the 8-unknown linear system (DLT), inverse-map every output pixel and interpolate. Source: https://docs.opencv.org/4.x/da/d54/group__imgproc__transform.html (getPerspectiveTransform, warpPerspective).
- **Auto-straighten**: Canny edges, then Hough lines. Take the dominant near-vertical and near-horizontal angles, then rotate or fit vanishing points. Sources: https://docs.opencv.org/4.x/d9/db0/tutorial_hough_lines.html ; https://scikit-image.org/docs/stable/auto_examples/edges/plot_line_hough_transform.html
- **NumPy alone**: yes. An 8x8 `np.linalg.solve` plus a vectorised inverse map and bilinear sampling takes about 0.3-1 s for 24 MP in float32. Hough voting is feasible but slow at full resolution, so downscale to about 1 MP first.
- **Best free tool**: OpenCV, Apache-2.0 since 4.5.0 (https://github.com/opencv/opencv/blob/4.x/LICENSE , https://opencv.org/blog/opencv-is-to-change-the-license-to-apache-2/). scikit-image `ProjectiveTransform` + `warp`, BSD-3-Clause (https://github.com/scikit-image/scikit-image/blob/main/LICENSE.txt).
- **Test**: warp a checkerboard with a known H and correct it. Pass if corner reprojection error is under 0.5 px, straight-line residual is under 0.5 px, and auto-straighten recovers a known rotation within 0.2 degrees.

## 2. Lens correction
- **Brown-Conrady model**: radial terms k1, k2, k3 and tangential terms p1, p2 on normalised coordinates. Sources: https://docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html ; https://en.wikipedia.org/wiki/Distortion_(optics)#Software_correction
- **lensfun**: a database of per-lens distortion (poly3, poly5, ptlens), TCA and vignetting coefficients. Code LGPL-3.0, database CC-BY-SA-3.0 (https://github.com/lensfun/lensfun README, https://lensfun.github.io/). Load the user's installed database rather than bundling it, so the share-alike terms stay with lensfun.
- **Vignetting**: lensfun `pa` model, gain = 1 + k1 r^2 + k2 r^4 + k3 r^6. Source: https://lensfun.github.io/manual/latest/corrections.html
- **Chromatic aberration (lateral, TCA)**: scale the red and blue planes radially against green (lensfun poly3/linear TCA, same source). To estimate it without lens data, align R and B to G by edge correlation per radius ring.
- **NumPy alone**: all three are per-pixel radial formulas plus a remap, about 1 s per 24 MP. Lensfun XML parses with stdlib `xml.etree`. Calibrating from a checkerboard needs corner detection and nonlinear least squares, and that is where OpenCV earns its place.
- **Best free tool**: OpenCV `calibrateCamera` and `undistort` (Apache-2.0). For lookup by EXIF, `lensfunpy` (MIT wrapper, https://github.com/letmaik/lensfunpy).
- **Test**: distort a grid with known k1 and k2, then undistort. Pass if RMS grid-point error is under 0.3 px, a flat field after vignetting correction has a corner/centre ratio within 2 %, and the R/B edge offset to G is under 0.2 px at the corners.

## 3. Warp, puppet warp, liquify
- **Mesh warp**: a control grid is displaced, then each triangle is mapped affinely (or each cell bicubically). scikit-image `PiecewiseAffineTransform`: https://scikit-image.org/docs/stable/auto_examples/transform/plot_piecewise_affine.html
- **MLS deformation** (puppet-warp style): Schaefer, McPhail and Warren 2006, "Image Deformation Using Moving Least Squares", with affine, similarity and rigid variants. Source: https://people.engr.tamu.edu/schaefer/research/mls.pdf . The as-rigid-as-possible shape manipulation paper (Igarashi et al. 2005) is the usual reference for puppet warp: https://www-ui.is.s.u-tokyo.ac.jp/~takeo/papers/rigid.pdf
- **Liquify**: brush strokes (push, twirl, pinch, bloat) build up a displacement field, applied with an inverse remap. GIMP's Warp Transform (GPL-3.0) is the free reference: https://docs.gimp.org/2.10/en/gimp-tool-warp-transform.html
- **NumPy alone**: fully. Run rigid MLS on a coarse grid (every 8 px) and upsample the displacement bilinearly, about 0.2 s per MP for tens of handles. Liquify strokes are Gaussian-weighted vector adds.
- **Best free tool**: own NumPy code (rung 1). Use scikit-image for piecewise affine and `cv2.remap` for fast resampling.
- **Test**: handles left in place must give a pixel-identical image. Handles must land within 0.5 px of their targets. The Jacobian determinant must stay above 0 everywhere (no fold-over), and rigid MLS must keep local area within 5 %.

## 4. Seam carving / content-aware scale
- **Algorithm**: Avidan & Shamir 2007. Energy is gradient magnitude, dynamic programming finds the cheapest 8-connected seam, and the seam is removed or duplicated. Source: https://dl.acm.org/doi/10.1145/1275808.1276390 . Forward energy (Rubinstein, Shamir, Avidan 2008) scores the energy a removal would add and gives fewer artefacts: https://dl.acm.org/doi/10.1145/1360612.1360615 ; explainer: https://avikdas.com/2019/07/29/improved-seam-carving-with-forward-energy.html
- **Patent flag**: Adobe holds seam-carving patents, for example US 8,160,398 B1 (https://patents.google.com/patent/US8160398B1). scikit-image removed `seam_carve` in 0.19, with patent concerns cited in the discussion (https://github.com/scikit-image/scikit-image/pull/5045). Check claims and expiry before shipping. Filings around 2007-2008 point to expiry around 2027-2028 (verify).
- **NumPy alone**: yes. The DP loop is H Python iterations over vectorised rows. Removing 500 seams from a 2 MP image takes tens of seconds; numba (BSD-2) makes it 20-50x faster. Protect and remove masks are offsets added to the energy.
- **Best free tool**: `seam-carving` on PyPI (MIT, https://github.com/li-plus/seam-carving), which supports forward energy. ImageMagick `-liquid-rescale` via liblqr (LGPL-3.0, https://github.com/carlobaldassi/liblqr).
- **Test**: shrink an image with a protected face mask. Pass if pixels inside the mask are unchanged (SSIM 1.0), the width change equals the seam count, and the object's bounding box is intact on a flat background. Forward energy should give a lower mean gradient jump along seams than backward energy on the same input.

## 5. Panorama stitching
- **Pipeline**: detect features (SIFT, ORB, AKAZE), match with the ratio test, fit a homography or rotation model with RANSAC, bundle-adjust, warp to cylindrical or spherical, compensate exposure, find seams (graph cut) and blend multiband. Sources: Brown & Lowe 2007, https://link.springer.com/article/10.1007/s11263-006-0002-3 ; OpenCV stitching module, https://docs.opencv.org/4.x/d1/d46/group__stitching.html
- **Patents**: the SIFT patent US 6,711,293 expired in March 2020 (https://patents.google.com/patent/US6711293B1), and SIFT moved into OpenCV main in 4.4.0 (https://github.com/opencv/opencv/wiki/ChangeLog#version440). SURF is still in opencv_contrib `xfeatures2d` behind the nonfree build flag (https://docs.opencv.org/4.x/d5/df7/classcv_1_1xfeatures2d_1_1SURF.html), so avoid it. ORB and AKAZE are patent-free alternatives.
- **NumPy alone**: only a toy. Harris corners, patch descriptors, brute-force matching and RANSAC come to about 400 lines and handle 2-4 rotation-only photos. Bundle adjustment and graph-cut seams are not worth rewriting.
- **Best free tools**: OpenCV Stitcher (Apache-2.0), one call: `cv2.Stitcher_create().stitch(imgs)`. Hugin command-line tools (`pto_gen`, `cpfind`, `autooptimiser`, `pano_modify`, `nona`) are GPL-2.0+: https://hugin.sourceforge.io/ , https://wiki.panotools.org/Panorama_scripting_in_a_nutshell . enblend does multiband seams, GPL-2.0+: https://enblend.sourceforge.net/
- **Test**: cut a wide image into overlapping tiles with a small synthetic rotation and stitch them. Pass if the overlap matches ground truth at PSNR above 35 dB with misalignment under 1 px. Report the RANSAC inlier ratio. Gradient energy along the seam should be within the image's local median.

## 6. Focus stacking
- **Algorithm**: align the frames (ECC or a feature homography, since focus breathing changes scale), measure per-pixel sharpness (local Laplacian energy), then hard-select (depth map) or blend through Laplacian pyramids weighted by sharpness. Sources: Burt & Adelson 1983, https://persci.mit.edu/pub_pdfs/spline83.pdf ; enfuse contrast weighting and `--hard-mask`, https://enblend.sourceforge.net/enfuse.doc/enfuse_4.2.xhtml/enfuse.html
- **NumPy alone**: yes. Pyramids use a 5-tap separable kernel with decimation, about 2-4 s for 10 frames of 12 MP. `cv2.findTransformECC` is easier than writing the alignment.
- **Best free tool**: enfuse (GPL-2.0+) with `--exposure-weight=0 --saturation-weight=0 --contrast-weight=1 --hard-mask`, after Hugin's `align_image_stack -m`. Source: https://wiki.panotools.org/Focus_stacking_macro_images
- **Test**: blur a sharp chart with a different depth mask per frame and stack. Pass if the result scores SSIM above 0.95 against the original, Laplacian variance per region is at least 95 % of the best input, and no halos appear at depth edges.

## 7. Exposure fusion (Mertens)
- **Algorithm**: Mertens, Kautz and Van Reeth 2007. Weight each pixel by contrast^wc * saturation^ws * well-exposedness^we (a Gaussian around 0.5 with sigma 0.2), normalise, and blend with Laplacian pyramids. It makes no radiance map and needs no tone mapping. Sources: https://web.stanford.edu/class/cs231m/project-1/exposure-fusion.pdf ; https://docs.opencv.org/4.x/d3/db7/tutorial_hdr_imaging.html
- **NumPy alone**: yes, and it is the clean rung-1 case: about 150 lines and 1-2 s for 3 x 12 MP.
- **Best free tool**: OpenCV `createMergeMertens` (Apache-2.0). enfuse's default mode (GPL-2.0+) is this algorithm.
- **Test**: compare our output to `cv2.createMergeMertens().process` on OpenCV's sample memorial set. Pass at PSNR above 40 dB, with a clipped-pixel fraction lower than any input.

## 8. HDR merge and tone mapping
- **Debevec & Malik 1997**: recover the camera response g(Z) by least squares with a smoothness term over sampled pixels and known exposure times. Radiance is then a weighted average of g(Z) - ln dt. Source: https://www.pauldebevec.com/Research/HDR/debevec-siggraph97.pdf
- **Robertson et al. 2003**: an iterative maximum-likelihood estimate of response and irradiance. Sources: https://doi.org/10.1117/1.1557695 ; OpenCV `CalibrateRobertson` and `MergeRobertson`, https://docs.opencv.org/4.x/d3/db7/tutorial_hdr_imaging.html
- **Tone mapping**: Reinhard 2002, global and local (https://www-old.cs.utah.edu/docs/techreports/2002/pdf/UUCS-02-001.pdf), plus Drago 2003 and Mantiuk 2006. OpenCV has `TonemapReinhard`, `TonemapDrago` and `TonemapMantiuk` (same OpenCV page). RAW input is already linear, so response recovery can be skipped (rawpy, MIT: https://github.com/letmaik/rawpy).
- **NumPy alone**: yes. The Debevec solve is a least-squares problem of about N*P + 256 rows; `np.linalg.lstsq` on 100 sample pixels x 5 frames is instant. Merging and global Reinhard are per-pixel. Radiance .hdr (RGBE) can be written in NumPy, and .exr through OpenCV or imageio.
- **Best free tool**: OpenCV photo module (Apache-2.0). Luminance HDR (GPL-3.0, https://github.com/LuminanceHDR/LuminanceHDR) has more operators but is a GUI app first.
- **Test**: synthesise exposures from a known linear radiance image with a known gamma response and noise. Pass if the recovered response is within 2 % RMS of truth, merged radiance log-RMSE is under 0.05, and the tone-mapped output has no clipping and keeps luminance order on a step wedge.

## Rung summary
| Task | Rung 1 (NumPy) | Rung 2 tool |
|---|---|---|
| Perspective, auto-straighten | yes | OpenCV |
| Lens (distortion, vignette, TCA) | yes (coefficients from lensfun data) | OpenCV, lensfun |
| Mesh/MLS warp, liquify | yes | scikit-image, cv2.remap |
| Seam carving | yes (slow); patent flag | seam-carving (MIT), liblqr |
| Panorama | toy only | OpenCV Stitcher, Hugin + enblend |
| Focus stack | yes | enfuse + align_image_stack |
| Exposure fusion | yes | OpenCV, enfuse |
| HDR + tone map | yes | OpenCV |

GPL tools (Hugin, enblend, enfuse) run as separate processes and are not linked, so photowright's own licence is unaffected: https://www.gnu.org/licenses/gpl-faq.html#MereAggregation

## 9. Notes from Szeliski (phw 0.7.0)

- Prefilter: inverse mapping alone aliases where a warp shrinks the image by more than about 2x. `warp` and `perspective` now sample a Gaussian pyramid at log2 of the local shrink (trilinear mip-mapping) there; a zone plate shrunk 4x scored RMS 0.077 against a Lanczos reference, 0.373 without the prefilter. `--no-prefilter` keeps plain sampling. Source: Szeliski, Computer Vision: Algorithms and Applications, 2nd ed. (2022), https://szeliski.org/Book/.
- Pyramid blend: a layer with `"pyramid": true` is pasted band by band with the mask blurred to each band's scale (Burt and Adelson 1983), so a paste whose exposure differs leaves no step. Source: Szeliski, Computer Vision: Algorithms and Applications, 2nd ed. (2022), https://szeliski.org/Book/.
- Median stack: `stack --mode median` keeps per pixel what most aligned frames agree on (a clean plate when people walk through). Source: Szeliski, Computer Vision: Algorithms and Applications, 2nd ed. (2022), https://szeliski.org/Book/.
- Stitch projection: a flat (planar) projection only works under about 90 degrees of view; wider panoramas need cylindrical or spherical projection (OpenCV's PANORAMA mode warps spherically; Hugin offers the rest). Source: Szeliski, Computer Vision: Algorithms and Applications, 2nd ed. (2022), https://szeliski.org/Book/.
- Upscale: any single-image super-resolution model invents detail and is recorded with `invented_detail: true`, like generative fill; Lanczos records false. Source: Szeliski, Computer Vision: Algorithms and Applications, 2nd ed. (2022), https://szeliski.org/Book/.
