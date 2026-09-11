"""SyMoNeuRaL Reinforce -- the model registry and the VRAM arithmetic behind the picker.

The owner's complaint was that the training surface *"doesn't even give a place to load the
model"*. This module is that place: it enumerates what is genuinely on this box, reads the
shape of each candidate out of the file itself, and derives -- rather than looks up -- what a
run would cost in VRAM.

## Two rules this file exists to enforce

**Scan, never hardcode.** A hardcoded model table goes stale the first time somebody drops a
directory into the cache. Every row below is produced by reading `config.json` (HF format) or
the GGUF key/value header (llama.cpp format) off disk. If the file is not there, the row is
not there.

**Derive, never look up.** `plan_fit()` computes the memory cost from the architecture
numbers just read, using the four-term model in §4.2 of `docs/specs/qlora-upgrade.md`. That
means a model nobody anticipated still gets an honest estimate, and it means the estimate
moves when the preset moves.

## Labelling, which is the product and not decoration

`.claude/CLAUDE.md`: *"Label every figure: measured on this machine, vendor specification, or
projected arithmetic. Never present a projection as a result."* Every figure this module
emits carries a `label` field, and the three values are used strictly:

* **measured** -- read off this box right now. File sizes, quantisation types, tensor counts,
  parameter counts derived from real tensor shapes, free VRAM from the driver.
* **vendor** -- a published figure from somebody else's paper or docs. Exactly one is used
  here: **4.127 bits/parameter** for 4-bit NF4 with double quantisation, from the QLoRA paper
  (Dettmers et al., arXiv:2305.14314 §3). It is not measured here and is not called measured.
* **projected** -- arithmetic. Every peak-VRAM number is projected until a run records a real
  `torch.cuda.max_memory_allocated()` for that exact (model x preset) pair, at which point
  `jobs.measured_peaks()` supplies the measured value for *that cell only*. Scaling one
  measurement across the other cells would be a projection wearing a measurement's label,
  which is the specific dishonesty the rule names.

## Trade-secret guard

This module enumerates **weights**. It never enumerates datasets, and in particular it never
looks inside `training/`. `training/corpus.jsonl` and `training/build_dataset.py` are trade
secret per `.claude/CLAUDE.md`, and a model picker that helpfully scanned the sibling
directory for `.jsonl` files would publish the recipe. Dataset admission is handled in
`datasets.py`, behind an explicit refusal, and nothing here calls it.

Stdlib only. This module is imported by the serving API, which runs on the system interpreter
by deliberate policy -- no torch, no transformers, no numpy. The GGUF reader below is a
few hundred bytes of `struct` rather than a dependency for exactly that reason.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field, asdict

HERE = pathlib.Path(__file__).resolve().parent
# `backend/api.py` is the marker, and it is WALKED for rather than counted to. The counted
# form (`HERE.parent.parent.parent`) has now been wrong a FOURTH time: moving this app to
# `backend/apps/studio/plugins/reinforce` added two levels and the count resolved to
# `backend/apps`, which exists, so the only thing that caught it was the assert below.
# A walk survives the next move; a count has to be found and fixed by hand every time.
ROOT = next((_p for _p in (HERE, *HERE.parents) if (_p / "backend" / "api.py").is_file()), HERE)
# This calculation has been wrong three times in this repo's history (the demo/ flatten, the
# tools/ move, and `train_lora.py`'s HF_HOME, which is still wrong today -- it resolves to
# /home/google/models/hf, a path that does not exist). It fails silently, because the wrong
# parent is usually a directory that does exist. So assert, the way tools/build_training.py
# does, and turn a silent misresolution into an import-time crash.
assert (ROOT / "backend" / "api.py").is_file(), f"repo root misresolved to {ROOT}"

MODELS_DIR = ROOT / "backend" / "models"
HF_HOME = MODELS_DIR / "hf"
HF_HUB = HF_HOME / "hub"
GGUF_DIR = MODELS_DIR / "llm"

GIB = 1024 ** 3

# ---------------------------------------------------------------- the one vendor constant
#
# NF4 + double quantisation stores 4 bits per weight plus ~0.127 bits/weight of quantisation
# constants (the absmax scales, themselves quantised). QLoRA paper §3, "Double Quantization".
# VENDOR figure. Not measured on this box and never to be presented as if it were.
NF4_BITS_PER_PARAM = 4.127

# Bytes of optimiser/adapter state per *trainable* parameter:
#   4  fp32 master weight (LoRA matrices are trained in fp32)
# + 4  fp32 gradient
# + 2  paged AdamW 8-bit state (two moments at one byte each)
# PROJECTED. It is the standard accounting, not a reading from this card.
TRAINABLE_BYTES_PER_PARAM = 4 + 4 + 2

# Bytes per *resident, non-quantised* parameter -- embeddings, lm_head, norms and biases.
#
# This is 4, not 2, and getting it wrong cost a 2.03 GiB underestimate that a real run caught.
# The model is loaded at bf16, so 2 looks right and the arithmetic reads correctly. But peft's
# `prepare_model_for_kbit_training()` -- which every 4-bit recipe calls, including this one --
# then casts every non-quantised parameter to fp32:
#
#     peft/utils/other.py:197-202     # cast all non INT8 parameters to fp32
#         if (param.dtype == torch.float16) or (param.dtype == torch.bfloat16):
#             param.data = param.data.to(torch.float32)
#
# On a 152k-vocabulary model that is 1.09B parameters going from 2 bytes to 4: **+2.03 GiB**.
# MEASURED consequence: the Smoke preset on the 7B was projected at 6.29 GiB and peaked at
# 8.39 GiB allocated. The gap is this constant, and the corrected arithmetic lands within ~1%
# of the measurement. Kept as a named constant with the citation attached, because "2 bytes for
# a bf16 parameter" is the obvious wrong answer and somebody will try to simplify it back.
#
# The lever that would recover the 2.03 GiB is `peft.utils.other.cast_mixed_precision_params`,
# which casts non-trainable parameters back to half precision. It is NOT used here and has not
# been tested on this box; changing the recipe on the strength of a docstring is how a run OOMs
# at step 0 in a new way.
RESIDENT_BYTES_PER_PARAM = 4

# The allocator reserves more than it allocates -- cached blocks and fragmentation.
# MEASURED on the one run that exists: 10,158,604,288 reserved against 9,009,202,688
# allocated, a factor of 1.128. Used at 1.25 rather than 1.128 deliberately: one reading is
# not a distribution, and under-projecting is the failure mode that OOMs a run, so the rounding
# goes toward caution. PROJECTED.
ALLOCATOR_RESERVE_FACTOR = 1.25

# CUDA context + cuBLAS/cuBLASLt workspaces, which sit outside torch's own counters entirely --
# neither `max_memory_allocated()` nor `max_memory_reserved()` can see them, so this term can
# only ever be projected. On this box `nvidia-smi` reports ~1,027 MiB in use with nothing of
# ours running. PROJECTED.
CONTEXT_OVERHEAD_BYTES = int(0.6 * GIB)

# The budget to plan against. `nvidia-smi` reports 16,303 MiB total on this card and ~14,7xx
# MiB free at idle; the Reinforce engine's own registry docstring settled on ~14.2 GiB free
# in practice. Budgeting against the 15.92 GiB nameplate is how a run OOMs at step 0.
PRACTICAL_BUDGET_BYTES = int(14.2 * GIB)

# How much headroom a projection has to leave before this surface will call it a fit.
#
# `headroom > 0` is the wrong test and it is worth being explicit about why. The projection
# has known unmodelled terms -- cuBLAS workspace growth, allocator fragmentation, the
# dataloader, the tokeniser, and an activation estimate that is arithmetic rather than a
# reading. Its own error bar is comfortably wider than a gibibyte. So a run projected to fit
# by 0.9 GiB is not a run that fits; it is a run whose OOM is inside the noise.
#
# PROJECTED policy, not a measurement. Once real peaks exist for a cell these thresholds
# should be revisited against them -- and the measured value should replace the projection
# for that cell rather than adjusting the threshold to make the projection look better.
REFUSE_BELOW_BYTES = int(1.0 * GIB)     # below this, the answer is "this box cannot"
TIGHT_BELOW_BYTES = int(2.0 * GIB)      # below this, it may run, and it may not


# ---------------------------------------------------------------- GGUF header reader
#
# Enough of the GGUF spec to answer "what shape is this model and how is it quantised",
# without pulling in the `gguf` package (which lives in the training venv, not the serving
# interpreter). Arrays are skipped by seeking rather than materialised -- the tokeniser
# vocabulary is 152k strings and reading it to learn nothing would be silly.

_GGUF_MAGIC = b"GGUF"

# value type -> (struct format, byte width). None means variable-width, handled by hand.
_SCALAR = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2),
    4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1),
    10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8),
}
_STRING = 8
_ARRAY = 9

# ggml tensor types we can actually meet in these files. The name is what gets reported as
# the quantisation, and it is MEASURED -- it is read out of the tensor table, not guessed
# from the filename. (A file called `...Q4_K_M.gguf` that is secretly Q8_0 would be caught.)
_GGML_TYPE_NAMES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1", 8: "Q8_0", 9: "Q8_1",
    10: "Q2_K", 11: "Q3_K", 12: "Q4_K", 13: "Q5_K", 14: "Q6_K", 15: "Q8_K",
    16: "IQ2_XXS", 17: "IQ2_XS", 18: "IQ3_XXS", 19: "IQ1_S", 20: "IQ4_NL",
    21: "IQ3_S", 22: "IQ2_S", 23: "IQ4_XS", 24: "I8", 25: "I16", 26: "I32",
    27: "I64", 28: "F64", 29: "IQ1_M", 30: "BF16",
}

# `general.file_type`, the llama.cpp quantisation *recipe* name. Q4_K_M mixes Q4_K and Q6_K
# tensors, so the recipe is the honest label for the file as a whole and the per-tensor
# histogram is the evidence for it.
_FILE_TYPE_NAMES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1",
    10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M",
    16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS",
    32: "BF16",
}


class GGUFError(Exception):
    """The file is not a GGUF we can read. Never carries file *contents* in its message."""


def _read(fh, fmt: str, size: int):
    raw = fh.read(size)
    if len(raw) != size:
        raise GGUFError("truncated header")
    return struct.unpack(fmt, raw)[0]


def _read_str(fh) -> str:
    n = _read(fh, "<Q", 8)
    if n > 1 << 20:
        raise GGUFError("implausible string length in header")
    return fh.read(n).decode("utf-8", "replace")


def _skip_value(fh, vtype: int) -> None:
    if vtype in _SCALAR:
        fh.seek(_SCALAR[vtype][1], os.SEEK_CUR)
    elif vtype == _STRING:
        fh.seek(_read(fh, "<Q", 8), os.SEEK_CUR)
    elif vtype == _ARRAY:
        etype = _read(fh, "<I", 4)
        count = _read(fh, "<Q", 8)
        if etype in _SCALAR:
            fh.seek(_SCALAR[etype][1] * count, os.SEEK_CUR)   # one seek, not 152k reads
        elif etype == _STRING:
            for _ in range(count):
                fh.seek(_read(fh, "<Q", 8), os.SEEK_CUR)
        else:
            raise GGUFError(f"unsupported array element type {etype}")
    else:
        raise GGUFError(f"unsupported value type {vtype}")


def _read_value(fh, vtype: int):
    if vtype in _SCALAR:
        fmt, size = _SCALAR[vtype]
        return _read(fh, fmt, size)
    if vtype == _STRING:
        return _read_str(fh)
    _skip_value(fh, vtype)
    return None      # arrays are never a value we want; we only ever want their absence


def read_gguf_header(path: pathlib.Path) -> dict:
    """Architecture + quantisation, read off the file. Every field here is MEASURED.

    Returns keys: `arch`, `kv` (scalar/string metadata only), `file_type`, `tensor_types`
    (a histogram), `tensor_count`, and `tensors` (name -> dims) for the handful of tensors
    whose *presence* answers a real question -- `output.weight` tells us whether the
    embedding is tied, which changes the resident-bf16 term by a gibibyte on a 14B.
    """
    with path.open("rb") as fh:
        if fh.read(4) != _GGUF_MAGIC:
            raise GGUFError("not a GGUF file")
        version = _read(fh, "<I", 4)
        if version not in (2, 3):
            raise GGUFError(f"unsupported GGUF version {version}")
        tensor_count = _read(fh, "<Q", 8)
        kv_count = _read(fh, "<Q", 8)

        kv: dict[str, object] = {}
        for _ in range(kv_count):
            key = _read_str(fh)
            vtype = _read(fh, "<I", 4)
            val = _read_value(fh, vtype)
            if val is not None:
                kv[key] = val

        tensors: dict[str, list[int]] = {}
        types: dict[str, int] = {}
        for _ in range(tensor_count):
            name = _read_str(fh)
            ndims = _read(fh, "<I", 4)
            dims = [_read(fh, "<Q", 8) for _ in range(ndims)]
            ttype = _read(fh, "<I", 4)
            _read(fh, "<Q", 8)                       # offset, unused
            tname = _GGML_TYPE_NAMES.get(ttype, f"type{ttype}")
            types[tname] = types.get(tname, 0) + 1
            # Only the tensors whose shape or presence we actually reason about. Keeping the
            # whole table would be ~600 entries of noise in an API response.
            if name in ("token_embd.weight", "output.weight"):
                tensors[name] = dims

    arch = str(kv.get("general.architecture", "unknown"))
    ft = kv.get("general.file_type")
    return {
        "arch": arch,
        "kv": kv,
        "file_type": _FILE_TYPE_NAMES.get(ft, f"file_type{ft}") if ft is not None else None,
        "tensor_types": dict(sorted(types.items(), key=lambda kv_: -kv_[1])),
        "tensor_count": tensor_count,
        "tensors": tensors,
    }


# ---------------------------------------------------------------- the architecture record


@dataclass(frozen=True)
class Arch:
    """The seven numbers the VRAM arithmetic needs, however the model was described.

    Populated from an HF `config.json` or from GGUF KV metadata. Both paths land on the same
    record so `plan_fit()` never has to know which kind of file it came from.
    """
    layers: int
    hidden: int
    ffn: int
    heads: int
    kv_heads: int
    vocab: int
    tied_embeddings: bool

    @property
    def head_dim(self) -> int:
        return self.hidden // self.heads if self.heads else 0

    @property
    def kv_width(self) -> int:
        return self.head_dim * self.kv_heads

    @property
    def linear_params(self) -> int:
        """Parameters that bitsandbytes will actually quantise to 4 bits.

        Per decoder layer: q and o are hidden x hidden; k and v are hidden x kv_width
        (grouped-query attention, so they are much smaller than q); gate, up and down are
        each hidden x ffn. That is the seven `nn.Linear` leaves a Qwen2 decoder layer
        contains -- verified in the spec by instantiating the model on the meta device --
        which is also exactly the target-module list every preset uses.
        """
        per_layer = (2 * self.hidden * self.hidden          # q_proj, o_proj
                     + 2 * self.hidden * self.kv_width      # k_proj, v_proj
                     + 3 * self.hidden * self.ffn)          # gate_proj, up_proj, down_proj
        return per_layer * self.layers

    @property
    def resident_bf16_params(self) -> int:
        """Parameters that stay at bf16 no matter what `load_in_4bit` is set to.

        `nn.Embedding` is not a `Linear4bit`, and bitsandbytes skips `lm_head` by default.
        With a 152k vocabulary that is over a billion parameters and two gibibytes -- the
        term a naive `params * 0.5 bytes` estimate silently throws away, and the single most
        common reason a 'this fits' estimate OOMs.
        """
        embeddings = self.vocab * self.hidden * (1 if self.tied_embeddings else 2)
        # RMSNorm weights (two per layer plus a final) and the q/k/v biases Qwen2 carries.
        norms_and_biases = (2 * self.layers + 1) * self.hidden + self.layers * (
            self.hidden + 2 * self.kv_width)
        return embeddings + norms_and_biases

    @property
    def total_params(self) -> int:
        return self.linear_params + self.resident_bf16_params

    def lora_params(self, rank: int, modules: tuple[str, ...]) -> int:
        """Trainable parameters for a given rank over a given module set.

        A LoRA pair on a d_in x d_out projection is rank*(d_in + d_out) parameters. Summed
        per layer over whichever of the seven projections the preset targets, which is why
        a q,v-only preset is genuinely cheaper and not just nominally so.
        """
        widths = {
            "q_proj": (self.hidden, self.hidden),
            "k_proj": (self.hidden, self.kv_width),
            "v_proj": (self.hidden, self.kv_width),
            "o_proj": (self.hidden, self.hidden),
            "gate_proj": (self.hidden, self.ffn),
            "up_proj": (self.hidden, self.ffn),
            "down_proj": (self.ffn, self.hidden),
        }
        per_layer = sum(rank * (widths[m][0] + widths[m][1]) for m in modules if m in widths)
        return per_layer * self.layers


def arch_from_hf_config(cfg: dict) -> Arch:
    """Build an `Arch` from an HF `config.json`. Raises KeyError if it is not a causal LM
    config -- the TAO rejection-criteria pattern: qualify before offering, do not offer and
    then fail at load."""
    heads = int(cfg["num_attention_heads"])
    return Arch(
        layers=int(cfg["num_hidden_layers"]),
        hidden=int(cfg["hidden_size"]),
        ffn=int(cfg["intermediate_size"]),
        heads=heads,
        kv_heads=int(cfg.get("num_key_value_heads", heads)),
        vocab=int(cfg["vocab_size"]),
        tied_embeddings=bool(cfg.get("tie_word_embeddings", False)),
    )


def arch_from_gguf(header: dict) -> Arch:
    """Build an `Arch` from GGUF KV metadata.

    Two things are not in the KV block and are read off the tensor table instead:
    the vocabulary size (from `token_embd.weight`'s shape, rather than by materialising a
    152k-entry token array) and whether the embedding is tied (`output.weight` present means
    untied). The 0.5B here carries no `output.weight` and is tied; the 14B carries one and
    is not -- which is worth ~0.9 GiB on the 14B's resident-bf16 term.
    """
    arch = header["arch"]
    kv = header["kv"]

    def g(key: str) -> int:
        full = f"{arch}.{key}"
        if full not in kv:
            raise GGUFError(f"GGUF metadata has no {full}")
        return int(kv[full])

    heads = g("attention.head_count")
    embd = header["tensors"].get("token_embd.weight")
    if embd and len(embd) == 2:
        vocab = int(embd[1])            # GGUF dims are [hidden, vocab]
    elif f"{arch}.vocab_size" in kv:
        vocab = int(kv[f"{arch}.vocab_size"])
    else:
        raise GGUFError("cannot determine vocabulary size")
    return Arch(
        layers=g("block_count"),
        hidden=g("embedding_length"),
        ffn=g("feed_forward_length"),
        heads=heads,
        kv_heads=int(kv.get(f"{arch}.attention.head_count_kv", heads)),
        vocab=vocab,
        tied_embeddings="output.weight" not in header["tensors"],
    )


# ---------------------------------------------------------------- the catalogue entry


@dataclass
class Entry:
    """One row in the picker.

    `trainable` is the field the whole surface turns on, and `reason` says *why* when it is
    false. "Unsupported" on its own is what makes an operator file a bug report; "GGUF has no
    torch state dict, so peft has no modules to attach to" is what makes them pick the other
    row.
    """
    id: str
    label: str
    kind: str                    # "hf" | "gguf"
    path: str                    # display path, relative to the repo root -- never absolute
    present: bool
    trainable: bool
    reason: str = ""
    bytes_on_disk: int = 0
    quantisation: str = ""
    quant_label: str = ""        # measured / vendor / projected, for the quantisation figure
    tensor_types: dict = field(default_factory=dict)
    arch: dict | None = None
    arch_label: str = ""
    params: dict | None = None
    fetch_bytes: int = 0         # projected download size when `present` is false
    #: What this artefact was converted from, read out of backend/models/PROVENANCE.json.
    upstream: str = ""
    #: The OTHER row in this same catalogue that is the same model at a different stage.
    #: This field exists because of a specific misreading. The catalogue printed, adjacently:
    #:     symon-1.0-14b-q4_k_m       present=True   trainable=False
    #:     Qwen/Qwen2.5-14B-Instruct  present=False  trainable=False
    #: Two rows about ONE model with nothing connecting them, which a commissioning pass read
    #: on 2026-09-09 as "this box has no trainable weights at all" and escalated to a finding
    #: against the project's standing objective. Both rows were telling the truth. What
    #: neither could say was that they are the same model, house-named and upstream.
    same_model_as: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


#: backend/models/PROVENANCE.json is the only place recording which upstream artefact each
#: house name came from. It is authoritative and already existed; nothing here writes it.
PROVENANCE = MODELS_DIR / "PROVENANCE.json"


def _provenance_rows() -> list[dict]:
    """The provenance manifest, or an empty list. Never raises -- a missing or malformed
    manifest degrades the catalogue's labelling, it must not break the picker."""
    try:
        return json.loads(PROVENANCE.read_text()).get("weights", [])
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return []


