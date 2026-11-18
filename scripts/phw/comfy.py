"""Rung 3: local models through a ComfyUI server (standard library HTTP only).

Routes (node class names checked against GET /object_info on 2026-11-17, see
references/comfyui-nodes.md):
  cutout --method birefnet  core LoadBackgroundRemovalModel + RemoveBackground (birefnet.safetensors, MIT)
  fill/remove --method lama Acly comfyui-inpaint-nodes INPAINT_LoadInpaintModel + INPAINT_InpaintWithModel (big-lama.pt, Apache-2.0)
  select --text "..."       kijai Florence2ModelLoader (Florence-2-large, MIT) caption_to_phrase_grounding boxes
                            into kijai Sam2Segmentation (sam2.1_hiera_base_plus, Apache-2.0)
Flow: upload the image (/upload/image), POST /prompt with an API-format graph, poll /history,
fetch the PreviewImage output (/view). A busy queue is waited on, not failed. Any failure
raises Unavailable(reason) and the caller falls back to its rung 1/2 method.
PHW_COMFY_URL overrides the server (default http://127.0.0.1:8199); PHW_COMFY_WAIT is the
longest wait in seconds for queue + run (default 1800). PHW_RUNG_MAX below 3 hides this rung.
"""
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import numpy as np
from PIL import Image

from . import core

BIREFNET = "birefnet.safetensors"
LAMA = "big-lama.pt"
FLORENCE = "Florence-2-large"
SAM2 = "sam2.1_hiera_base_plus.safetensors"


class Unavailable(Exception):
    """Rung 3 cannot run; str(e) is the reason shown after 'fell back:'."""


def url():
    return os.environ.get("PHW_COMFY_URL", "http://127.0.0.1:8199").rstrip("/")


def _req(path, data=None, headers=None, timeout=30, tries=3):
    """One HTTP call. GETs retry on a timeout: the server stalls while it loads a model."""
    for k in range(tries if data is None else 1):
        req = urllib.request.Request(url() + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = e.read()[:400].decode("utf-8", "replace")
            raise Unavailable(f"ComfyUI HTTP {e.code} on {path}: {body}")
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            timed_out = isinstance(e, TimeoutError) or isinstance(reason, TimeoutError)
            if not timed_out or k == tries - 1 or data is not None:
                raise Unavailable(f"ComfyUI server unreachable at {url()} ({reason})")
            time.sleep(2.0)


def get_json(path, timeout=30):
    return json.loads(_req(path, timeout=timeout))


def check(nodes, models=None):
    """Raise Unavailable unless the rung is allowed, the server answers and every node exists.
    models: {(node, input): filename} that must be among that input's options."""
    if core.rung_max() < 3:
        raise Unavailable(f"PHW_RUNG_MAX={core.rung_max()} hides rung 3")
    get_json("/system_stats", timeout=20)
    for n in nodes:
        info = get_json("/object_info/" + urllib.parse.quote(n))
        if n not in info:
            raise Unavailable(f"ComfyUI node {n} is not installed")
        if models:
            for (node, inp), fname in models.items():
                if node != n:
                    continue
                spec = {**info[n]["input"].get("required", {}), **info[n]["input"].get("optional", {})}[inp]
                opts = spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])
                if fname not in opts:
                    raise Unavailable(f"model {fname} is not on the server for {node}.{inp}")


def png_bytes(a):
    """float 0..1 HxW or HxWx3 -> 8-bit PNG bytes."""
    a8 = np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(a8, "L" if a8.ndim == 2 else "RGB").save(buf, "PNG")
    return buf.getvalue()


def upload(data, name):
    b = "----phw" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + data + \
        f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n".encode()
    r = json.loads(_req("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={b}"}, 120))
    return (r.get("subfolder") + "/" if r.get("subfolder") else "") + r["name"]


def run_graph(graph, wait=None):
    """Queue the graph, wait (queue + run) and return its history outputs."""
    wait = float(wait or os.environ.get("PHW_COMFY_WAIT", 1800))
    q = get_json("/queue")
    ahead = len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
    r = json.loads(_req("/prompt", json.dumps({"prompt": graph, "client_id": "phw"}).encode(),
                        {"Content-Type": "application/json"}))
    if r.get("node_errors"):
        raise Unavailable(f"ComfyUI rejected the graph: {json.dumps(r['node_errors'])[:300]}")
    pid = r["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < wait:
        h = get_json("/history/" + pid)
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                raise Unavailable(f"ComfyUI run failed: {json.dumps(msgs)[:300]}")
            if st.get("completed", True):
                return h[pid]["outputs"], ahead, time.time() - t0
        time.sleep(1.0)
    raise Unavailable(f"ComfyUI did not finish within {wait:.0f} s ({ahead} jobs were ahead)")


def fetch_first(outputs, node="out"):
    imgs = outputs.get(node, {}).get("images") or []
    if not imgs:
        raise Unavailable("ComfyUI returned no image")
    i = imgs[0]
    q = urllib.parse.urlencode({"filename": i["filename"], "subfolder": i.get("subfolder", ""),
                                "type": i.get("type", "temp")})
    im = Image.open(io.BytesIO(_req("/view?" + q, timeout=120)))
    return np.asarray(im.convert("RGB"), np.float32) / 255.0


# ---------------------------------------------------------------- graphs (API format)
def graph_birefnet(image):
    return {
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "mdl": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": BIREFNET}},
        "rb": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["mdl", 0], "image": ["img", 0]}},
        "m2i": {"class_type": "MaskToImage", "inputs": {"mask": ["rb", 0]}},
        "out": {"class_type": "PreviewImage", "inputs": {"images": ["m2i", 0]}},
    }


