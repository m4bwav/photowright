"""Rung 3: local models through a ComfyUI server (standard library HTTP only).

Routes (node class names checked against GET /object_info on 2026-11-17, see
references/comfyui-nodes.md):
  cutout --method birefnet  core LoadBackgroundRemovalModel + RemoveBackground (birefnet.safetensors, MIT)
  fill/remove --method lama Acly comfyui-inpaint-nodes INPAINT_LoadInpaintModel + INPAINT_InpaintWithModel (big-lama.pt, Apache-2.0)
  fill --model qwen-edit --prompt "..."  core Qwen-Image-Edit-2511 (fp8mixed + Lightning 4-step LoRA,
                            Apache-2.0) with SetLatentNoiseMask; refuses a busy queue (PHW_COMFY_MAX_AHEAD)
  relight --prompt "..." --light left  kijai IC-Light v1 fc (LoadAndApplyICLightUnet + ICLightConditioning,
                            iclight_sd15_fc on SD1.5 v1-5-pruned-emaonly) with the light direction as an init
                            gradient shaded by Depth Anything V2 Small (controlnet_aux, vits, Apache-2.0);
                            refuses a busy queue (PHW_COMFY_MAX_AHEAD)
  decompose --model qwen-layered  core Qwen-Image-Layered (fp8mixed, Apache-2.0) after the core blueprint
                            "Image to Layers (Qwen-Image-Layered)": EmptyQwenImageLayeredLatentImage, ReferenceLatent,
                            LatentCut + LatentCutToBatch, layered VAE (RGBA out); refuses a busy queue
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
SEEDVR2 = {"3b": "seedvr2_3b_int8_convrot.safetensors", "7b": "seedvr2_7b_int8_convrot.safetensors"}
SEEDVR2_VAE = "seedvr2_ema_vae_fp16.safetensors"
QWEN_EDIT = "qwen_image_edit_2511_fp8mixed.safetensors"
QWEN_LORA = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
QWEN_CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
QWEN_VAE = "qwen_image_vae.safetensors"
SD15 = "v1-5-pruned-emaonly.safetensors"
ICLIGHT = "iclight_sd15_fc.safetensors"
DAV2_SMALL = "depth_anything_v2_vits.pth"
QWEN_LAYERED = "qwen_image_layered_fp8mixed.safetensors"
QWEN_LAYERED_VAE = "qwen_image_layered_vae.safetensors"
LIGHTS = ("left", "right", "top", "bottom", "none")


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


def run_graph(graph, wait=None, max_ahead=None):
    """Queue the graph, wait (queue + run) and return its history outputs.
    max_ahead: refuse (Unavailable) instead of queueing when more jobs than this are ahead."""
    wait = float(wait or os.environ.get("PHW_COMFY_WAIT", 1800))
    q = get_json("/queue")
    ahead = len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
    if max_ahead is not None and ahead > max_ahead:
        raise Unavailable(f"ComfyUI is busy ({ahead} jobs ahead; PHW_COMFY_MAX_AHEAD={max_ahead})")
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


def fetch_all(outputs, node="out"):
    """Every image of one output node as float RGBA arrays (alpha 1 when the PNG has none)."""
    res = []
    for i in outputs.get(node, {}).get("images") or []:
        q = urllib.parse.urlencode({"filename": i["filename"], "subfolder": i.get("subfolder", ""),
                                    "type": i.get("type", "temp")})
        im = Image.open(io.BytesIO(_req("/view?" + q, timeout=120)))
        res.append(np.asarray(im.convert("RGBA"), np.float32) / 255.0)
    if not res:
        raise Unavailable("ComfyUI returned no image")
    return res


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


def graph_seedvr2(image, width, height, seed, unet):
    """One still through core SeedVR2 (one-step diffusion SR), after the core blueprint
    'Upscale Video (SeedVR2 3B Int8)' without its video and temporal-chunk nodes."""
    tile = {"tile_size": 512, "overlap": 128, "temporal_size": 64, "temporal_overlap": 8}
    return {
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "rs": {"class_type": "ImageScale", "inputs": {"image": ["img", 0], "upscale_method": "lanczos",
                                                       "width": int(width), "height": int(height), "crop": "disabled"}},
        "pre": {"class_type": "SeedVR2Preprocess", "inputs": {"resized_images": ["rs", 0]}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": SEEDVR2_VAE}},
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "enc": {"class_type": "VAEEncodeTiled", "inputs": {"pixels": ["pre", 0], "vae": ["vae", 0], **tile}},
        "cond": {"class_type": "SeedVR2Conditioning", "inputs": {"model": ["unet", 0], "vae_conditioning": ["enc", 0]}},
        "ks": {"class_type": "KSampler", "inputs": {"model": ["unet", 0], "positive": ["cond", 0],
                                                    "negative": ["cond", 1], "latent_image": ["enc", 0],
                                                    "seed": int(seed), "steps": 1, "cfg": 1.0,
                                                    "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "dec": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0], **tile}},
        "post": {"class_type": "SeedVR2PostProcessing", "inputs": {"images": ["dec", 0],
                                                                  "original_resized_images": ["rs", 0],
                                                                  "color_correction_method": "lab"}},
        "out": {"class_type": "PreviewImage", "inputs": {"images": ["post", 0]}},
    }


def graph_qwen_edit(image, mask, prompt, seed, steps=4, megapixels=1.0):
    """Qwen-Image-Edit-2511 by instruction, after the core 2511 template (Lightning 4-step LoRA,
    AuraFlow shift 3.1, CFGNorm, index_timestep_zero reference latents). The image and mask are
    scaled to ~1 MP; SetLatentNoiseMask keeps the sampler inside the mask. The caller resizes the
    result back and composites through the mask, so outside pixels stay the source's."""
    sc = {"upscale_method": "lanczos", "megapixels": float(megapixels), "resolution_steps": 8}
    enc = {"clip": ["clip", 0], "vae": ["vae", 0], "image1": ["rs", 0]}
    return {
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "rs": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["img", 0], **sc}},
        "mimg": {"class_type": "LoadImage", "inputs": {"image": mask}},
        "mrs": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["mimg", 0], **sc}},
        "msk": {"class_type": "ImageToMask", "inputs": {"image": ["mrs", 0], "channel": "red"}},
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": QWEN_EDIT, "weight_dtype": "default"}},
        "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "lora_name": QWEN_LORA,
                                                                 "strength_model": 1.0}},
        "ms": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["lora", 0], "shift": 3.1}},
        "cn": {"class_type": "CFGNorm", "inputs": {"model": ["ms", 0], "strength": 1.0}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": QWEN_CLIP, "type": "qwen_image"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_VAE}},
        "pos0": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {**enc, "prompt": prompt}},
        "neg0": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {**enc, "prompt": ""}},
        "pos": {"class_type": "FluxKontextMultiReferenceLatentMethod",
                "inputs": {"conditioning": ["pos0", 0], "reference_latents_method": "index_timestep_zero"}},
        "neg": {"class_type": "FluxKontextMultiReferenceLatentMethod",
                "inputs": {"conditioning": ["neg0", 0], "reference_latents_method": "index_timestep_zero"}},
        "enc": {"class_type": "VAEEncode", "inputs": {"pixels": ["rs", 0], "vae": ["vae", 0]}},
        "lat": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["enc", 0], "mask": ["msk", 0]}},
        "ks": {"class_type": "KSampler", "inputs": {"model": ["cn", 0], "positive": ["pos", 0], "negative": ["neg", 0],
                                                    "latent_image": ["lat", 0], "seed": int(seed), "steps": int(steps),
                                                    "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                                                    "denoise": 1.0}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}},
        "out": {"class_type": "PreviewImage", "inputs": {"images": ["dec", 0]}},
    }


def relight_size(w, h, area=512 * 640):
    """SD1.5 working size: about `area` pixels, both sides multiples of 64."""
    k = (area / float(w * h)) ** 0.5
    return max(64, int(round(w * k / 64)) * 64), max(64, int(round(h * k / 64)) * 64)


def light_gradient(w, h, light):
    """Init image for IC-Light: bright on the light's side, dark on the far side (grey for 'none')."""
    if light == "none":
        return np.full((h, w, 3), 0.5, np.float32)
    t = np.linspace(1.0, 0.0, w if light in ("left", "right") else h, dtype=np.float32)
    if light in ("right", "bottom"):
        t = t[::-1]
    g = np.broadcast_to(t[None, :] if light in ("left", "right") else t[:, None], (h, w))
    return np.repeat(g[..., None], 3, axis=2).astype(np.float32)


def graph_iclight(image, light_image, prompt, seed, width, height, steps=25, cfg=2.0, denoise=0.9,
                  depth_mix=0.5, negative="lowres, bad anatomy, bad hands, cropped, worst quality"):
    """IC-Light v1 foreground-conditioned relight, after kijai's ComfyUI-IC-Light example: the source
    is the foreground latent, the light direction is an init latent (a gradient multiplied by the
    Depth Anything V2 Small depth so near surfaces catch more light) sampled at denoise 0.9.
    light_image None = no direction: start from IC-Light's empty latent at denoise 1."""
    sc = {"upscale_method": "lanczos", "width": int(width), "height": int(height), "crop": "disabled"}
    g = {
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "rs": {"class_type": "ImageScale", "inputs": {"image": ["img", 0], **sc}},
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": SD15}},
        "ic": {"class_type": "LoadAndApplyICLightUnet", "inputs": {"model": ["ckpt", 0], "model_path": ICLIGHT}},
        "pos0": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": prompt}},
        "neg0": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["ckpt", 1], "text": negative}},
        "fg": {"class_type": "VAEEncode", "inputs": {"pixels": ["rs", 0], "vae": ["ckpt", 2]}},
        "icc": {"class_type": "ICLightConditioning",
                "inputs": {"positive": ["pos0", 0], "negative": ["neg0", 0], "vae": ["ckpt", 2],
                           "foreground": ["fg", 0], "multiplier": 0.18215}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["ckpt", 2]}},
        "out": {"class_type": "PreviewImage", "inputs": {"images": ["dec", 0]}},
    }
    ks = {"model": ["ic", 0], "positive": ["icc", 0], "negative": ["icc", 1], "seed": int(seed),
          "steps": int(steps), "cfg": float(cfg), "sampler_name": "dpmpp_2m", "scheduler": "karras"}
    if light_image is None:
        ks.update(latent_image=["icc", 2], denoise=1.0)
    else:
        g.update({
            "limg": {"class_type": "LoadImage", "inputs": {"image": light_image}},
            "lrs": {"class_type": "ImageScale", "inputs": {"image": ["limg", 0], **sc}},
            "depth": {"class_type": "DepthAnythingV2Preprocessor",
                      "inputs": {"image": ["rs", 0], "ckpt_name": DAV2_SMALL,
                                 "resolution": max(64, min(int(width), int(height)) // 64 * 64)}},
            "drs": {"class_type": "ImageScale", "inputs": {"image": ["depth", 0], **sc}},
            "lit": {"class_type": "ImageBlend", "inputs": {"image1": ["lrs", 0], "image2": ["drs", 0],
                                                           "blend_factor": float(depth_mix),
                                                           "blend_mode": "multiply"}},
            "init": {"class_type": "VAEEncode", "inputs": {"pixels": ["lit", 0], "vae": ["ckpt", 2]}},
        })
        ks.update(latent_image=["init", 0], denoise=float(denoise))
    g["ks"] = {"class_type": "KSampler", "inputs": ks}
    return g


def layered_size(w, h, area=640 * 640):
    """Qwen-Image-Layered working size: about `area` pixels (the blueprint's 640x640), sides multiples of 16."""
    k = (area / float(w * h)) ** 0.5
    return max(16, int(round(w * k / 16)) * 16), max(16, int(round(h * k / 16)) * 16)


def graph_qwen_layered(image, layers, seed, prompt="", steps=20, cfg=2.5):
    """Image to RGBA layers, after the core blueprint 'Image to Layers (Qwen-Image-Layered)': the source
    (already at the working size) is VAE-encoded as a reference latent on both prompts, the empty layered
    latent has layers+1 frames, frame 0 is cut away and the rest decode as a batch of RGBA layers."""
    return {
        "img": {"class_type": "LoadImage", "inputs": {"image": image}},
        "size": {"class_type": "GetImageSize", "inputs": {"image": ["img", 0]}},
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": QWEN_LAYERED, "weight_dtype": "default"}},
        "ms": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["unet", 0], "shift": 1.0}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": QWEN_CLIP, "type": "qwen_image"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_LAYERED_VAE}},
        "enc": {"class_type": "VAEEncode", "inputs": {"pixels": ["img", 0], "vae": ["vae", 0]}},
        "pos0": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "neg0": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": ""}},
        "pos": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["pos0", 0], "latent": ["enc", 0]}},
        "neg": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["neg0", 0], "latent": ["enc", 0]}},
        "lat": {"class_type": "EmptyQwenImageLayeredLatentImage",
                "inputs": {"width": ["size", 0], "height": ["size", 1], "layers": int(layers), "batch_size": 1}},
        "ks": {"class_type": "KSampler", "inputs": {"model": ["ms", 0], "positive": ["pos", 0], "negative": ["neg", 0],
                                                    "latent_image": ["lat", 0], "seed": int(seed), "steps": int(steps),
                                                    "cfg": float(cfg), "sampler_name": "euler", "scheduler": "simple",
                                                    "denoise": 1.0}},
        "cut": {"class_type": "LatentCut", "inputs": {"samples": ["ks", 0], "dim": "t", "index": 1, "amount": 16384}},
        "batch": {"class_type": "LatentCutToBatch", "inputs": {"samples": ["cut", 0], "dim": "t", "slice_size": 1}},
        "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["batch", 0], "vae": ["vae", 0]}},
        "out": {"class_type": "PreviewImage", "inputs": {"images": ["dec", 0]}},
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


