# Photoshop feature map (coverage table)

Checked 2026-11-16. This is the list the photowright build is scored against.

**About the sources.** helpx.adobe.com answered 403 to the fetcher on 2026-11-16. The Adobe URLs below are each feature area's help page, found by search or by Adobe's usual URL pattern. They show that a feature exists; re-check them in a browser before quoting them. The "underneath" column comes from the cited maths sources (W3C, Wikipedia algorithm pages, papers). Where Adobe does not publish its method, the row says "Adobe unpublished" and names the nearest open equivalent.

Groups: adjust, compose, select, retouch, transform, batch, files, vectorize. Rungs: 1 = own code (stdlib, Pillow, NumPy); 2 = free tool; 3 = open-weight local model; 4 = Photoshop only.

Short source keys:
- [ADJ] https://helpx.adobe.com/photoshop/using/adjusting-image-color-tone.html
- [FLT] https://helpx.adobe.com/photoshop/using/filter-effects-reference.html
- [BLD] https://helpx.adobe.com/photoshop/using/blending-modes.html
- [W3C] https://www.w3.org/TR/compositing-1/ (16 blend modes and Porter-Duff; blending "must not use pre-multiplied color values"; fetched 2026-11-16)
- [NF] https://helpx.adobe.com/photoshop/using/neural-filters-list-and-faq.html
- [GEN] https://helpx.adobe.com/photoshop/using/generative-ai-faqs-photoshop.html
- [SEL] https://helpx.adobe.com/photoshop/using/making-selections.html
- [RET] https://helpx.adobe.com/photoshop/using/retouching-repairing-images.html
- [LAY] https://helpx.adobe.com/photoshop/using/layer-basics.html
- [SO] https://helpx.adobe.com/photoshop/using/create-smart-objects.html
- [ACT] https://helpx.adobe.com/photoshop/using/actions-actions-panel.html
- [TRN] https://helpx.adobe.com/photoshop/using/transforming-objects.html
- [FILE] https://helpx.adobe.com/photoshop/using/file-formats.html
- [PATH] https://helpx.adobe.com/photoshop/using/drawing-pen-tools.html
- [PIL] https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html (fetched 2026-11-16)