def _base_model_name(repo: str) -> str:
    """`bartowski/Qwen2.5-14B-Instruct-GGUF` -> `Qwen2.5-14B-Instruct`.

    Strips the repackager org and the container marker, leaving the upstream model name --
    which is what the HF cache directory is keyed on (`models--Qwen--Qwen2.5-14B-Instruct`).
    Verified against all eleven manifest rows, including the lowercase
    `leejet/FLUX.1-schnell-gguf`.
    """
    name = repo.split("/", 1)[1] if "/" in repo else repo
    return re.sub(r"-GGUF$", "", name, flags=re.IGNORECASE)


def _provenance_index() -> tuple[dict[str, str], dict[str, list[str]]]:
    """(gguf stem -> "repo :: file", base upstream model name -> [house stems]).

    The second half is what connects an upstream row to the house-named row it became.
    """
    by_stem: dict[str, str] = {}
    by_base: dict[str, list[str]] = {}
    for row in _provenance_rows():
        path, repo = row.get("path") or "", row.get("upstream_repo") or ""
        if not path or not repo:
            continue
        stem = pathlib.PurePosixPath(path).stem
        upstream_file = row.get("upstream_file") or ""
        by_stem[stem] = f"{repo} :: {upstream_file}" if upstream_file else repo
        by_base.setdefault(_base_model_name(repo), []).append(stem)
    return by_stem, by_base


