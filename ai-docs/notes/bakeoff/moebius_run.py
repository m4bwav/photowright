"""Moebius vs lama fill bake-off on 8199 (seam ratio, lower = better, 1 = invisible)."""
import json, sys, time
import numpy as np
from skimage import data
sys.path.insert(0, "scripts")
from phw import comfy, retouch

def graph_moebius(image, mask, seed):
    return {
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "mimg": {"class_type": "LoadImage", "inputs": {"image": mask}},
        "msk": {"class_type": "ImageToMask", "inputs": {"image": ["mimg", 0], "channel": "red"}},
        "mdl": {"class_type": "MoebiusModelLoader",
                "inputs": {"model_name": "pretrained/diffusion_pytorch_model.bin", "dtype": "fp32"}},
        "inp": {"class_type": "MoebiusInpaint",
                "inputs": {"pipe": ["mdl", 0], "image": ["img", 0], "mask": ["msk", 0], "steps": 20,
                           "guidance": 2.5, "seed": int(seed), "image_size": 512, "mask_dilate": 0, "paste": True}},
        "out": {"class_type": "PreviewImage", "inputs": {"images": ["inp", 0]}},
    }

cases = [("astronaut", data.astronaut(), (300, 60, 60, 60)), ("astronaut", data.astronaut(), (180, 200, 120, 120)),
         ("coffee", data.coffee(), (250, 150, 100, 80))]
rows = []
for name, img, (x, y, w, h) in cases:
    rgb = img.astype(np.float32) / 255
    hole = np.zeros(rgb.shape[:2], bool); hole[y:y + h, x:x + w] = True
    row = {"case": f"{name} {x},{y},{w},{h}"}
    lam, info = comfy.lama_fill(rgb, hole, 0)
    row["lama"] = retouch.seam_score(lam, hole)["ratio"]; row["lama_s"] = info["seconds"]
    t = comfy._tag()
    a = comfy.upload(comfy.png_bytes(rgb), f"phw_{t}.png")
    m = comfy.upload(comfy.png_bytes(hole.astype(np.float32)), f"phw_{t}_mask.png")
    outs, ahead, secs = comfy.run_graph(graph_moebius(a, m, 0))
    mo = comfy.fetch_first(outs)
    row["moebius_shape_ok"] = mo.shape[:2] == hole.shape
    row["moebius"] = retouch.seam_score(mo, hole)["ratio"] if row["moebius_shape_ok"] else None
    row["moebius_s"] = round(secs, 1)
    print(json.dumps(row), flush=True); rows.append(row)
json.dump(rows, open("ai-docs/notes/bakeoff/results-moebius-2026-11-18.json", "w"), indent=1)