## Adjustments

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Brightness/Contrast | adjust | Offset and gain around mid-grey; the modern mode is a tone curve that protects the ends | 1 | [ADJ] |
| Levels | adjust | Per-channel map: black and white input clip points, gamma exponent on the midtone, output range | 1 | [ADJ] |
| Curves | adjust | Per-channel 1D LUT from a monotone spline through control points | 1 | [ADJ]; https://en.wikipedia.org/wiki/Monotone_cubic_interpolation |
| Exposure | adjust | Multiply in linear light by 2^stops, plus offset and gamma | 1 | [ADJ] |
| Vibrance | adjust | Saturation boost weighted against existing saturation, protecting skin hues (Adobe unpublished) | 1 | [ADJ] |
| Hue/Saturation | adjust | HSL: rotate hue, scale S and L, optionally only inside a hue band with feathered edges | 1 | [ADJ]; https://en.wikipedia.org/wiki/HSL_and_HSV |
| Color Balance | adjust | R, G, B offsets weighted by shadow, midtone and highlight masks of luminance | 1 | [ADJ] |
| Black & White | adjust | Weighted sum of six hue-band contributions to grey | 1 | [ADJ] |
| Photo Filter | adjust | Blend toward a colour, optional luminosity preserve | 1 | [ADJ] |
| Channel Mixer | adjust | 3x3 matrix plus offset on RGB | 1 | [ADJ] |
| Color Lookup | adjust | Apply a 3D LUT (.cube, .3dl) by trilinear or tetrahedral interpolation | 1 | [ADJ]; https://en.wikipedia.org/wiki/3D_lookup_table |
| Invert | adjust | 1 - x per channel | 1 | [ADJ] |
| Posterize | adjust | Quantise each channel to N levels | 1 | [ADJ] |
| Threshold | adjust | Luminance >= t becomes white | 1 | [ADJ] |
| Gradient Map | adjust | Luminance indexes a 1D colour gradient | 1 | [ADJ] |
| Selective Color | adjust | CMYK-style offsets per colour-family mask (reds ... neutrals, blacks) | 1 | [ADJ] |
| Shadows/Highlights | adjust | Local tone mapping: a blurred luminance mask drives shadow lift and highlight pull | 1 | [ADJ] |
| HDR Toning | adjust | Single-image local tone mapping (edge-aware detail plus tone curve) | 2 | [ADJ]; https://en.wikipedia.org/wiki/Tone_mapping |
| Desaturate | adjust | Luminance (or (max+min)/2) to grey | 1 | [ADJ] |
| Match Color | adjust | Match channel mean and standard deviation to a source (Reinhard-style statistics transfer) | 1 | [ADJ]; https://en.wikipedia.org/wiki/Color_mapping |
| Replace Color | adjust | Colour-range mask plus hue, saturation and lightness shift | 1 | [ADJ] |
| Equalize | adjust | Histogram equalisation through the CDF | 1 | [ADJ]; https://en.wikipedia.org/wiki/Histogram_equalization |
| Auto Tone / Auto Contrast / Auto Color | adjust | Percentile clipping per channel or on luminance; Auto Color also neutralises midtones | 1 | [ADJ] |
| Camera Raw basic panel | adjust | Exposure, white balance, tone curve, clarity, dehaze on scene-linear data | 2 | https://helpx.adobe.com/camera-raw/using/make-color-tonal-adjustments-camera.html |
| Dehaze | adjust | Haze removal; open equivalent is the dark channel prior (Adobe unpublished) | 1 | https://en.wikipedia.org/wiki/Dark_channel_prior |
| Clarity / Texture | adjust | Edge-aware local contrast at medium (clarity) or fine (texture) radius | 1 | https://helpx.adobe.com/camera-raw/using/make-color-tonal-adjustments-camera.html |
| White balance | adjust | Chromatic adaptation matrix (Bradford, von Kries) in linear XYZ | 1 | https://en.wikipedia.org/wiki/Chromatic_adaptation |
| Mode change (RGB, CMYK, Lab, Grayscale, Indexed) | adjust | ICC conversion through the profile connection space with a rendering intent; Indexed = palette quantisation | 1 | [FILE]; https://pillow.readthedocs.io/en/stable/reference/ImageCms.html |
| Indexed colour / palette for web | files | Median cut, octree or k-means quantisation, ordered or Floyd-Steinberg dither | 1 | https://en.wikipedia.org/wiki/Color_quantization |