def cache_state(repo_id: str, hub: pathlib.Path | None = None) -> str:
    """Why an HF model is not here: "offloaded", "partial", or "absent".

    These are completely different situations and the catalogue used to print none of them.

    `huggingface_hub` stores every file in a snapshot as a symlink into `blobs/`. Remove the
    blobs -- which the model-storage policy does, because upstream originals and conversion
    inputs belong on Drive `Models/` -- and the snapshot keeps its FILENAMES and loses its
    contents. So an offloaded cache looks like a full directory listing over dead links, and
    `du` reports kilobytes.

    That is the intended steady state, not damage. A commissioning pass on 2026-09-09 read it
    as lost training weights and published it as a finding against the project's standing
    objective, because nothing anywhere distinguished it from "never fetched".

      offloaded -- a snapshot exists and its files are dangling symlinks: the blobs are on
                   Drive. Fetch them back to train; serving does not need them.
      partial   -- a snapshot exists with real files but no usable config: damaged, re-fetch.
      absent    -- no cache directory at all: never fetched here.
    """
    root = HF_HUB if hub is None else hub
    repo_dir = root / ("models--" + repo_id.replace("/", "--"))
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return "absent"
    for snap in sorted(snapshots.iterdir()):
        if not snap.is_dir():
            continue
        names = sorted(snap.iterdir())
        if not names:
            continue
        if any(f.is_symlink() and not f.exists() for f in names):
            return "offloaded"
        return "partial"
    return "absent"