def seedvr2_upscale(rgb, width, height, seed, size="3b"):
    unet = SEEDVR2[size]
    check(["SeedVR2Preprocess", "SeedVR2Conditioning", "SeedVR2PostProcessing", "UNETLoader", "VAELoader"],
          {("UNETLoader", "unet_name"): unet, ("VAELoader", "vae_name"): SEEDVR2_VAE})
    name = upload(png_bytes(rgb), f"phw_{_tag()}.png")
    outs, ahead, secs = run_graph(graph_seedvr2(name, width, height, seed, unet))
    res = fetch_first(outs)
    if res.shape[:2] != (int(height), int(width)):
        raise Unavailable(f"SeedVR2 returned {res.shape[1]}x{res.shape[0]}, expected {width}x{height}")
    return res, {"model": unet, "seed": int(seed), "server": url(), "seconds": round(secs, 1), "queued_ahead": ahead}


def qwen_edit_fill(rgb, hole, prompt, seed):
    """Fill the hole by instruction. Returns the model image resized back to the source size
    (Lanczos); the caller composites through the hole. A busy queue is refused, not waited on:
    the model is ~20 GB and would sit behind long renders (PHW_COMFY_MAX_AHEAD, default 0)."""
    check(["TextEncodeQwenImageEditPlus", "FluxKontextMultiReferenceLatentMethod", "ModelSamplingAuraFlow",
           "CFGNorm", "SetLatentNoiseMask", "ImageScaleToTotalPixels", "LoraLoaderModelOnly", "UNETLoader",
           "CLIPLoader", "VAELoader"],
          {("UNETLoader", "unet_name"): QWEN_EDIT, ("LoraLoaderModelOnly", "lora_name"): QWEN_LORA,
           ("CLIPLoader", "clip_name"): QWEN_CLIP, ("VAELoader", "vae_name"): QWEN_VAE})
    t = _tag()
    name = upload(png_bytes(rgb), f"phw_{t}.png")
    mname = upload(png_bytes(hole.astype(np.float32)), f"phw_{t}_mask.png")
    max_ahead = int(os.environ.get("PHW_COMFY_MAX_AHEAD", 0))
    outs, ahead, secs = run_graph(graph_qwen_edit(name, mname, prompt, seed), max_ahead=max_ahead)
    res = fetch_first(outs)
    h, w = hole.shape
    if res.shape[:2] != (h, w):
        im = Image.fromarray(np.round(np.clip(res, 0, 1) * 255).astype(np.uint8)).resize((w, h), Image.LANCZOS)
        res = np.asarray(im, np.float32) / 255.0
    return res, {"model": QWEN_EDIT, "lora": QWEN_LORA, "seed": int(seed), "server": url(),
                 "seconds": round(secs, 1), "queued_ahead": ahead}


