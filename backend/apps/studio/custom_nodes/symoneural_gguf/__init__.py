"""Load stable-diffusion.cpp-style text-encoder GGUFs in ComfyUI.

## The problem this solves, precisely

`backend/models/image/symoneural-image-t5-q8_0.gguf` is a **stable-diffusion.cpp** GGUF: it carries no
`general.architecture` field, and its tensors use the original HuggingFace T5 names
(`encoder.block.0.layer.0.SelfAttention.k.weight`, `shared.weight`,
`encoder.final_layer_norm.weight`).

`ComfyUI-GGUF` refuses it at `loader.py:96`:

    if arch_str in [None, "pig", "cow"]:
        if is_text_model:
            raise ValueError("This gguf file is incompatible with llama.cpp! ...")

That is a **guard, not a capability gap**. Three facts make this safe to step around, and all
three were checked against the file on this disk rather than assumed:

1. The loading loop below the guard is architecture-agnostic -- it wraps every tensor as a
   `GGMLTensor` and never consults `arch_str` again except for one SDXL shape workaround that
   is gated on `arch_str == "sdxl"`.
2. Image models with no arch already take the `compat = "sd.cpp"` path and work. Your FLUX
   UNet is such a file. Only the *text* branch raises.
3. `T5_SD_MAP` exists to rename llama.cpp tensors (`enc.blk.0.attn_q`) **into** the names this
   file already has. It is not needed here -- and it is actively destructive here, because
   `sd_map_replace` does a blind substring `k.replace("enc.", "encoder.")`, which rewrites an
   existing `encoder.block...` key to `encoderoder.block...`. So this loader calls
   `gguf_sd_loader` directly and never applies the map.

## Why a separate pack instead of a patch

Editing `custom_nodes/ComfyUI-GGUF/loader.py` would work today and be silently reverted by the
next `git pull` in that clone, taking image generation down with it. This pack touches nothing
upstream; it imports the already-loaded module out of `sys.modules` so `GGMLTensor` is the
*same class object* the rest of ComfyUI-GGUF's custom ops do `isinstance` checks against.
Loading it by file path instead would create a second, unrelated class of the same name and
the failure would be a baffling dtype error deep in a matmul.

Alphabetical load order (`ComfyUI-GGUF` before `symoneural_gguf`) is what guarantees the
module is already present. `_gguf_module` raises a legible error rather than relying on it.
"""
import logging
import pathlib
import sys
from contextlib import contextmanager
from functools import lru_cache

import gguf
import torch


def _gguf_module(name: str):
    """The *already-imported* ComfyUI-GGUF submodule, found by file path, not by module name.

    Identity matters more than convenience here. ComfyUI-GGUF's custom ops dispatch on
    `GGMLTensor` via `__torch_function__`, and torch compares **class objects**, not class
    names. Import the same file twice under two module names and you get two unrelated
    classes; the model's ops then refuse every tensor this loader produced:

        Multiple dispatch failed for 'torch.nn.linear'; all __torch_function__ handlers
        returned NotImplemented:
          - tensor subclass <class 'custom_nodes.ComfyUI-GGUF.ops.GGMLTensor'>
          - tensor subclass <class '/home/.../custom_nodes/ComfyUI-GGUF.ops.GGMLTensor'>

    That is a real failure this file caused once. ComfyUI names custom-node modules from the
    path it loaded them by (here: the full absolute path, dashes and all), and that scheme has
    varied between versions -- so guessing keys such as "ComfyUI-GGUF.loader" is exactly what
    produced the duplicate. Scanning `sys.modules` for a module whose `__file__` *is* the
    target file cannot pick a copy: the already-loaded module is the one ComfyUI itself is
    using, whatever it called it.

    **Called lazily, never at import time.** ComfyUI walks `custom_nodes` in `os.listdir`
    order, which is filesystem order, not alphabetical -- the tidy sorted list it prints at
    the end is `sorted(node_import_times)` and says nothing about what loaded first. This pack
    was in fact imported *before* ComfyUI-GGUF, saw an empty `sys.modules`, and failed to
    import at all. Everything below resolves on first use instead, by which time every pack
    is loaded regardless of order.
    """
    # Matched by *shape of path*, not by an absolute path computed from `__file__`.
    #
    # This pack no longer lives inside the render UI tree: engines/ is gitignored in full, so
    # the source of truth is `backend/apps/studio/custom_nodes/symoneural_gguf/`
    # and `scripts/symoneural-ui.sh start` symlinks it into `custom_nodes/`. The previous version
    # computed the sibling as `Path(__file__).resolve().parent.parent / "ComfyUI-GGUF"`, and
    # `.resolve()` walks *through* that symlink -- so it went looking for ComfyUI-GGUF next
    # to itself inside `backend/apps/`, where it will never be, and every node in this pack
    # 500'd on `/object_info`. That is a real failure, caught by restarting the server after
    # the link was made rather than by reading the diff.
    #
    # Matching on the tail of the path avoids the question entirely: it does not care where
    # this file is, only that ComfyUI has already imported a module from a directory named
    # ComfyUI-GGUF. Scanning `sys.modules` rather than importing by path is still the point
    # -- see the docstring; a second import means a second GGMLTensor class and every render
    # fails in torch dispatch.
    tail = ("ComfyUI-GGUF", f"{name}.py")
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if not path:
            continue
        parts = pathlib.Path(path).parts
        if len(parts) >= 2 and parts[-2:] == tail:
            return module
    raise ImportError(
        f"ComfyUI has not imported ComfyUI-GGUF/{name}.py. Either the pack is not installed "
        "in custom_nodes/, or it failed to load -- check run/comfyui.log for its own "
        "traceback. Importing it here by path would create a second GGMLTensor class and "
        "every render would fail in torch dispatch, so this raises instead."
    )