## Blending and layer features

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Normal / Dissolve | compose | Porter-Duff source-over; Dissolve = random per-pixel alpha threshold | 1 | [W3C]; [BLD] |
| Darken, Multiply, Color Burn, Linear Burn, Darker Color | compose | min(Cb,Cs); Cb*Cs; 1-min(1,(1-Cb)/Cs); Cb+Cs-1; whichever pixel has lower luma | 1 | [W3C]; [BLD] |
| Lighten, Screen, Color Dodge, Linear Dodge, Lighter Color | compose | max; Cb+Cs-Cb*Cs; min(1,Cb/(1-Cs)); Cb+Cs; higher-luma pixel | 1 | [W3C]; [BLD] |
| Overlay, Soft Light, Hard Light | compose | W3C formulas; Adobe's Soft Light curve is not published and differs slightly | 1 | [W3C] |
| Vivid Light, Linear Light, Pin Light, Hard Mix | compose | Burn/dodge pairs split at 0.5; Hard Mix thresholds Vivid Light | 1 | [BLD]; https://en.wikipedia.org/wiki/Blend_modes |
| Difference, Exclusion, Subtract, Divide | compose | abs(Cb-Cs); Cb+Cs-2CbCs; Cb-Cs; Cb/Cs | 1 | [W3C]; [BLD] |
| Hue, Saturation, Color, Luminosity | compose | Non-separable SetLum, SetSat, ClipColor with luma 0.3/0.59/0.11 | 1 | [W3C] |
| Opacity against Fill | compose | Fill scales layer pixels but not layer styles; Opacity scales both | 1 | [LAY] |
| Layer masks | compose | Greyscale alpha multiplier, non-destructive | 1 | https://helpx.adobe.com/photoshop/using/masking-layers.html |
| Vector masks | compose | Anti-aliased rasterised path as alpha | 1 | https://helpx.adobe.com/photoshop/using/masking-layers.html |
| Clipping masks | compose | Layer alpha multiplied by the base layer's alpha | 1 | https://helpx.adobe.com/photoshop/using/masking-layers.html |
| Blend If | compose | Alpha from luminance ranges of this layer and the layer below; split sliders give a linear ramp | 1 | [BLD] |
| Layer groups and pass-through | compose | Group composited in isolation, or children blended straight through | 1 | [LAY]; [W3C] (isolation) |
| Adjustment layers | compose | Adjustment applied to the composite below, masked | 1 | [ADJ] |
| Fill layers (solid, gradient, pattern) | compose | Generated layer content | 1 | [LAY] |
| Gradient tool | compose | Linear, radial, angle, reflected, diamond; interpolation in perceptual, linear or classic space | 1 | https://helpx.adobe.com/photoshop/using/gradient-fills.html |
| Layer style: Drop Shadow | compose | Alpha offset, spread (dilation), blur, colour, blend | 1 | https://helpx.adobe.com/photoshop/using/layer-effects-styles.html |
| Layer style: Inner Shadow, Outer Glow, Inner Glow | compose | Same with inverted alpha or no offset; choke = erosion | 1 | same |
| Layer style: Bevel & Emboss | compose | Height from a distance transform of alpha, shaded by a light direction | 1 | same; https://en.wikipedia.org/wiki/Distance_transform |
| Layer style: Stroke | compose | Alpha grown or shrunk by distance, filled | 1 | same |
| Layer style: Satin, Color/Gradient/Pattern Overlay | compose | Offset-shape interference; overlays = fill blended inside alpha | 1 | same |
| Smart Objects | compose | Embedded or linked source plus transform and filter stack, re-rendered from the source | 1 | [SO] |
| Smart Filters | compose | Non-destructive filter stack, each with mask and blend mode | 1 | https://helpx.adobe.com/photoshop/using/apply-smart-filters.html |
| Linked smart objects | files | External file reference updated on change | 1 | [SO] |
| Artboards | compose | Several canvases in one document | 1 | https://helpx.adobe.com/photoshop/using/artboards.html |
| Layer comps | compose | Saved visibility, position and style states | 1 | https://helpx.adobe.com/photoshop/using/layer-comps.html |
| Auto-Blend Layers | compose | Seam finding plus multiband (Laplacian pyramid) blend; stack mode = focus stacking | 2 | https://helpx.adobe.com/photoshop/using/combine-images-auto-blend-layers.html; https://en.wikipedia.org/wiki/Image_stitching |
| Auto-Align Layers | transform | Feature matching plus homography or cylindrical fit with RANSAC | 2 | https://helpx.adobe.com/photoshop/using/aligning-layers.html |
| Photomerge | transform | Panorama: align, warp, seam, blend | 2 | https://helpx.adobe.com/photoshop/using/create-panoramic-images-photomerge.html |
| Merge to HDR Pro | compose | Camera response recovery to a radiance map, then tone mapping | 2 | https://helpx.adobe.com/photoshop/using/high-dynamic-range-images.html; https://en.wikipedia.org/wiki/High-dynamic-range_imaging |
| Image stacks (median, mean) | compose | Per-pixel statistic across aligned layers (median removes passers-by) | 1 | https://helpx.adobe.com/photoshop/using/image-stacks.html |
| Apply Image / Calculations | compose | Blend channels between documents with a blend mode | 1 | https://helpx.adobe.com/photoshop/using/channel-calculations.html |
| Alpha channels | select | Extra greyscale planes stored with the file | 1 | https://helpx.adobe.com/photoshop/using/channel-basics.html |
| Spot channels | files | Named ink plates for print | 2 | https://helpx.adobe.com/photoshop/using/spot-channels.html |
| Text layers | compose | OpenType shaping and rasterisation; Pillow ImageFont (raqm layout for complex scripts) | 1 | https://helpx.adobe.com/photoshop/using/creating-type.html; https://pillow.readthedocs.io/en/stable/reference/ImageFont.html |
| Shape layers | vectorize | Vector paths filled and stroked, rasterised with anti-aliasing | 1 | [PATH] |