def _rel(p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return p.name


def _params_block(a: Arch) -> dict:
    """The parameter split, with each number labelled at the point it is produced."""
    return {
        "total": a.total_params,
        "quantised_4bit": a.linear_params,
        "resident_bf16": a.resident_bf16_params,
        "label": "measured",
        "note": ("derived from the architecture metadata read off this file; the 7B lands on "
                 "its safetensors index total_size byte-for-byte"),
    }


def scan_hf_cache(hub: pathlib.Path = HF_HUB) -> list[Entry]:
    """Enumerate HF-format models in the local cache.

    The sd-webui `list_models()` pattern (§3.4 of the spec): one directory scan, refreshed on
    demand, no hardcoded list. A snapshot qualifies only if it has a `config.json` we can
    parse into an `Arch` and at least one `.safetensors` shard -- a `.no_exist` marker
    directory in the same cache carries a `config.json`-shaped absence and must not be
    offered.
    """
    out: list[Entry] = []
    if not hub.is_dir():
        return out
    for repo_dir in sorted(hub.glob("models--*")):
        snapshots = repo_dir / "snapshots"
        if not snapshots.is_dir():
            continue
        for snap in sorted(snapshots.iterdir()):
            cfg_path = snap / "config.json"
            repo_id = repo_dir.name.removeprefix("models--").replace("--", "/", 1).replace("--", "/")
            if not cfg_path.is_file():
                continue
            try:
                cfg = json.loads(cfg_path.read_text())
                a = arch_from_hf_config(cfg)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                out.append(Entry(
                    id=repo_id, label=repo_id, kind="hf", path=_rel(snap), present=True,
                    trainable=False,
                    reason=(f"config.json is not a causal-LM config this surface can qualify "
                            f"({type(exc).__name__}); rejected before load rather than after"),
                ))
                continue
            shards = sorted(snap.glob("*.safetensors"))
            if not shards:
                out.append(Entry(
                    id=repo_id, label=repo_id, kind="hf", path=_rel(snap), present=False,
                    trainable=False,
                    reason="config.json present but no safetensors shards -- metadata-only cache entry",
                ))
                continue
            # Resolve symlinks: the HF cache snapshots are links into blobs/, and the link
            # itself is 60-odd bytes. Reporting that as the model size would be a lie the
            # first operator to check `du` would catch.
            size = sum(s.resolve().stat().st_size for s in shards)
            out.append(Entry(
                id=repo_id, label=repo_id, kind="hf", path=_rel(snap), present=True,
                trainable=True,
                reason="", bytes_on_disk=size,
                quantisation=str(cfg.get("torch_dtype", "bfloat16")),
                quant_label="measured",
                tensor_types={f"{len(shards)} safetensors shards": len(shards)},
                arch=asdict(a), arch_label="measured", params=_params_block(a),
            ))
    return out


def scan_gguf(directory: pathlib.Path = GGUF_DIR) -> list[Entry]:
    """Enumerate GGUF weights, all of which are offered as *rejected* rows with the reason.

    They are listed rather than hidden on purpose. Three of the four largest model files on
    this box are GGUF; a picker that showed none of them would look broken, and an operator
    who has just watched the chat surface serve a GGUF is owed an explanation of why the
    training bay will not take one.
    """
    out: list[Entry] = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.gguf")):
        size = path.stat().st_size
        entry = Entry(
            id=path.stem, label=path.stem, kind="gguf", path=_rel(path), present=True,
            trainable=False,
            reason=("GGUF is a serving format, not a training format: it carries no torch "
                    "state dict and no module tree, so there is nothing for a low-rank "
                    "adapter to attach to. llama.cpp can serve an adapter; it cannot "
                    "produce one."),
            bytes_on_disk=size,
        )
        # The house name alone hides what this is. `symon-1.0-14b-q4_k_m` and
        # `Qwen/Qwen2.5-14B-Instruct` are one model at two stages, and an operator who cannot
        # see that reads the catalogue as two families with one missing.
        by_stem, by_base = _provenance_index()
        entry.upstream = by_stem.get(path.stem, "")
        if entry.upstream:
            base = _base_model_name(entry.upstream.split(" :: ", 1)[0])
            entry.same_model_as = base
            entry.reason += (f" Converted from {entry.upstream}; the upstream HF weights for "
                             f"{base} are the training target for this model.")
        try:
            header = read_gguf_header(path)
            entry.quantisation = header["file_type"] or "unknown"
            entry.quant_label = "measured"
            entry.tensor_types = header["tensor_types"]
            a = arch_from_gguf(header)
            entry.arch = asdict(a)
            entry.arch_label = "measured"
            entry.params = _params_block(a)
        except (GGUFError, OSError, struct.error) as exc:
            # Deliberately reports the exception *class*, not its message. Nothing in a GGUF
            # header is secret, but the habit is: an error path is the easiest place in a
            # training surface for file contents to escape into an API response.
            entry.reason += f" (header not readable: {type(exc).__name__})"
        out.append(entry)
    return out


def _fetchable_pairs() -> list[tuple[str, str]]:
    """(gguf filename, upstream HF repo id) for every local GGUF with recorded provenance.

    Only LLM rows qualify: the image and whisper artefacts have upstreams too, but they are
    not causal-LM training targets and offering them in this picker would be padding of
    exactly the kind `fetchable()`'s docstring warns against.

    The repo id is reconstructed as `<org>/<base>` from the upstream's base model name, using
    the same org the HF cache keys on. `bartowski/Qwen2.5-14B-Instruct-GGUF` is a repackager;
    the trainable original is `Qwen/Qwen2.5-14B-Instruct`.
    """
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for row in _provenance_rows():
        path = row.get("path") or ""
        repo = row.get("upstream_repo") or ""
        if not path.startswith("llm/") or not repo:
            continue
        base = _base_model_name(repo)
        # Qwen publishes the originals; the GGUF repackagers do not host safetensors.
        if not base.lower().startswith("qwen"):
            continue
        repo_id = f"Qwen/{base}"
        if repo_id in seen:
            continue
        seen.add(repo_id)
        pairs.append((pathlib.PurePosixPath(path).name, repo_id))
    return sorted(pairs, key=lambda t: t[1])


def fetchable() -> list[Entry]:
    """Models this box could train but does not have, with the download size stated up front.

    This exists because of a specific honesty problem: exactly one model on this box is
    fine-tunable, and *a dropdown with one item is a UI that lies about choice*. The honest
    fix is to offer the others and say what they cost, not to pad the list.

    The architecture rows here are **measured** -- they are read from the GGUF of the same
    model that is already on disk, which is the same architecture in a different container.
    The download sizes are **projected**: they are the safetensors totals published by the
    source repository, arithmetic on the parameter count, not a transfer this box has run.

    Fetching is NOT implemented. `jobs.start()` refuses a model with `present=False` rather
    than kicking off a 27.5 GiB download from an HTTP handler. See the module note in
    routes.py.
    """
    out: list[Entry] = []
    have = {e.id for e in scan_hf_cache() if e.trainable}
    # Derived from backend/models/PROVENANCE.json rather than hardcoded. The hardcoded pair
    # was ("0.5b", "14b") -- which silently excluded the 7B and the 27B, the two models whose
    # HF blobs are actually offloaded to Drive. So the picker could not show the offload state
    # for the only two models in it, and a reader who went looking found nothing at all.
    # The manifest already knew every house-name -> upstream mapping; this reads it.
    for gguf_name, repo_id in _fetchable_pairs():
        if repo_id in have:
            continue
        src = GGUF_DIR / gguf_name
        if not src.is_file():
            continue
        try:
            a = arch_from_gguf(read_gguf_header(src))
        except (GGUFError, OSError, struct.error):
            continue
        # WHY it is absent, which the previous single sentence could not say. "Never
        # fetched" and "offloaded to Drive by policy" want different actions, and reading the
        # second as the first is what produced a false finding on 2026-09-09.
        state = cache_state(repo_id)
        _, by_base = _provenance_index()
        house = by_base.get(_base_model_name(repo_id), [])
        whereabouts = {
            "offloaded": ("OFFLOADED, not missing: the HF cache holds this model's metadata "
                          "over symlinks whose blobs are on Drive `Models/`. That is the "
                          "model-storage policy working -- only house-named runnable "
                          "artefacts stay local. Fetch the base safetensors back from Drive "
                          "to train; serving never needs them and works with Drive down."),
            "partial": ("a damaged cache entry: files are present but there is no usable "
                        "config.json. Re-fetch it."),
            "absent": ("never fetched on this box: the training stack needs safetensors plus "
                       "a config.json."),
        }[state]
        also = (f" Already here as {', '.join(house)} in GGUF form for serving -- same model, "
                f"different stage." if house else "")
        out.append(Entry(
            id=repo_id, label=repo_id, kind="hf",
            path=f"backend/models/hf ({state})",
            present=False, trainable=False,
            same_model_as=", ".join(house),
            reason=(whereabouts + also + " Fetch-on-demand is not implemented -- this row "
                    "states the cost so the choice is informed, it is not a button."),
            quantisation="bfloat16 (once fetched)", quant_label="projected",
            arch=asdict(a),
            arch_label="measured (architecture read from the GGUF of the same model on disk)",
            params=_params_block(a),
            # bf16 safetensors: two bytes per parameter, plus a few per-shard headers.
            fetch_bytes=a.total_params * 2,
        ))
    return out


def catalogue() -> list[Entry]:
    """Everything the picker shows, trainable rows first.

    NOTE FOR ANYONE EXTENDING THIS: do not add a dataset scan here, and specifically never
    glob `training/*.jsonl`. `training/corpus.jsonl` and `training/build_dataset.py` are
    trade secret under `.claude/CLAUDE.md`; enumerating them into a dropdown publishes the
    product's recipe, and it is the single most likely accident on a surface like this one.
    Datasets are admitted by `datasets.py`, which refuses those two paths by name.
    """
    rows = scan_hf_cache() + fetchable() + scan_gguf()
    rows.sort(key=lambda e: (not e.trainable, not e.present, e.id))
    return rows


def find(model_id: str) -> Entry | None:
    """Resolve a model id to an entry, tolerating the short form.

    The fuzzy half of sd-webui's `get_closet_checkpoint_match`: a preset saved as
    `Qwen2.5-7B-Instruct` still resolves after somebody writes the full `Qwen/...` repo id,
    and vice versa. Exact match always wins, so a suffix collision cannot shadow a real id.
    """
    rows = catalogue()
    for e in rows:
        if e.id == model_id:
            return e
    lowered = model_id.lower()
    hits = [e for e in rows if e.id.lower().endswith("/" + lowered) or e.label.lower() == lowered]
    return hits[0] if len(hits) == 1 else None


# ---------------------------------------------------------------- the fit calculation


def free_vram_bytes() -> tuple[int | None, str]:
    """Free VRAM from the driver. MEASURED when it answers, `None` when it does not.

    Not called from `status()` -- that runs on every rack poll and must not fork a process.
    This is for preflight, where one `nvidia-smi` in exchange for not OOMing at step 0 is a
    trade worth making.
    """
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None, "nvidia-smi not on PATH"
    try:
        out = subprocess.run(
            [smi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True).stdout
        return int(out.strip().splitlines()[0].strip()) * 1024 * 1024, "measured"
    except (subprocess.SubprocessError, ValueError, IndexError) as exc:
        return None, f"nvidia-smi unreadable ({type(exc).__name__})"


def activation_bytes(a: Arch, seq_len: int, batch: int, checkpointing: bool = True) -> dict:
    """Activation memory, broken into the three terms that matter, all PROJECTED.

    The interesting result -- and the reason this is a function and not a constant -- is that
    on a 152k-vocabulary model the **logits dominate**. At sequence 1024 the checkpointed
    hidden states are ~205 MiB while the logit tensor and its fp32 upcast for cross-entropy
    are ~890 MiB together. That is why `max_length` moves the peak so much more than layer
    count does, and why Long-form (seq 2048) is the preset closest to the ceiling.
    """
    hidden_states = a.layers * seq_len * a.hidden * batch * 2 if checkpointing else 0
    # Without checkpointing every intermediate in every layer is kept; roughly an order of
    # magnitude more. Every preset here enables checkpointing, so this branch is the
    # arithmetic that justifies the rule rather than a configuration anyone can pick.
    if not checkpointing:
        hidden_states = a.layers * seq_len * batch * (a.hidden * 6 + a.ffn * 3) * 2
    recompute = seq_len * batch * (a.ffn * 3 + a.hidden * 4) * 2
    logits = seq_len * batch * a.vocab * (2 + 4)      # bf16 logits + fp32 upcast for the loss
    return {
        "hidden_states": hidden_states,
        "recompute_peak": recompute,
        "logits": logits,
        "total": hidden_states + recompute + logits,
        "label": "projected",
    }


def kv_cache_bytes(a: Arch, seq_len: int, batch: int) -> int:
    """KV cache for autoregressive generation, at bf16. PROJECTED.

    Only the reinforcement method pays this: it is the one method here that *samples*. Two
    tensors (K and V) per layer, each `kv_heads x head_dim` wide per token -- so grouped-query
    attention makes this far cheaper than the head count suggests. On the 7B, `kv_heads` is 4
    against 28 query heads, a 7x saving on precisely this term.
    """
    return 2 * a.layers * a.kv_width * seq_len * batch * 2


def method_terms(a: Arch, *, method: str, method_config: dict, seq_len: int,
                 checkpointing: bool = True) -> dict:
    """The VRAM terms the supervised cost model does not have. All PROJECTED.

    ## Why this exists as its own function

    `plan_fit` costed one shape of run: one sequence forward, one backward, one logit tensor.
    Both new methods break that assumption in ways that are large rather than marginal, and
    charging them at the supervised rate would publish an understatement wearing a `projected`
    label -- which is the specific dishonesty `.claude/CLAUDE.md` forbids, made worse by the
    fact that the arithmetic *looks* done.

    ## reinforcement (GRPO): the multiplier is `num_generations`

    A GRPO step samples `G` completions for each prompt, then trains on all `G`. So the
    training forward runs at an effective batch of `G`, and every activation term scales with
    it. Plus a generation KV cache, which the supervised path has no equivalent of at all.

    The one piece of good news, and it is checked against the installed library rather than
    assumed: **the logit tensor is charged over the completion window only, not the whole
    sequence.** `trl/trainer/grpo_trainer.py:2503` sets

        logits_to_keep = completion_ids.size(1)   # only the completion tokens

    and passes it into the forward, so the 152k-wide lm_head projection is computed for 256
    positions rather than 768. On this model that is the difference between ~0.87 GiB and
    ~2.61 GiB, so it is worth reading the source instead of guessing: guessing high here would
    refuse a configuration that fits.

    `seq_len` for a reinforcement preset is the **prompt** cap; the completion is
    `max_completion_length` on top of it. That differs from the supervised and preference
    methods, where `max_length` covers the whole sequence, and it differs because trl's
    `GRPOConfig` has **no `max_prompt_length` field in 1.10.0** -- a checked absence -- so the
    prompt bound is enforced by this package before the card is taken rather than by the
    trainer at step 0.

    ## preference (DPO): the multiplier is 2, and the reference may be free

    `trl/trainer/dpo_trainer.py:356-359` concatenates the chosen and rejected completions along
    the **batch** dimension, so one preference example is two sequences through the model. DPO
    does not use `logits_to_keep`, so its logit tensor is charged over the full sequence at
    batch 2.

    The reference policy costs **no weight bytes under peft** -- `ref_model=None` with a
    `peft_config` makes trl disable the adapter for the reference pass and re-enable it after,
    so the reference is the base model that is already resident. It costs a forward pass. And
    with `precompute_ref_log_probs=True` even that lands outside the peak: the reference passes
    all happen in a pre-pass, before the optimiser state exists, so the two never coincide.
    That is why the preference preset sets it, and it is charged here as zero *at peak* with
    the reason attached rather than silently omitted.
    """
    cfg = method_config or {}
    terms: dict[str, dict] = {}
    notes: list[str] = []

    if method == "reinforcement":
        g = max(1, int(cfg.get("num_generations", 1)))
        completion = int(cfg.get("max_completion_length", 256))
        total_len = seq_len + completion
        beta = float(cfg.get("beta", 0.0))

        kv = kv_cache_bytes(a, total_len, g)
        # The training forward at effective batch G. Hidden states and the recompute peak scale
        # with the full sequence; the logits scale with the completion window only.
        hidden = a.layers * total_len * a.hidden * g * 2 if checkpointing else 0
        recompute = total_len * g * (a.ffn * 3 + a.hidden * 4) * 2
        logits = completion * g * a.vocab * (2 + 4)

        terms["rollout_kv_cache"] = {
            "bytes": kv, "label": "projected",
            "basis": (f"2 (K,V) x {a.layers} layers x {a.kv_width} kv width x "
                      f"{total_len} tokens x {g} completions x 2 bytes. Grouped-query "
                      f"attention: {a.kv_heads} kv heads against {a.heads} query heads")}
        terms["rollout_group_activations"] = {
            "bytes": hidden + recompute + logits, "label": "projected",
            "basis": (f"the training forward runs at an effective batch of {g} -- every sampled "
                      f"completion takes a gradient. Checkpointed hidden states "
                      f"{hidden / GIB:.2f} GiB + one-layer recompute {recompute / GIB:.2f} GiB "
                      f"at seq {total_len} x {g}, plus logits {logits / GIB:.2f} GiB charged "
                      f"over the {completion}-token completion window only "
                      f"(logits_to_keep, grpo_trainer.py:2503)")}
        if beta > 0:
            # A no-grad forward: no stored hidden states, but the same transient recompute and
            # logit tensors. Charged, because at G completions it is not a rounding error.
            ref = recompute + logits
            terms["reference_forward"] = {
                "bytes": ref, "label": "projected",
                "basis": (f"beta={beta} keeps the KL penalty, which costs one extra forward pass "
                          f"over all {g} completions. No weight bytes -- the reference is this "
                          f"model with the adapter disabled -- but the transient activations are "
                          f"real. Set beta=0 to remove this term and the KL tether with it")}
        else:
            notes.append("beta=0: no reference forward pass, and no KL tether to lose it to. "
                         "That is a trade against reward hacking, not a free saving")
        notes.append(f"num_generations={g} is the multiplier on every term above and is the "
                     f"first rung on this method's OOM ladder")

    elif method == "preference":
        # Chosen and rejected, concatenated on the batch dimension.
        hidden = a.layers * seq_len * a.hidden * 2 * 2 if checkpointing else 0
        recompute = seq_len * 2 * (a.ffn * 3 + a.hidden * 4) * 2
        logits = seq_len * 2 * a.vocab * (2 + 4)
        # `activation_bytes` has already charged one sequence's worth in the base plan, so only
        # the second sequence is added here. Charging both would double-count.
        base = activation_bytes(a, seq_len, 1, checkpointing)["total"]
        extra = max(0, hidden + recompute + logits - base)
        terms["preference_pair_activations"] = {
            "bytes": extra, "label": "projected",
            "basis": (f"every preference example is scored twice -- chosen and rejected are "
                      f"concatenated along the batch dimension (dpo_trainer.py:356-359), so the "
                      f"activation and logit terms are charged at batch 2 rather than 1. Only "
                      f"the second sequence is added here; the first is already in the "
                      f"activations term above")}
        if cfg.get("precompute_ref_log_probs"):
            terms["reference_forward"] = {
                "bytes": 0, "label": "projected",
                "basis": ("zero AT PEAK, and that is the whole point of "
                          "precompute_ref_log_probs=True: the reference log-probabilities are "
                          "computed in a pass over the dataset before the optimiser and its "
                          "state exist, cached, and never recomputed. The reference forward and "
                          "the training peak never coincide. It costs wall-clock and host "
                          "memory, which is the right trade when VRAM is the binding constraint")}
            notes.append("reference log-probabilities are precomputed, so the reference forward "
                         "sits outside the training peak")
        else:
            ref = recompute + logits
            terms["reference_forward"] = {
                "bytes": ref, "label": "projected",
                "basis": ("one no-grad forward pass per step over both sequences. No weight "
                          "bytes -- under peft the reference is this model with the adapter "
                          "disabled -- but the transient activations coincide with the training "
                          "peak. precompute_ref_log_probs=True moves this term out of the peak")}
        notes.append("the reference policy costs no weight bytes: ref_model=None with a "
                     "peft_config disables the adapter for the reference pass instead of "
                     "loading a second copy of the model")

    return {"terms": terms,
            "bytes": sum(t["bytes"] for t in terms.values()),
            "notes": notes,
            "label": "projected"}


def plan_fit(a: Arch, *, rank: int, target_modules: tuple[str, ...], seq_len: int,
             batch: int, gradient_checkpointing: bool = True,
             free_bytes: int | None = None,
             method: str = "sft", method_config: dict | None = None) -> dict:
    """The four-term VRAM projection, itemised so a refusal can show its working.

    Reinforce's `plan_residency(free_bytes)` decides what fits *before* anything is loaded;
    this is the training-shaped version of that. A refusal returns the sum, because "won't
    fit" with no arithmetic is indistinguishable from a bug, and because the OOM ladder can
    only name a rung if it knows which term is the large one.

    Every figure here is **projected** except `free_bytes`, which is measured, and the
    4.127 bits/param NF4 constant, which is vendor.
    """
    weights_4bit = int(a.linear_params * NF4_BITS_PER_PARAM / 8)
    weights_resident = a.resident_bf16_params * RESIDENT_BYTES_PER_PARAM
    lora_n = a.lora_params(rank, target_modules)
    trainable = lora_n * TRAINABLE_BYTES_PER_PARAM
    acts = activation_bytes(a, seq_len, batch, gradient_checkpointing)
    # Whatever the objective costs beyond one forward and one backward: the sampling loop and
    # its group multiplier for reinforcement, the second sequence and the reference pass for
    # preference. Empty for `sft`, which is why every existing figure is unchanged.
    extra = method_terms(a, method=method, method_config=method_config or {},
                         seq_len=seq_len, checkpointing=gradient_checkpointing)

    # Two figures, because they answer two different questions and conflating them is what
    # produced the first bad estimate. `content` is what torch will report as allocated -- it
    # is comparable against `max_memory_allocated()` and is the number the arithmetic can be
    # checked against. `total` is what the process takes off the card, which is what decides
    # whether it fits: allocator reservation on top of content, plus a CUDA context that
    # torch's counters cannot see at all.
    content = weights_4bit + weights_resident + trainable + acts["total"] + extra["bytes"]
    total = int(content * ALLOCATOR_RESERVE_FACTOR) + CONTEXT_OVERHEAD_BYTES

    budget = free_bytes if free_bytes is not None else PRACTICAL_BUDGET_BYTES
    headroom = budget - total
    trainable_pct = 100.0 * lora_n / a.total_params if a.total_params else 0.0

    if headroom < REFUSE_BELOW_BYTES:
        verdict = "refused"
    elif headroom < TIGHT_BELOW_BYTES:
        verdict = "tight"
    else:
        verdict = "fits"

    # The OOM ladder, from TAO's error playbook, minus the rungs this box has already spent.
    # Batch is 1 in every preset and gradient checkpointing is always on, so "halve the batch"
    # and "enable checkpointing" are not available here. Saying which rung is being offered,
    # in these words, is the difference between a refusal and a shrug.
    ladder: list[str] = []
    if verdict != "fits":
        # The method-specific rungs come FIRST, because on an RL run they are the cheap ones.
        # `num_generations` multiplies every activation term, so halving it saves more than
        # halving the sequence does -- and unlike rank it costs nothing in adapter capacity.
        # Offering "lower the rank" first on a GRPO run would be pointing at the smallest term
        # on the panel.
        if method == "reinforcement":
            cfg = method_config or {}
            g = int(cfg.get("num_generations", 1))
            comp = int(cfg.get("max_completion_length", 256))
            if g > 2:
                ladder.append(f"lower num_generations from {g} to {g // 2} (saves roughly half "
                              f"of {extra['bytes'] / GIB:.2f} GiB of rollout terms, projected -- "
                              f"the cheapest rung on this method, though a smaller group is a "
                              f"noisier advantage estimate)")
            if comp > 64:
                ladder.append(f"shorten max_completion_length from {comp} to {comp // 2} "
                              f"(the logit term is charged over the completion window, so this "
                              f"halves it, projected)")
            if float(cfg.get("beta", 0.0)) > 0:
                ladder.append("set beta=0 to drop the reference forward pass -- but that removes "
                              "the KL tether, which is what holds a reward-hacking policy back")
        if method == "preference" and not (method_config or {}).get("precompute_ref_log_probs"):
            ladder.append("set precompute_ref_log_probs=True to move the reference forward out "
                          "of the training peak (costs wall-clock and host memory instead)")
        if seq_len > 512:
            ladder.append(f"shorten max_length from {seq_len} to {seq_len // 2} "
                          f"(saves ~{(acts['logits'] + acts['hidden_states']) // 2 / GIB:.2f} GiB, projected)")
        if rank > 8:
            ladder.append(f"lower rank from {rank} to {rank // 2} "
                          f"(saves ~{trainable // 2 / GIB:.2f} GiB, projected)")
        ladder.append("choose a smaller base model -- the weights term is the large one and "
                      "rank does not touch it")

    return {
        "terms": {
            "weights_4bit": {"bytes": weights_4bit, "label": "projected",
                             "basis": f"{a.linear_params:,} params x {NF4_BITS_PER_PARAM} bits "
                                      f"(NF4 + double quant, vendor: QLoRA arXiv:2305.14314 §3)"},
            "weights_resident_fp32": {"bytes": weights_resident, "label": "projected",
                                      "basis": f"{a.resident_bf16_params:,} params x "
                                               f"{RESIDENT_BYTES_PER_PARAM} bytes -- embeddings, "
                                               f"lm_head, norms and biases are not quantised, and "
                                               f"peft upcasts them from bf16 to fp32 before "
                                               f"training (peft/utils/other.py:197-202). Assuming "
                                               f"2 bytes here understated a real run by 2.03 GiB"},
            "adapter_and_optimiser": {"bytes": trainable, "label": "projected",
                                      "basis": f"{lora_n:,} trainable x "
                                               f"{TRAINABLE_BYTES_PER_PARAM} bytes "
                                               f"(fp32 weight + fp32 grad + 8-bit AdamW)"},
            "activations": {"bytes": acts["total"], "label": "projected",
                            "basis": f"checkpointed hidden states {acts['hidden_states'] / GIB:.2f} GiB "
                                     f"+ one-layer recompute {acts['recompute_peak'] / GIB:.2f} GiB "
                                     f"+ logits {acts['logits'] / GIB:.2f} GiB "
                                     f"at seq {seq_len} x batch {batch}"},
            **extra["terms"],
            "allocator_reserve": {"bytes": int(content * (ALLOCATOR_RESERVE_FACTOR - 1)),
                                  "label": "projected",
                                  "basis": f"x{ALLOCATOR_RESERVE_FACTOR} on the content above. The "
                                           f"one run measured here reserved 1.128x what it "
                                           f"allocated; rounded up because one reading is not a "
                                           f"distribution and under-projecting is what OOMs"},
            "cuda_context": {"bytes": CONTEXT_OVERHEAD_BYTES, "label": "projected",
                             "basis": "CUDA context and cuBLAS workspace, which sit outside "
                                      "torch's own memory counters entirely"},
        },
        "projected_allocated_bytes": content,
        "projected_allocated_gib": round(content / GIB, 2),
        "projected_allocated_note": ("comparable against torch.cuda.max_memory_allocated(); this "
                                     "is the figure the arithmetic can be checked against"),
        "projected_peak_bytes": total,
        "projected_peak_gib": round(total / GIB, 2),
        "budget_bytes": budget,
        "budget_gib": round(budget / GIB, 2),
        "budget_label": "measured" if free_bytes is not None else "projected",
        "budget_basis": ("free VRAM read from the driver just now"
                         if free_bytes is not None else
                         "~14.2 GiB practical budget; the 15.92 GiB nameplate is not free"),
        "headroom_bytes": headroom,
        "headroom_gib": round(headroom / GIB, 2),
        "verdict": verdict,
        "verdict_why": {
            "fits": f"projected to leave at least {TIGHT_BELOW_BYTES / GIB:.1f} GiB spare",
            "tight": (f"projected headroom is under {TIGHT_BELOW_BYTES / GIB:.1f} GiB, which is "
                      f"inside the error bar on the projection itself. It may complete; treat an "
                      f"OOM as expected rather than as a fault"),
            "refused": (f"projected headroom is under {REFUSE_BELOW_BYTES / GIB:.1f} GiB. This is "
                        f"a capability this box does not have for this configuration -- not a "
                        f"fault, and not something a retry fixes"),
        }[verdict],
        "fits": verdict != "refused",
        "trainable_params": lora_n,
        "trainable_pct": round(trainable_pct, 3),
        # TAO's error playbook: an adapter outside 0.1-1% of the base usually means the target
        # regex is too broad. Worth surfacing, not worth refusing over -- r=32 on a 7B lands
        # at ~1.06%, which is deliberate for the Recall preset and not a mistake.
        "trainable_pct_note": ("inside the 0.1-1% band a low-rank adapter is expected to occupy"
                               if 0.1 <= trainable_pct <= 1.0 else
                               "outside the usual 0.1-1% band -- expected at high rank, but check "
                               "the target module list if you did not intend it"),
        "ladder": ladder,
        "method": method,
        "method_bytes": extra["bytes"],
        "method_notes": extra["notes"],
        "label": "projected",
        "note": ("arithmetic, not a measurement. A cell becomes measured only when a run of "
                 "that exact model and preset records torch.cuda.max_memory_allocated()."),
        "accuracy": ACCURACY,
        # Stated separately from `accuracy`, because `accuracy` describes how the SUPERVISED
        # arithmetic did against a real run and would otherwise be read as covering these terms
        # too. It does not. Nothing on either new method has ever run on this box.
        "method_accuracy": (
            "the one measurement behind this arithmetic is a supervised run. The preference and "
            "reinforcement terms above have NEVER been checked against a real peak on this box -- "
            "they are arithmetic from the trl source, with the source lines cited, and their error "
            "bar is wider than the supervised model's. Treat a `tight` verdict on either as "
            "'expect an OOM' rather than 'probably fine'."
            if method in ("preference", "reinforcement") else
            "this is the supervised cost model, the one with a measurement behind it -- see "
            "`accuracy`."),
    }


# How well this arithmetic has actually done, stated rather than implied.
#
# There is exactly ONE measurement behind it: the Smoke preset on the 7B, eight steps, which
# reported 9,009,202,688 bytes allocated and 10,158,604,288 reserved. Publishing a projection
# without publishing how far off it was the one time it could be checked would be the same
# class of dishonesty as an unlabelled figure.
#
# The content term still runs ~7% UNDER the measurement. The unmodelled remainder is transient
# copies during the fp32 cast, the paged optimiser's own state, and the evaluation forward
# pass. It is NOT tuned away with a fudge constant, because a constant fitted to one data point
# is a projection that has stopped being arithmetic. What protects a run instead is that the
# figure the fit decision uses -- `projected_peak_bytes` -- sits above the measured reservation
# by design, and a regression test asserts that it does.
ACCURACY = {
    "runs_measured": 1,
    "cell": "Qwen/Qwen2.5-7B-Instruct | smoke | 8 steps",
    "measured_allocated_bytes": 9_009_202_688,
    "measured_reserved_bytes": 10_158_604_288,
    "content_term_error": "projection ran about 7% under the measured allocation",
    "direction": ("the fit decision uses the peak figure, which projects ABOVE the measured "
                  "reservation -- deliberately, because under-projecting is the failure that "
                  "OOMs a run at step 0 and over-projecting only refuses one that might have fit"),
    "first_correction": ("the first version of this arithmetic charged 2 bytes for each resident "
                         "parameter and was 2.03 GiB under. peft upcasts them to fp32; the run "
                         "found it, the constant was corrected, and the comment carries the "
                         "citation so it does not get simplified back"),
    "label": "measured",
}