def iclight_relight(rgb, prompt, light, seed):
    """Relight by prompt and direction. Returns the model image resized back to the source size
    (Lanczos). IC-Light repaints the whole frame at SD1.5 size, so detail changes: the caller
    flags it. A busy queue is refused, not waited on (PHW_COMFY_MAX_AHEAD, default 0)."""
    if light not in LIGHTS:
        raise Unavailable(f"unknown light direction {light!r} (one of {', '.join(LIGHTS)})")
    check(["LoadAndApplyICLightUnet", "ICLightConditioning", "DepthAnythingV2Preprocessor", "CheckpointLoaderSimple",
           "ImageBlend", "ImageScale"],
          {("CheckpointLoaderSimple", "ckpt_name"): SD15, ("LoadAndApplyICLightUnet", "model_path"): ICLIGHT,
           ("DepthAnythingV2Preprocessor", "ckpt_name"): DAV2_SMALL})
    h, w = rgb.shape[:2]
    gw, gh = relight_size(w, h)
    t = _tag()
    name = upload(png_bytes(rgb), f"phw_{t}.png")
    lname = None if light == "none" else upload(png_bytes(light_gradient(gw, gh, light)), f"phw_{t}_light.png")
    max_ahead = int(os.environ.get("PHW_COMFY_MAX_AHEAD", 0))
    outs, ahead, secs = run_graph(graph_iclight(name, lname, prompt, seed, gw, gh), max_ahead=max_ahead)
    res = fetch_first(outs)
    if res.shape[:2] != (h, w):
        im = Image.fromarray(np.round(np.clip(res, 0, 1) * 255).astype(np.uint8)).resize((w, h), Image.LANCZOS)
        res = np.asarray(im, np.float32) / 255.0
    return res, {"model": f"{ICLIGHT} on {SD15}", "depth": DAV2_SMALL if light != "none" else None,
                 "seed": int(seed), "server": url(), "seconds": round(secs, 1), "queued_ahead": ahead,
                 "work_size": [gw, gh]}