## Selection

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Marquee (rectangle, ellipse, row, column) | select | Geometric mask, optional feather (Gaussian blur of the mask) | 1 | [SEL] |
| Lasso / Polygonal Lasso | select | Polygon fill of a mask | 1 | [SEL] |
| Magnetic Lasso | select | Live-wire: shortest path over a gradient cost | 2 | https://en.wikipedia.org/wiki/Livewire_Segmentation_Technique |
| Magic Wand | select | Flood fill with colour tolerance, contiguous or global | 1 | [SEL]; https://en.wikipedia.org/wiki/Flood_fill |
| Quick Selection | select | Brush-seeded segmentation (Adobe unpublished; open equivalent GrabCut graph cut) | 2 | [SEL]; https://en.wikipedia.org/wiki/GrabCut |
| Object Selection | select | Detector plus segmentation model; open equivalent SAM 2.1 with a box prompt | 3 | https://helpx.adobe.com/photoshop/using/object-selection-tool.html |
| Select Subject | select | Salient-object segmentation model | 3 | https://helpx.adobe.com/photoshop/using/select-subject.html |
| Select Sky | select | Sky segmentation model | 3 | https://helpx.adobe.com/photoshop/using/sky-replacement.html |
| Remove Background | select | Matting model giving soft alpha | 3 | [SEL] |
| Select and Mask / Refine Hair | select | Trimap alpha matting (closed-form or learned) plus colour decontamination | 3 | https://helpx.adobe.com/photoshop/using/select-mask.html |
| Color Range | select | Soft mask from distance to sampled colours, with fuzziness | 1 | https://helpx.adobe.com/photoshop/using/selecting-color-range-image.html |
| Focus Area | select | Local sharpness (Laplacian energy) thresholded | 1 | [SEL] |
| Grow, Similar, Expand, Contract, Border, Smooth, Feather | select | Morphology (dilate, erode), flood, Gaussian | 1 | [SEL]; https://en.wikipedia.org/wiki/Mathematical_morphology |
| Quick Mask mode | select | Mask edited as a paintable channel | 1 | [SEL] |
| Selection to path / path to selection | vectorize | Contour trace plus curve fit; path rasterised to mask | 1 | [PATH] |

