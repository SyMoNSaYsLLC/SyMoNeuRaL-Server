"""Stock workflows, in ComfyUI's prompt format, built for the weights actually on this disk.

Nothing here is a template copied from a tutorial. Every class name, every input name and
every filename below was read out of the installed node set on this box:

    symoneural-ui/.venv/bin/python  ->  folder_paths + custom_nodes/ComfyUI-GGUF
    UnetLoaderGGUF      required: unet_name                  -> MODEL
    DualCLIPLoaderGGUF  required: clip_name1, clip_name2, type -> CLIP
    VAELoader           required: vae_name                   -> VAE
    CLIPTextEncode      required: text, clip                 -> CONDITIONING
    FluxGuidance        required: conditioning, guidance     -> CONDITIONING
    EmptySD3LatentImage required: width, height, batch_size  -> LATENT
    KSampler            required: model, seed, steps, cfg, sampler_name, scheduler,
                                  positive, negative, latent_image, denoise -> LATENT
    VAEDecode           required: samples, vae               -> IMAGE
    SaveImage           required: images, filename_prefix    (OUTPUT_NODE = True)

and the four filenames are the ones `folder_paths.get_filename_list` returns after
`extra_model_paths.yaml` is loaded.

## Why FLUX.1-schnell and not SD1.5

Because it is what is here. `models/image/` holds a quantised schnell UNet, the T5-XXL
and CLIP-L text encoders, and the FLUX autoencoder -- 12 GB that the stable-diffusion.cpp
surface already uses. `ComfyUI/models/checkpoints/` is empty apart from its placeholder, so a
`CheckpointLoaderSimple` graph (the shape every ComfyUI example uses) has nothing to load and
would fail at the first node.

## Schnell's parameters are not SD's, and getting them wrong looks like a broken model

- **`cfg` is 1.0.** Schnell is guidance-distilled; classifier-free guidance is baked in.
  Raising cfg does not sharpen the image, it destroys it.
- **`steps` is 4.** That is the point of schnell. 20 steps costs five times as long for no
  improvement.
- **The negative prompt is inert.** With cfg 1.0 there is no unconditional branch to steer
  away from, so the negative CLIPTextEncode is wired only because KSampler requires the input.
  The UI says so rather than offering a negative box that silently does nothing.
- **`EmptySD3LatentImage`, not `EmptyLatentImage`.** FLUX's latent space is 16-channel; the
  SD-era node emits 4 channels and KSampler fails on the shape mismatch.
- **Dimensions should be multiples of 16.**
"""
from __future__ import annotations

import copy

__all__ = ["FLUX_SCHNELL", "DEFAULT", "get", "names", "PARAMETER_MAP"]

UNET = "symoneural-image-unet-q4_k.gguf"
T5 = "symoneural-image-t5-q8_0.gguf"
CLIP_L = "symoneural-image-clip.safetensors"
VAE = "symoneural-image-vae.safetensors"

FLUX_SCHNELL: dict = {
    "1": {"class_type": "UnetLoaderGGUF",
          "inputs": {"unet_name": UNET}},
    # `type` must be "flux": it selects which text-encoder pair the CLIP object expects, and
    # the wrong value produces a CLIP that encodes to the wrong shape rather than an error.
    #
    # DualCLIPLoaderSDCPP, not DualCLIPLoaderGGUF. This was found by running a render, not by
    # reading the catalogue: the stock GGUF loader validates fine against /object_info and
    # then fails at execution with "This gguf file is incompatible with llama.cpp!", because
    # the local symoneural-image-t5-q8_0.gguf is a stable-diffusion.cpp file (no `general.architecture`,
    # original HuggingFace tensor names) and upstream's text-model branch rejects those.
    # `custom_nodes/symoneural_gguf` accepts them; its docstring explains why that is safe.
    "2": {"class_type": "DualCLIPLoaderSDCPP",
          "inputs": {"clip_name1": T5, "clip_name2": CLIP_L, "type": "flux"}},
    "3": {"class_type": "VAELoader",
          "inputs": {"vae_name": VAE}},
    "4": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "a photograph", "clip": ["2", 0]}},
    # FLUX takes its guidance as an embedded conditioning value, not through cfg.
    "5": {"class_type": "FluxGuidance",
          "inputs": {"conditioning": ["4", 0], "guidance": 3.5}},
    # Required by KSampler and inert at cfg 1.0. See the module docstring.
    "6": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "", "clip": ["2", 0]}},
    "7": {"class_type": "EmptySD3LatentImage",
          "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "8": {"class_type": "KSampler",
          "inputs": {"model": ["1", 0], "seed": 0, "steps": 4, "cfg": 1.0,
                     "sampler_name": "euler", "scheduler": "simple",
                     "positive": ["5", 0], "negative": ["6", 0],
                     "latent_image": ["7", 0], "denoise": 1.0}},
    "9": {"class_type": "VAEDecode",
          "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
    "10": {"class_type": "SaveImage",
           "inputs": {"images": ["9", 0], "filename_prefix": "symoneural/studio"}},
}

# Which node input each friendly parameter name addresses in the stock graph. `generate_image`
# uses this so a caller -- or the LLM -- can say `width=768` without knowing that width lives
# on node 7. A workflow supplied by the canvas will not match these ids, which is exactly why
# `graph.inject` addresses are explicit and this map is only the default's convenience layer.
PARAMETER_MAP: dict[str, str] = {
    "prompt": "4.text",
    "negative": "6.text",
    "guidance": "5.guidance",
    "width": "7.width",
    "height": "7.height",
    "batch_size": "7.batch_size",
    "seed": "8.seed",
    "steps": "8.steps",
    "cfg": "8.cfg",
    "sampler_name": "8.sampler_name",
    "scheduler": "8.scheduler",
    "denoise": "8.denoise",
    "filename_prefix": "10.filename_prefix",
}

_LIBRARY: dict[str, dict] = {"flux-schnell": FLUX_SCHNELL}
DEFAULT = "flux-schnell"


def names() -> list[str]:
    return sorted(_LIBRARY)


def get(name: str = DEFAULT) -> dict:
    """A deep copy, always. These dicts are module-level and a caller that injected into the
    original would silently change every later generation on the box."""
    if name not in _LIBRARY:
        raise KeyError(f"unknown workflow {name!r}; have {names()}")
    return copy.deepcopy(_LIBRARY[name])


def describe(name: str = DEFAULT) -> dict:
    """What the UI shows about a stock workflow before it is run."""
    g = _LIBRARY.get(name)
    if g is None:
        return {"error": "unknown_workflow", "name": name, "available": names()}
    return {
        "name": name,
        "node_count": len(g),
        "classes": sorted({n["class_type"] for n in g.values()}),
        "parameters": sorted(PARAMETER_MAP),
        "weights": [UNET, T5, CLIP_L, VAE],
        "requires_custom_nodes": ["ComfyUI-GGUF", "symoneural_gguf"],
        "notes": [
            "cfg is 1.0 because schnell is guidance-distilled; raising it degrades the image",
            "4 steps is the design point, not a shortcut",
            "the negative prompt has no effect at cfg 1.0 and is wired only to satisfy KSampler",
        ],
    }