@lru_cache(maxsize=None)
def _loader():
    return _gguf_module("loader")


@lru_cache(maxsize=None)
def _upstream_nodes():
    return _gguf_module("nodes")

# The HF-T5 fingerprint. Checked before the guard is stepped around, so a genuinely
# unsupported file still fails -- just with a message that says what was wrong with it.
_T5_MARKERS = ("encoder.final_layer_norm.weight", "shared.weight")


def _is_hf_t5(path: str) -> bool:
    reader = gguf.GGUFReader(path)
    if "general.architecture" in reader.fields:
        return False          # a normal llama.cpp file; upstream handles it correctly
    names = {t.name for t in reader.tensors}
    return all(m in names for m in _T5_MARKERS)


@contextmanager
def _claim_arch(arch: str = "t5encoder"):
    """Make `general.architecture` read as a supported text arch for the duration of one load.

    Patching the *reader field lookup* rather than the file keeps this to a single, reversible
    seam. `t5encoder` is in upstream's `TXT_ARCH_LIST`, so the `elif` below the guard passes
    and control reaches the ordinary loading loop with `compat` unset -- which is what we want:
    `compat` only drives an SDXL-specific shape fix that must not run here.
    """
    original = _loader().get_field

    def patched(reader, field_name, field_type):
        if field_name == "general.architecture":
            value = original(reader, field_name, field_type)
            return arch if value is None else value
        return original(reader, field_name, field_type)

    _loader().get_field = patched
    try:
        yield
    finally:
        _loader().get_field = original


def _dequantize_1d(sd: dict) -> int:
    """Dequantize every 1-D weight to float32. Returns how many were converted.

    Found by running a render, not by reading code. With the norms left quantized the graph
    dies in `comfy/text_encoders/t5.py:15` with:

        RuntimeError: The size of tensor a (4352) must match the size of tensor b (4096)

    4352 is the giveaway: 4096 Q8_0 values occupy exactly 4352 bytes (128 blocks x 34 -- a
    2-byte scale plus 32 int8 each). torch was being handed the raw block bytes as if they
    were values.

    Two things combine to cause it, and neither is a bug upstream:

    - llama.cpp keeps normalisation weights in F32, so upstream's 1-D special case only needs
      to cover BF16. This stable-diffusion.cpp file quantises *everything* -- all 220 tensors
      are Q8_0, including 49 one-dimensional norms.
    - `GGMLOps` dequantizes inside `Linear`, `Embedding` and `LayerNorm` layers. T5 does not
      use any of them for its norms: `T5LayerNorm` is an RMSNorm holding a plain
      `nn.Parameter` and multiplying by it directly, so no custom op is in the path.

    2-D weights are deliberately left quantized -- that is the entire point of loading a 4.8 GB
    Q8_0 file instead of a 9.5 GB fp16 one, and those *do* go through GGMLOps. The 49 norms
    dequantize to about 800 KB.
    """
    converted = 0
    for key, value in list(sd.items()):
        if not _loader().is_quantized(value):
            continue
        if len([d for d in value.tensor_shape if d > 1]) <= 1:
            sd[key] = _loader().dequantize_tensor(value, dtype=torch.float32)
            converted += 1
    return converted