## Retouch

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Clone Stamp | retouch | Copy with an offset under a soft brush | 1 | [RET] |
| Healing Brush | retouch | Clone, then gradient-domain (Poisson) blend to the target boundary | 1 | [RET]; https://en.wikipedia.org/wiki/Gradient-domain_image_processing |
| Spot Healing Brush | retouch | Automatic source by patch search plus healing | 2 | [RET] |
| Patch tool | retouch | Region replace plus gradient-domain blend | 1 | [RET] |
| Content-Aware Fill | retouch | PatchMatch randomised nearest-neighbour patch synthesis (Barnes et al. 2009, Adobe co-authors) | 2 | https://helpx.adobe.com/photoshop/using/content-aware-fill.html; https://gfx.cs.princeton.edu/pubs/Barnes_2009_PAR/ |
| Content-Aware Move / Extend | retouch | PatchMatch retargeting | 2 | https://helpx.adobe.com/photoshop/using/content-aware-patch-move.html |
| Remove tool | retouch | Learned inpainting; open equivalent is a LaMa-class model | 3 | https://helpx.adobe.com/photoshop/using/tool-techniques/remove-tool.html |
| Red Eye | retouch | Find red-dominant pupil region, desaturate and darken | 1 | [RET] |
| Dodge / Burn / Sponge | retouch | Local exposure or saturation change under a brush, limited to a tonal range | 1 | [RET] |
| Blur / Sharpen / Smudge brushes | retouch | Local convolution, or dragging pixels along the stroke | 1 | [RET] |
| Brush engine | retouch | Stamped dabs with spacing, hardness falloff and dynamics | 1 | https://helpx.adobe.com/photoshop/using/painting-tools.html |
| Eraser / Background Eraser / Magic Eraser | retouch | Paint alpha; colour-sampled alpha clear; flood alpha clear | 1 | [RET] |
| Paint Bucket | retouch | Flood fill with tolerance | 1 | https://en.wikipedia.org/wiki/Flood_fill |
| Mixer Brush | retouch | Simulated paint loading and mixing | 4 | https://helpx.adobe.com/photoshop/using/painting-mixer-brush.html |
| Liquify | transform | Displacement field (forward warp, pucker, bloat) | 1 | https://helpx.adobe.com/photoshop/using/liquify-filter.html |
| Face-Aware Liquify | transform | Face landmark model drives the warp | 3 | same |
| Frequency separation (technique) | retouch | Low = blur; high = image - low + 0.5; edit each, recombine | 1 | https://en.wikipedia.org/wiki/Unsharp_masking |