def graph_lama(image, mask, seed):
    return {
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "mimg": {"class_type": "LoadImage", "inputs": {"image": mask}},
        "msk": {"class_type": "ImageToMask", "inputs": {"image": ["mimg", 0], "channel": "red"}},
        "mdl": {"class_type": "INPAINT_LoadInpaintModel", "inputs": {"model_name": LAMA}},
        "inp": {"class_type": "INPAINT_InpaintWithModel",
                "inputs": {"inpaint_model": ["mdl", 0], "image": ["img", 0], "mask": ["msk", 0], "seed": int(seed)}},
        "out": {"class_type": "PreviewImage", "inputs": {"images": ["inp", 0]}},
    }


def graph_text_select(image, text, seed, index=""):
    return {
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "fl": {"class_type": "Florence2ModelLoader", "inputs": {"model": FLORENCE, "precision": "fp16"}},
        "run": {"class_type": "Florence2Run",
                "inputs": {"image": ["img", 0], "florence2_model": ["fl", 0], "text_input": text,
                           "task": "caption_to_phrase_grounding", "fill_mask": True, "keep_model_loaded": False,
                           "max_new_tokens": 1024, "num_beams": 3, "do_sample": False,
                           "output_mask_select": "", "seed": max(1, int(seed))}},
        "co": {"class_type": "Florence2toCoordinates", "inputs": {"data": ["run", 3], "index": index, "batch": False}},
        "sam": {"class_type": "DownloadAndLoadSAM2Model",
                "inputs": {"model": SAM2, "segmentor": "single_image", "device": "cuda", "precision": "fp16"}},
        "seg": {"class_type": "Sam2Segmentation",
                "inputs": {"sam2_model": ["sam", 0], "image": ["img", 0], "keep_model_loaded": False,
                           "bboxes": ["co", 1], "individual_objects": False}},
        "m2i": {"class_type": "MaskToImage", "inputs": {"mask": ["seg", 0]}},
        "out": {"class_type": "PreviewImage", "inputs": {"images": ["m2i", 0]}},
    }


# ---------------------------------------------------------------- routes
def _tag():
    return uuid.uuid4().hex[:10]


def birefnet_mask(rgb):
    check(["LoadBackgroundRemovalModel", "RemoveBackground", "MaskToImage"],
          {("LoadBackgroundRemovalModel", "bg_removal_name"): BIREFNET})
    name = upload(png_bytes(rgb), f"phw_{_tag()}.png")
    outs, ahead, secs = run_graph(graph_birefnet(name))
    m = fetch_first(outs)[..., 0]
    return m, {"model": BIREFNET, "server": url(), "seconds": round(secs, 1), "queued_ahead": ahead}


def lama_fill(rgb, hole, seed):
    check(["INPAINT_LoadInpaintModel", "INPAINT_InpaintWithModel", "ImageToMask"],
          {("INPAINT_LoadInpaintModel", "model_name"): LAMA})
    t = _tag()
    name = upload(png_bytes(rgb), f"phw_{t}.png")
    mname = upload(png_bytes(hole.astype(np.float32)), f"phw_{t}_mask.png")
    outs, ahead, secs = run_graph(graph_lama(name, mname, seed))
    res = fetch_first(outs)
    if res.shape[:2] != hole.shape:
        raise Unavailable(f"LaMa returned {res.shape[1]}x{res.shape[0]}, expected {hole.shape[1]}x{hole.shape[0]}")
    return res, {"model": LAMA, "seed": int(seed), "server": url(), "seconds": round(secs, 1), "queued_ahead": ahead}


def text_mask(rgb, text, seed):
    check(["Florence2ModelLoader", "Florence2Run", "Florence2toCoordinates", "DownloadAndLoadSAM2Model",
           "Sam2Segmentation"],
          {("Florence2ModelLoader", "model"): FLORENCE, ("DownloadAndLoadSAM2Model", "model"): SAM2})
    name = upload(png_bytes(rgb), f"phw_{_tag()}.png")
    outs, ahead, secs = run_graph(graph_text_select(name, text, seed))
    m = fetch_first(outs)[..., 0]
    return m, {"model": f"{FLORENCE} + {SAM2}", "seed": max(1, int(seed)), "server": url(),
               "seconds": round(secs, 1), "queued_ahead": ahead}
