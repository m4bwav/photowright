# Live run: decompose with Qwen-Image-Layered (2026-11-18, session 42)

Server: ComfyUI 127.0.0.1:8199 (RTX 5060 Ti 16 GB), queue empty. phw 0.25.0 branch s42-layers.

Input: a synthetic 640x480 scene made by tests/test_phw22.py `scene(640, 480)`: flat blue background (40,120,200), a red disc (bbox 10,20-60,70) and a yellow square (70,10-110,50) in the top-left corner.

Command:

    python scripts/phw.py decompose scene.png --model qwen-layered --layers 3 \
      --prompt "a red ball and a yellow square on a blue background" -o scene.psd --png png

| Measure | Value |
|---|---|
| Time (cold load, 20 steps) | 177.1 s, 0 jobs ahead |
| Working size | 736x560 (about 640x640, multiples of 16), layers resized back with Lanczos |
| Layers produced | 3 RGBA |
| Alpha coverage (alpha > 0.5) | layer 1 1.000, layer 2 0.000, layer 3 0.012 |
| Recomposite PSNR (flattened layers vs source) | 36.31 dB |
| Flattened alpha mean | 1.000 |

What came back, looked at on a checker sheet:
- Layer 1 (bottom) is the background, fully opaque, plain blue with the disc and square removed and painted over (hidden area invented, cleanly).
- Layer 2 is empty in effect: faint alpha everywhere (max 61/255, none above 0.5).
- Layer 3 holds both the disc and the square together (1.2% of the frame matches their area).
- So the model's order is bottom first (background first), which is the order phw writes. With 3 layers asked for and 2 objects, it grouped the objects into one layer and left one nearly empty; ask for fewer layers or caption each object.

Verdict: PASS. The route works end to end (PSD and PNG layers written), the background is clean, the flatten is close to the source (36 dB; losses are the 736x560 round trip and repainted edges). Not measured: photos, more layers, warm-run time.