## Filters

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Gaussian Blur | adjust | Separable Gaussian convolution | 1 | [FLT]; https://en.wikipedia.org/wiki/Gaussian_blur |
| Box Blur | adjust | Moving average (summed-area table) | 1 | [FLT] |
| Motion Blur | adjust | Line kernel at an angle | 1 | [FLT] |
| Radial Blur (spin, zoom) | adjust | Accumulation along arcs or rays | 1 | [FLT] |
| Lens Blur | adjust | Polygon bokeh kernel scaled by a depth map, specular boost | 1 | [FLT] |
| Surface Blur / Smart Blur | adjust | Edge-preserving bilateral-type filter | 1 | [FLT]; https://en.wikipedia.org/wiki/Bilateral_filter |
| Shape Blur / Average | adjust | Custom kernel; mean colour | 1 | [FLT] |
| Blur Gallery (Field, Iris, Tilt-Shift, Path, Spin) | adjust | Spatially varying blur-radius map with bokeh | 1 | https://helpx.adobe.com/photoshop/using/blur-gallery.html |
| Unsharp Mask | adjust | x + amount*(x - blur(x)) with a threshold | 1 | [FLT]; https://en.wikipedia.org/wiki/Unsharp_masking |
| Smart Sharpen | adjust | Sharpen modelling Gaussian, lens or motion blur (deconvolution-like), with shadow/highlight fade | 1 | [FLT]; https://en.wikipedia.org/wiki/Deconvolution |
| Shake Reduction | adjust | Blind blur-kernel estimation then deconvolution | 2 | https://helpx.adobe.com/photoshop/using/reduce-camera-shake-blurring.html |
| High Pass | adjust | x - blur(x) + 0.5 | 1 | [FLT] |
| Add Noise | adjust | Uniform or Gaussian noise, mono option | 1 | [FLT] |
| Reduce Noise | adjust | Edge-preserving denoise (Adobe unpublished; open: non-local means, BM3D) | 2 | [FLT]; https://en.wikipedia.org/wiki/Non-local_means |
| Despeckle / Median / Dust & Scratches | adjust | Median filter with threshold | 1 | [FLT]; https://en.wikipedia.org/wiki/Median_filter |
| Maximum / Minimum | adjust | Grey dilation and erosion | 1 | [FLT] |
| Emboss | adjust | Directional derivative kernel + 0.5 | 1 | [FLT] |
| Find Edges / Trace Contour / Glowing Edges | adjust | Sobel-type gradient magnitude; iso-contours | 1 | [FLT]; https://en.wikipedia.org/wiki/Sobel_operator |
| Solarize | adjust | Invert values above the midpoint | 1 | [FLT] |
| Diffuse / Wind / Extrude / Tiles | adjust | Random neighbour swap; directional streaks; 3D blocks; tile offsets | 1 | [FLT] |
| Oil Paint | adjust | Kuwahara-like anisotropic stroke filter | 1 | [FLT]; https://en.wikipedia.org/wiki/Kuwahara_filter |
| Pixelate (Mosaic, Crystallize, Pointillize, Color Halftone, Fragment, Mezzotint, Facet) | adjust | Block average; Voronoi cells; dots; rotated-screen halftone | 1 | [FLT]; https://en.wikipedia.org/wiki/Halftone |
| Distort (Pinch, Spherize, Twirl, Wave, Ripple, ZigZag, Polar Coordinates, Shear, Displace) | transform | Inverse-mapped coordinate warps with resampling | 1 | [FLT] |
| Adaptive Wide Angle | transform | Fisheye or perspective lens model plus constraint lines | 2 | https://helpx.adobe.com/photoshop/using/adaptive-wide-angle-filter.html |
| Lens Correction | transform | Radial distortion polynomial, chromatic aberration scale, vignette gain, perspective | 1 | https://helpx.adobe.com/photoshop/using/correcting-image-distortion-noise.html |
| Vanishing Point | transform | Planar homography grids for clone and paste in perspective | 1 | https://helpx.adobe.com/photoshop/using/vanishing-point.html |
| Clouds / Difference Clouds / Fibers | adjust | Fractal (fBm, Perlin-type) noise | 1 | [FLT]; https://en.wikipedia.org/wiki/Perlin_noise |
| Lens Flare / Lighting Effects | adjust | Composited flare elements; Phong lighting on a height channel | 1 | [FLT]; https://en.wikipedia.org/wiki/Phong_reflection_model |
| Flame / Picture Frame / Tree | adjust | Procedural path-based generators | 4 | [FLT] |
| Filter Gallery (Artistic, Brush Strokes, Sketch, Texture) | adjust | About 47 stylisation filters built from edges, posterise, texture overlay, halftone | 1 | https://helpx.adobe.com/photoshop/using/filter-gallery-overview.html |
| Camera Raw Filter | adjust | Camera Raw pipeline on a layer | 2 | https://helpx.adobe.com/camera-raw/using/supported-cameras.html |
| Offset | transform | Wrap-around translate (for tile seams) | 1 | [FLT] |
| Custom | adjust | User 5x5 convolution kernel, scale, offset | 1 | [FLT] |
| De-Interlace / NTSC Colors | adjust | Line interpolation; gamut clip | 1 | [FLT] |