def sdcpp_clip_loader(path: str) -> dict:
    """A state dict from an arch-less T5 GGUF, with no key remapping. See the module docstring."""
    with _claim_arch():
        sd, _extra = _loader().gguf_sd_loader(path, is_text_model=True)
    converted = _dequantize_1d(sd)
    logging.info(f"symoneural_gguf: loaded sd.cpp text encoder from {path} "
                 f"({len(sd)} tensors, {converted} 1-D norms dequantized to fp32)")
    return sd


class _SDCPPMixin:
    """Overrides only the file-reading step; patcher construction stays upstream's."""

    def load_data(self, ckpt_paths):
        data = []
        for p in ckpt_paths:
            if p.endswith(".gguf") and _is_hf_t5(p):
                data.append(sdcpp_clip_loader(p))
            else:
                # Anything upstream already handles -- llama.cpp GGUFs, safetensors -- goes
                # through upstream unchanged. This node is a superset, not a fork.
                data.extend(super().load_data([p]))
        return data


@lru_cache(maxsize=None)
def _impl(upstream_name: str):
    """One instance of upstream's loader with our `load_data` mixed in, built on first use.

    The subclassing happens *here*, inside a function, and not at module scope. Deriving from
    `_upstream_nodes().DualCLIPLoaderGGUF` at import time would resolve ComfyUI-GGUF at import
    time, which is precisely the ordering assumption that broke -- see `_gguf_module`.
    """
    base = getattr(_upstream_nodes(), upstream_name)
    return type(f"_{upstream_name}SDCPP", (_SDCPPMixin, base), {})()


class DualCLIPLoaderSDCPP:
    """FLUX's two text encoders, where one of them is a stable-diffusion.cpp T5 GGUF.

    A thin facade: ComfyUI only needs `INPUT_TYPES`, `RETURN_TYPES` and `FUNCTION` on the
    registered class, and both are answered after every pack has loaded -- `INPUT_TYPES` when
    `/object_info` is built, `load_clip` when a graph runs. Nothing here touches ComfyUI-GGUF
    until then.
    """

    RETURN_TYPES = ("CLIP",)
    FUNCTION = "load_clip"
    CATEGORY = "symoneural"
    TITLE = "DualCLIPLoader (sd.cpp GGUF)"

    @classmethod
    def INPUT_TYPES(cls):
        return _upstream_nodes().DualCLIPLoaderGGUF.INPUT_TYPES()

    def load_clip(self, clip_name1, clip_name2, type):
        return _impl("DualCLIPLoaderGGUF").load_clip(clip_name1, clip_name2, type)


class CLIPLoaderSDCPP:
    """The single-encoder form of the same thing."""

    RETURN_TYPES = ("CLIP",)
    FUNCTION = "load_clip"
    CATEGORY = "symoneural"
    TITLE = "CLIPLoader (sd.cpp GGUF)"

    @classmethod
    def INPUT_TYPES(cls):
        return _upstream_nodes().CLIPLoaderGGUF.INPUT_TYPES()

    def load_clip(self, clip_name, type="stable_diffusion"):
        return _impl("CLIPLoaderGGUF").load_clip(clip_name, type)


NODE_CLASS_MAPPINGS = {
    "DualCLIPLoaderSDCPP": DualCLIPLoaderSDCPP,
    "CLIPLoaderSDCPP": CLIPLoaderSDCPP,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DualCLIPLoaderSDCPP": "DualCLIPLoader (sd.cpp GGUF)",
    "CLIPLoaderSDCPP": "CLIPLoader (sd.cpp GGUF)",
}