def qwen_layered(rgb, layers, seed, prompt="", steps=20):
    """Split an image into RGBA layers with Qwen-Image-Layered. Returns a list of float RGBA arrays at
    the source size (Lanczos back from the working size), in the model's order, and an info dict.
    A busy queue is refused, not waited on (PHW_COMFY_MAX_AHEAD, default 0)."""
    check(["EmptyQwenImageLayeredLatentImage", "ReferenceLatent", "LatentCut", "LatentCutToBatch", "GetImageSize",
           "ModelSamplingAuraFlow", "UNETLoader", "CLIPLoader", "VAELoader"],
          {("UNETLoader", "unet_name"): QWEN_LAYERED, ("CLIPLoader", "clip_name"): QWEN_CLIP,
           ("VAELoader", "vae_name"): QWEN_LAYERED_VAE})
    h, w = rgb.shape[:2]
    gw, gh = layered_size(w, h)
    a8 = np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    small = np.asarray(Image.fromarray(a8, "RGB").resize((gw, gh), Image.LANCZOS), np.float32) / 255.0
    name = upload(png_bytes(small), f"phw_{_tag()}.png")
    max_ahead = int(os.environ.get("PHW_COMFY_MAX_AHEAD", 0))
    outs, ahead, secs = run_graph(graph_qwen_layered(name, layers, seed, prompt, steps), max_ahead=max_ahead)
    res = []
    for lay in fetch_all(outs):
        if lay.shape[:2] != (h, w):
            im = Image.fromarray(np.round(np.clip(lay, 0, 1) * 255).astype(np.uint8), "RGBA").resize((w, h), Image.LANCZOS)
            lay = np.asarray(im, np.float32) / 255.0
        res.append(lay.astype(np.float32))
    return res, {"model": QWEN_LAYERED, "vae": QWEN_LAYERED_VAE, "seed": int(seed), "steps": int(steps),
                 "server": url(), "seconds": round(secs, 1), "queued_ahead": ahead, "work_size": [gw, gh]}