## Neural filters and generative AI

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Skin Smoothing | retouch | Face detection plus learned smoothing; code route is frequency separation on a face mask | 3 | [NF] |
| Smart Portrait | retouch | GAN latent editing (age, expression, gaze, light) | 3 | [NF] |
| Makeup Transfer | retouch | Learned transfer on face regions | 3 | [NF] |
| Style Transfer | adjust | Neural style transfer | 3 | [NF]; https://en.wikipedia.org/wiki/Neural_style_transfer |
| Landscape Mixer | adjust | Generative blend of an image with a reference or season | 3 | [NF] |
| Harmonization | compose | Learned colour and tone matching of a layer to its background | 3 | [NF] |
| Color Transfer | adjust | Palette transfer; code route is Reinhard Lab statistics | 1 | [NF] |
| Colorize | adjust | Learned black-and-white colourisation | 3 | [NF] |
| Super Zoom | transform | Learned super-resolution | 3 | [NF] |
| Depth Blur | adjust | Monocular depth model plus depth-driven lens blur | 3 | [NF] |
| JPEG Artifacts Removal | adjust | Learned deblocking | 3 | [NF] |
| Photo Restoration | retouch | Scratch detection and learned restoration | 3 | [NF] |
| Preserve Details 2.0 resample | transform | Learned upscaling in Image Size | 3 | https://helpx.adobe.com/photoshop/using/resizing-image.html |
| Generative Fill | retouch | Firefly diffusion inpainting from a selection and prompt (cloud, credits) | 3 | [GEN] |
| Generative Expand | transform | Diffusion outpainting into the crop margin | 3 | [GEN] |
| Generate Image / Generate Background | compose | Text-to-image diffusion | 3 | [GEN] |
| Generate Similar / Reference Image | compose | Diffusion conditioned on an image | 3 | https://helpx.adobe.com/photoshop/using/reference-image.html |
| Generative Upscale | transform | Diffusion super-resolution | 3 | [GEN] |
| Sky Replacement | compose | Sky segmentation, composite, edge decontamination, foreground relight | 3 | https://helpx.adobe.com/photoshop/using/sky-replacement.html |
| Distraction removal (people, wires) | retouch | Detection plus inpainting | 3 | https://helpx.adobe.com/photoshop/using/tool-techniques/remove-tool.html |
| Content Credentials | files | C2PA manifest attached to the export | 2 | https://helpx.adobe.com/photoshop/using/content-credentials.html; https://c2pa.org/specifications/ |

## Transform

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Image Size | transform | Nearest, bilinear, bicubic (smoother, sharper); correct practice is resampling in linear light | 1 | https://helpx.adobe.com/photoshop/using/resizing-image.html |
| Canvas Size | transform | Pad or crop | 1 | same |
| Crop / Straighten | transform | Rotate by an angle then crop; content-aware crop fills corners | 1 | https://helpx.adobe.com/photoshop/using/crop-straighten-photos.html |
| Perspective Crop | transform | Homography from four corners | 1 | same; https://en.wikipedia.org/wiki/Homography_(computer_vision) |
| Free Transform (scale, rotate, skew) | transform | Affine matrix with resampling | 1 | [TRN] |
| Distort / Perspective | transform | Projective transform (homography) | 1 | [TRN] |
| Warp / Puppet Warp / Perspective Warp | transform | Bezier mesh warp; as-rigid-as-possible mesh deformation; multi-plane homographies | 2 | [TRN]; https://helpx.adobe.com/photoshop/using/puppet-warp.html |
| Content-Aware Scale | transform | Seam carving (energy map, dynamic programming) | 1 | https://helpx.adobe.com/photoshop/using/content-aware-scaling.html; https://en.wikipedia.org/wiki/Seam_carving |
| Rotate / Flip canvas | transform | Exact 90-degree transposes | 1 | [TRN] |
| Trim / Reveal All | transform | Bounding box of non-transparent or non-border pixels | 1 | [TRN] |
| Crop and Straighten Photos | transform | Find rectangles in a scan, deskew, split | 1 | https://helpx.adobe.com/photoshop/using/crop-straighten-photos.html |
| Lens profile correction | transform | Lens database polynomials for distortion, vignetting, chromatic aberration | 2 | https://helpx.adobe.com/photoshop/using/correcting-image-distortion-noise.html |

## Vector

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Pen / Curvature Pen | vectorize | Cubic Bezier paths | 1 | [PATH] |
| Make Work Path from selection | vectorize | Contour trace of the mask plus curve fit to a tolerance | 2 | [PATH]; https://potrace.sourceforge.net/ |
| Export paths to Illustrator | files | Paths written as .ai | 4 | [PATH] |
| Image Trace (Illustrator, for comparison) | vectorize | Colour quantise, trace regions, fit curves | 2 | https://helpx.adobe.com/illustrator/using/image-trace.html |

## Batch and automation

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| Actions | batch | Recorded command list (.atn) replayed | 1 | [ACT] |
| Batch / Droplets | batch | Run an action over a folder | 1 | https://helpx.adobe.com/photoshop/using/processing-batch-files.html |
| Image Processor | batch | Convert and resize a folder to JPEG, PSD, TIFF | 1 | same |
| Variables (data-driven graphics) | batch | Template layers filled from CSV rows | 1 | https://helpx.adobe.com/photoshop/using/creating-data-driven-graphics.html |
| Scripting (ExtendScript, UXP) | batch | JavaScript object model over Photoshop | 4 | https://developer.adobe.com/photoshop/uxp/ |
| Contact Sheet | batch | Grid layout of thumbnails | 1 | https://helpx.adobe.com/photoshop/using/contact-sheets-pdf-presentations.html |
| Export As / Quick Export / Save for Web | files | Resize, convert to sRGB, strip metadata, encode | 1 | https://helpx.adobe.com/photoshop/using/export-artboards-layers.html |
| Export layers / artboards to files | batch | Composite each layer or board and encode | 1 | same |
| History / Snapshots | batch | Undo stack of document states | 1 | https://helpx.adobe.com/photoshop/using/undo-history.html |
| Generator image assets | batch | Export driven by layer names | 1 | https://helpx.adobe.com/photoshop/using/generate-assets-layers.html |

## Files and colour management

| Feature | Group | What it is underneath | Rung | Source |
|---|---|---|---|---|
| PSD / PSB | files | Adobe's published format; Pillow reads PSD only (Photoshop 2.5/3.0 era files), psd-tools reads layers and composes | 2 | https://www.adobe.com/devnet-apps/photoshop/fileformatashtml/; [PIL] |
| Layered TIFF | files | Baseline TIFF plus Adobe's layer data tag | 2 | [FILE] |
| JPEG, PNG, GIF, BMP, WebP | files | Pillow codecs | 1 | [PIL] |
| AVIF, HEIC, JPEG XL | files | Pillow AVIF saves 8-bit only; HEIC through pillow-heif | 2 | [PIL] |
| Camera raw (CR3, NEF, ARW, DNG) | files | Demosaic then colour pipeline | 2 | https://helpx.adobe.com/camera-raw/using/supported-cameras.html; https://en.wikipedia.org/wiki/Demosaicing |
| PDF / EPS open | files | Rasterise through Ghostscript or similar | 2 | [FILE] |
| File Info (metadata) | files | XMP packet with EXIF and IPTC mirrors | 2 | https://helpx.adobe.com/photoshop/using/metadata-notes.html |
| Video layers / timeline | files | Frames as layers | 2 | https://helpx.adobe.com/photoshop/using/video-layers.html |
| 3D features | files | Removed from Photoshop; not a target | 4 | https://helpx.adobe.com/photoshop/kb/3d-faq.html |
| Convert to Profile / Assign Profile | files | Convert transforms pixels; Assign only relabels | 1 | https://helpx.adobe.com/photoshop/using/color-settings.html; https://pillow.readthedocs.io/en/stable/reference/ImageCms.html |
| Proof Colors / Gamut Warning | files | Transform to the output profile and back; flag out-of-gamut pixels | 1 | https://helpx.adobe.com/photoshop/using/proofing-colors.html |
| Bit depth 8 / 16 / 32 | files | Integer 8, integer 16 (Photoshop stores 0..32768), 32-bit float linear | 1 | https://helpx.adobe.com/photoshop/using/bit-depth.html |
| Histogram / Info / Color Sampler | files | Pixel readouts and per-channel histograms | 1 | https://helpx.adobe.com/photoshop/using/viewing-histograms-pixel-values.html |
| Raw demosaic | files | Bayer CFA interpolation (AHD, DCB, LMMSE) | 2 | https://en.wikipedia.org/wiki/Demosaicing |

## Rung tally

Counted from the tables above (2026-11-16, grep of the rung column): about 132 rung 1, 29 rung 2, 26 rung 3, 5 rung 4. Most rows are rung 1. Rung 3 is concentrated in selection (subject, sky, hair), neural filters and generative fill. Rung 4 is limited to the Mixer Brush, procedural Flame/Tree/Frame, .ai path export, 3D and Photoshop scripting itself.
