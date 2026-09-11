#!/usr/bin/env bash
#
# fork_engines.sh -- build SyMoNeuRaL's inference engines into engines/, from source,
# under our own names.
#
# WHY THIS SCRIPT EXISTS. The two engines behind the chat and image surfaces were being
# run straight out of external/, which is a reference-only tree: nothing in it may be
# imported, built or linked by the shipped product, and nothing ships under a third-party
# name. api.py pointed at external/contrib/.../llama-server and .../sd-cli, so both
# rules were broken at once and, once external/ moved, chat and image went offline.
#
# This script takes the vendored upstream source as INPUT -- the way you would treat a
# release tarball -- and produces our engine as OUTPUT under engines/. After it runs, the
# running product has no path into external/ at all: the binaries live in engines/, and
# their RUNPATH is $ORIGIN, so every library they load is one we built and named.
#
# HOW THE RENAMING WORKS, and why it is not a sed sweep over 874 MB of C++. CMake's
# OUTPUT_NAME changes the file written to disk and nothing else -- every
# target_link_libraries() reference in the tree is by CMake *target* name, which we leave
# alone. So the build graph is untouched (zero risk of a broken link line) while the
# artifacts that actually ship carry our names. This is only safe because
# GGML_BACKEND_DL is OFF in this configuration: backends are linked directly, so nothing
# discovers a library by globbing a filename pattern. Verified before writing this:
#   grep GGML_BACKEND_DL build/CMakeCache.txt  ->  OFF
#   readelf -d build/bin/llama-server          ->  RUNPATH [$ORIGIN]
# If you ever turn GGML_BACKEND_DL on, renaming libggml-*.so by OUTPUT_NAME will make the
# CUDA backend undiscoverable at runtime and the card will silently not be used.
#
# CUDA and NVIDIA names are deliberately NOT renamed -- that is the one standing
# exemption. "cuda" stays a word in these filenames because it names the vendor's
# toolkit, not somebody else's product identity.
#
# Idempotent: re-running re-syncs the source and rebuilds incrementally. ccache makes an
# unchanged rebuild cheap.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/external/contrib"
DST="$ROOT"                     # the five runtimes live at the repo root as of 2026-09-08
JOBS="$(nproc)"

# ---- ELF hardening, applied to every engine ------------------------------------------------
#
# Added after the native auditor in symoneural-buildv2 was pointed at the four engines this
# script produces and failed the same two checks on ALL of them:
#
#     FAIL  partial RELRO only: GNU_RELRO present but no BIND_NOW   (need -Wl,-z,now)
#     FAIL  no stack-protector reference                            (need -fstack-protector-strong)
#
# These are the defaults upstream never set and CMake's Release profile does not add. Nobody
# chose them; they were simply absent, which is the difference between a decision and a gap.
#
# `now` turns partial RELRO into full: the GOT is resolved at load and then made read-only, so
# a write primitive cannot redirect a not-yet-resolved import. `relro` is stated explicitly
# rather than relied on -- it is the default on this toolchain and defaults are what change
# under you. `-fstack-protector-strong` rather than `-all`: strong covers the functions that
# actually take arrays and address-taken locals at a fraction of the cost, which matters in a
# tensor kernel loop.
#
# _FORTIFY_SOURCE is deliberately NOT set here. It requires an optimisation level to do
# anything, silently does nothing without one, and emits a warning when a build overrides -O --
# so setting it globally across four very differently-configured trees would produce noise and
# a false sense of coverage. The auditor reports it as SKIP rather than FAIL for exactly that
# reason, and a SKIP that is honest beats a flag that is decorative.
#
# NOT addressed, and not a defect: the auditor also fails RPATH/RUNPATH present, and it is
# right to for the binary it was written for. That check assumes a privileged binary, where a
# RUNPATH is an attack surface. These engines are unprivileged and their RUNPATH is `$ORIGIN`,
# which is the thing that lets an installer relocate them at all -- removing it would trade a
# risk we do not carry for a bug we would. Recorded here so the next person reading a red line
# in that report knows it was considered rather than missed.
SYMONEURAL_HARDEN_C="-fstack-protector-strong"
SYMONEURAL_HARDEN_LD="-Wl,-z,relro -Wl,-z,now"

# The ASR upstream is not under external/contrib with the other two -- it was vendored
# into a differently-named parent. Searched rather than hard-coded to one spelling, because
# the whole reason this engine did not exist for so long is that its source was assumed to
# be somewhere it was not. First hit that actually looks like the tree wins; if none does,
# fork_listen says where it looked instead of failing with an empty path.
# Generalised to all three engines, not just this one. `external/contrib` no longer holds
# llama.cpp or stable-diffusion.cpp either -- it holds a miner build script and cuda-samples
# -- so `fork_engines.sh llm` and `diffuse` could not rebuild the two engines this box
# actually serves from, and nothing noticed: the binaries were already built and sitting in
# engines/, which is gitignored. That is a packaging problem before it is a build problem.
# An installer that cannot rebuild an engine from source can only ship a binary somebody
# built by hand once, which is the state this repo has been burned by twice already.
#
# Each candidate is confirmed to LOOK like the tree rather than merely exist -- an empty
# directory of the right name is the failure this guards against.
upstream_src() {
    local name="$1" c
    for c in "$SRC/$name" \
             "$ROOT/external/referencestochatgpt/$name"; do
        [ -f "$c/CMakeLists.txt" ] && [ -d "$c/src" ] && { printf '%s' "$c"; return 0; }
    done
    return 1
}

log() { printf '\n=== %s\n' "$*"; }

# Rewrite one identity string in a fork, and ASSERT rather than hope.
#
# `$dst` is the calling fork_* function's engine directory -- bash resolves it dynamically, so
# this stays one definition shared by every engine instead of a copy per fork that can drift.
#
# Three-way on purpose, and the third branch is the one that earns its keep: rewrite the
# upstream spelling if it is there; accept ours if this is a re-run; otherwise STOP. A plain
# `sed` would silently no-op when an upstream refresh moves a string, and the engine would go
# back to shipping somebody else's name with a green build. fork_diffuse's version banner has
# used this contract since it was written and has never regressed.
subst() { # file old new
    local f="$dst/$1" old="$2" new="$3"
    [ -f "$f" ] || { echo "fork_engines: $1 is not where it was" >&2; return 1; }
    if grep -qF "$old" "$f"; then
        python3 - "$f" "$old" "$new" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
p.write_text(p.read_text().replace(sys.argv[2], sys.argv[3]))
PY
    elif ! grep -qF "$new" "$f"; then
        echo "fork_engines: neither the upstream nor our spelling is in $1;" >&2
        echo "  the string moved. Find it and rename it, or this engine ships under" >&2
        echo "  somebody else's identity. Looked for: $old" >&2
        return 1
    fi
}

# ---------------------------------------------------------------- licence stamping
#
# Renaming the artefact and fixing the announced identity -- which the rest of this script
# does carefully -- says nothing about the LICENCE the fork ships under. Measured on
# 2026-09-08, every engine shipped its upstream's licence text as its own `LICENSE` and
# nothing recorded that our modifications are ours. The four MIT engines were understating
# our position; the miner was overstating it, because its upstream is GPL-3.0 and it was
# sitting in a tree the project describes as first-party.
#
# So this decides per engine, from the licence actually on disk, and it is deliberately
# capable of REFUSING:
#
#   permissive upstream (MIT / BSD / ISC / Apache-2.0)
#       Our modifications get the SyMoNeuRaL licence. The upstream text is preserved as
#       LICENSE.upstream, because every one of those licences requires the notice to travel
#       with the code, and dropping it is the one thing that turns compliance into
#       infringement. THIRD_PARTY_NOTICES.md records what came from where.
#
#   copyleft upstream (GPL / LGPL / AGPL)
#       REFUSED. The upstream LICENSE stays exactly where it is, no SyMoNeuRaL licence is
#       written, and THIRD_PARTY_NOTICES.md says plainly that this engine is not
#       first-party and cannot be made so by editing files. A licence is a grant from the
#       copyright holders, not a string in a file: replacing GPL text with a permissive
#       notice does not relicense anything, it just removes a notice we are required to
#       keep. Two engines are in this position -- symoneural-miner (kawpowminer, itself
#       descended from ethminer) and symoneural-ui (ComfyUI).
#
# The refusal is the point. Without it, the next person to add an engine can stamp
# proprietary over copyleft with one careless call, and the artefact ships wrong.
licence_of() { # dir -> permissive | copyleft | unknown
    local f
    # Already stamped: our own LICENSE is in place and the upstream notice was preserved
    # beside it. Classify from the PRESERVED notice, not from ours -- otherwise the second
    # run of this script cannot identify a licence it wrote itself and refuses. That is
    # exactly what happened to symoneural-listen on the first re-run, and a build step that
    # only works once is not idempotent, which this script's header promises it is.
    if [ -f "$1/LICENSE.upstream" ] && grep -qi 'SyMoNeuRaL Proprietary' "$1/LICENSE" 2>/dev/null; then
        grep -qiE 'GNU (GENERAL|LESSER GENERAL|AFFERO GENERAL) PUBLIC LICENSE' "$1/LICENSE.upstream" \
            && { echo copyleft; return 0; }
        echo permissive; return 0
    fi
    for f in "$1/LICENSE" "$1/LICENSE.txt" "$1/LICENSE.md" "$1/COPYING"; do
        [ -f "$f" ] || continue
        if grep -qiE 'GNU (GENERAL|LESSER GENERAL|AFFERO GENERAL) PUBLIC LICENSE' "$f"; then
            echo copyleft; return 0
        fi
        if grep -qiE '^\s*(MIT License|Apache License|ISC License)|Redistribution and use in source and binary forms' "$f"; then
            echo permissive; return 0
        fi
    done
    echo unknown
}

# The README a fork inherits is the UPSTREAM's README, and it advertises the upstream.
# Measured 2026-09-08, after the five runtimes were promoted to their own top-level
# directories: symoneural-listen/README.md opened with a whisper.cpp banner image,
# symoneural-llm/ with a llama.brand image, symoneural-miner/ with "kawpow miner with
# OpenCL, CUDA and stratum support", and the two diffusion trees with upstream centre-
# aligned headers. Anyone opening the repo root saw five first-party folder names whose
# first page named somebody else's project.
#
# Renaming the artefact and the announced identity does not touch this, because a README
# is neither. So it is generated, like the notices, and for the same reason: a hand-written
# one drifts, and this one has to survive every re-fork.
stamp_readme() { # uses $dst; args: <engine-name> <role> <upstream-name>
    local name="$1" role="$2" upstream="$3" kind
    kind="$(licence_of "$dst")"
    if [ -f "$dst/README.md" ] && [ ! -f "$dst/README.upstream.md" ]; then
        mv -- "$dst/README.md" "$dst/README.upstream.md"
    fi
    cat > "$dst/README.md" <<READ
# $name

$role

Built by \`tools/fork_engines.sh\` from vendored upstream source. This directory is a
**derived tree** and is gitignored: the recipe is tracked, the 11 GB of objects are not.
Delete it and re-run the fork and you get the same engine back.

## Identity

| | |
|---|---|
| Binary | \`build/$( [ "$name" = symoneural-miner ] && echo kawpowminer || echo bin )/$name\` |
| Announced identity | audited by \`tools/probe_engines.py\` -- version string, help text, and for a serving engine the HTTP \`Server\` header and model-ownership fields |
| Licence | see \`LICENSE\` and \`THIRD_PARTY_NOTICES.md\` in this directory |
| Upstream README | preserved verbatim as \`README.upstream.md\` |

The upstream README is kept rather than deleted because it is the provenance, and because
the attribution obligations in \`THIRD_PARTY_NOTICES.md\` are easier to honour when the
document they refer to is still here.

## Rebuild

\`\`\`bash
tools/fork_engines.sh ${name#symoneural-}      # sync, patch identity, build
tools/fork_engines.sh licences                 # licence + notices + this README only
\`\`\`

Regenerated by \`tools/fork_engines.sh\`. Do not hand-edit.
READ
    echo "  readme:  first-party README written (upstream preserved as README.upstream.md)"
}

stamp_licence() { # uses $dst; args: <engine-name> <upstream-name>
    local name="$1" upstream="$2" kind
    kind="$(licence_of "$dst")"

    case "$kind" in
    permissive)
        # Preserve first, overwrite second. If the copy fails we must not have replaced the
        # notice we are obliged to keep, so ordering here is a correctness property.
        if [ -f "$dst/LICENSE" ] && [ ! -f "$dst/LICENSE.upstream" ]; then
            cp -- "$dst/LICENSE" "$dst/LICENSE.upstream"
        fi
        [ -f "$dst/LICENSE.upstream" ] || {
            echo "fork_engines: $name reports a permissive upstream but its notice could" >&2
            echo "  not be preserved. Refusing to write our licence over it." >&2
            return 1; }
        cp -- "$ROOT/LICENSE" "$dst/LICENSE"
        cat > "$dst/THIRD_PARTY_NOTICES.md" <<NOTICE
# Third-party notices — $name

\`LICENSE\` in this directory is the **SyMoNeuRaL Proprietary License**, and it covers the
SyMoNeuRaL modifications: the rename, the announced identity, the build configuration and
the hardening flags applied by \`tools/fork_engines.sh\`.

It does **not** cover the upstream work this engine is derived from.

| | |
|---|---|
| Upstream | \`$upstream\` |
| Upstream licence | permissive — full text preserved verbatim in \`LICENSE.upstream\` |
| Obligation | the upstream notice and copyright must travel with any copy of this engine |

The upstream licence permits proprietary modification **provided its notice is retained**.
That is why \`LICENSE.upstream\` exists and why it must not be deleted: removing it does not
simplify the licensing, it breaches it.

Regenerated by \`tools/fork_engines.sh\`. Do not hand-edit.
NOTICE
        echo "  licence: SyMoNeuRaL over permissive $upstream (notice preserved)"
        ;;
    copyleft)
        rm -f -- "$dst/LICENSE.upstream"        # never leave a stale permissive-path artefact
        cat > "$dst/THIRD_PARTY_NOTICES.md" <<NOTICE
# Third-party notices — $name

**This engine is NOT first-party and cannot be made first-party by editing files here.**

| | |
|---|---|
| Upstream | \`$upstream\` |
| Upstream licence | **copyleft** — see \`LICENSE\` in this directory, which is the upstream's own text and stays that way |
| SyMoNeuRaL licence | **not applied**, deliberately |

\`tools/fork_engines.sh\` refuses to write the SyMoNeuRaL Proprietary License over a copyleft
upstream. A licence is a grant from the copyright holders; replacing the text in this file
would not relicense the code, it would only remove a notice the project is required to keep,
turning a compliant position into an infringing one.

The routes to a first-party engine here are a clean-room implementation, an upstream under a
permissive licence, or shipping this one as what it is — separate, labelled, and compliant.

Regenerated by \`tools/fork_engines.sh\`. Do not hand-edit.
NOTICE
        echo "  licence: REFUSED to stamp proprietary over copyleft $upstream — left as-is"
        ;;
    *)
        echo "fork_engines: cannot identify the upstream licence of $name." >&2
        echo "  Refusing to guess. Identify it by hand, then extend licence_of()." >&2
        return 1
        ;;
    esac
}

# ---------------------------------------------------------------- symoneural-llm
fork_llm() {
    local src dst="$DST/symoneural-llm"
    src="$(upstream_src llama.cpp)" || {
        echo "no llama.cpp upstream found under external/ -- looked beside the other" >&2
        echo "  engines and under the vendored tree that actually holds it." >&2; return 1; }

    log "syncing llm source -> $dst"
    mkdir -p "$dst"
    # node_modules is 711 MB of the web UI's build-time dependencies and is not needed to
    # build the server; tools/ui/dist (the already-built UI the server serves) IS kept.
    # The vocab .gguf files under models/ are test fixtures, not weights we serve.
    rsync -a --delete \
        --exclude '.git/' \
        --exclude '/build/' \
        --exclude 'tools/ui/node_modules/' \
        --exclude 'models/*.gguf' \
        "$src/" "$dst/"

    # ---- identity, not just filenames -------------------------------------------------
    #
    # OUTPUT_NAME below renames the ARTIFACTS. It does nothing about the identity the running
    # program announces, and this engine announced somebody else's on every single response:
    #
    #   Server: llama.cpp          on every HTTP reply, to every client
    #   owned_by: llamacpp         in the OpenAI-compatible /v1/models body, twice
    #   llamacpp:*                 the entire Prometheus metric namespace
    #   "llama.cpp does not ..."   in exception text a user reads
    #
    # `/v1/*` is a published route, so this was our product reporting a third-party identity
    # to anything that asked. Renaming the .so files while the server introduces itself as
    # llama.cpp is renaming the box and not the label.
    #
    # `subst` asserts. If an upstream refresh moves a string, the build STOPS rather than
    # quietly shipping the upstream name again -- the same contract fork_diffuse's version
    # banner uses, and the reason that one has never regressed. Checked in this order: if the
    # old spelling is present, rewrite it; else if ours is already there, this is a re-run;
    # else the string moved and we refuse.
    log "installing our identity"
    # The one that goes out on EVERY response.
    subst tools/server/server-http.cpp   '{"Server", "llama.cpp"}'  '{"Server", "SyMoNeuRaL LLM"}'
    # The OpenAI-compatible model owner, in two places. Lowercase and no spaces: it is an API
    # value other software matches on, not prose.
    subst tools/server/server-models.cpp  '"owned_by",      "llamacpp"' '"owned_by",      "symoneural"'
    subst tools/server/server-context.cpp '{"owned_by", "llamacpp"}'    '{"owned_by", "symoneural"}'
    # Exception and description text a person reads.
    subst tools/server/server-chat.cpp \
        "llama.cpp does not support 'previous_response_id'." \
        "SyMoNeuRaL LLM does not support 'previous_response_id'."
    subst tools/server/server-chat.cpp \
        "'input_file' is not supported by llamacpp at this moment" \
        "'input_file' is not supported by SyMoNeuRaL LLM at this moment"
    subst tools/server/server-schema.cpp \
        'Use backend sampling instead of llama.cpp sampling' \
        'Use backend sampling instead of SyMoNeuRaL LLM sampling'
    # The MCP server's advertised name.
    subst tools/server/server-mcp.cpp '"llama.cpp"' '"SyMoNeuRaL LLM"'
    # The Prometheus namespace. Nothing of ours parses these names -- `symon_client.py` and
    # `symon_client.js` return /metrics as opaque text -- so this is free to change now and
    # expensive to change once a dashboard exists.
    subst tools/server/server-task.cpp 'llamacpp:' 'symoneural:'
    # The CMake project name. Verified not load-bearing before touching it: PROJECT_NAME is
    # referenced nowhere in this tree's CMake, so nothing keys install paths or config files
    # off it.
    subst CMakeLists.txt 'project("llama.cpp" C CXX)' 'project("symoneural-llm" C CXX)'

    log "installing our names"
    mkdir -p "$dst/cmake"
    cat > "$dst/cmake/symoneural-names.cmake" <<'CMAKE'
# Ship under SyMoNeuRaL names. OUTPUT_NAME rewrites only the filename produced on disk --
# every target_link_libraries() in the tree refers to the CMake target name, which is
# untouched, so the dependency graph is exactly as upstream configured it.
#
# Safe only while GGML_BACKEND_DL is OFF. With it ON, ggml discovers backends by globbing
# libggml-*.so and these renames would hide the CUDA backend at runtime.
if(GGML_BACKEND_DL)
    message(FATAL_ERROR
        "symoneural-names.cmake: GGML_BACKEND_DL is ON. Renaming the ggml backend "
        "libraries would make them undiscoverable at runtime. Refusing to configure.")
endif()

# target                 -> filename on disk        ("cuda" stays: vendor name, exempt)
set(SYMONEURAL_NAME_MAP
    "llama"              "symoneural_llm"
    "llama-common"       "symoneural_llm_common"
    "ggml"               "symoneural_tensor"
    "ggml-base"          "symoneural_tensor_base"
    "ggml-cpu"           "symoneural_tensor_cpu"
    "ggml-cuda"          "symoneural_tensor_cuda"
    "mtmd"               "symoneural_multimodal"
    "llama-server-impl"  "symoneural_llm_server_impl"
    "llama-cli-impl"     "symoneural_llm_cli_impl"
    "llama-server"       "symoneural-llm"
    # The one-shot CLI. `bin/symoneural-cli`'s `chat` runs this rather than the
    # server, deliberately: `api.py` owns the server inside gpu.hold("chat") and a
    # second spawner would race it for :8081 and the lease. Building only the server
    # left that path pointing at a binary this fork does not produce.
    "llama-cli"          "symoneural-llm-cli"
)

list(LENGTH SYMONEURAL_NAME_MAP _n)
math(EXPR _last "${_n} / 2 - 1")
foreach(_i RANGE ${_last})
    math(EXPR _ti "${_i} * 2")
    math(EXPR _ni "${_ti} + 1")
    list(GET SYMONEURAL_NAME_MAP ${_ti} _target)
    list(GET SYMONEURAL_NAME_MAP ${_ni} _outname)
    if(TARGET ${_target})
        set_target_properties(${_target} PROPERTIES OUTPUT_NAME "${_outname}")
        message(STATUS "symoneural: ${_target} -> ${_outname}")
    endif()
endforeach()
CMAKE

    # Append the include once, at the very end, so every target is already defined.
    local marker='include(${CMAKE_CURRENT_LIST_DIR}/cmake/symoneural-names.cmake)'
    if ! grep -qF 'symoneural-names.cmake' "$dst/CMakeLists.txt"; then
        printf '\n# SyMoNeuRaL: rename the shipped artefacts. Must stay last -- it needs\n# every target to exist already.\n%s\n' \
            "$marker" >> "$dst/CMakeLists.txt"
    fi

    log "configuring llm (CUDA, sm_120)"
    cmake -S "$dst" -B "$dst/build" \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=ON \
        -DGGML_CUDA=ON \
        -DGGML_NATIVE=ON \
        -DCMAKE_CUDA_ARCHITECTURES=120 \
        -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
        -DLLAMA_CURL=OFF \
        -DLLAMA_BUILD_TESTS=OFF \
        -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
        -DCMAKE_C_FLAGS="$SYMONEURAL_HARDEN_C" \
        -DCMAKE_CXX_FLAGS="$SYMONEURAL_HARDEN_C" \
        -DCMAKE_EXE_LINKER_FLAGS="$SYMONEURAL_HARDEN_LD" \
        -DCMAKE_SHARED_LINKER_FLAGS="$SYMONEURAL_HARDEN_LD" \
        -DCMAKE_C_COMPILER_LAUNCHER=ccache \
        -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
        -DCMAKE_CUDA_COMPILER_LAUNCHER=ccache

    log "building the llm server and the one-shot cli (their deps, not the whole tool suite)"
    cmake --build "$dst/build" --target llama-server llama-cli -j "$JOBS"

    stamp_licence symoneural-llm llama.cpp
}

# ------------------------------------------------------------ symoneural-diffuse
fork_diffuse() {
    local src dst="$DST/symoneural-diffuse"
    src="$(upstream_src stable-diffusion.cpp)" || {
        echo "no stable-diffusion.cpp upstream found under external/ -- looked beside the" >&2
        echo "  other engines and under the vendored tree that actually holds it." >&2; return 1; }

    log "syncing diffuse source -> $dst"
    mkdir -p "$dst"
    # NOTE the leading slash on '/build/'. Unanchored, rsync's pattern matches a
    # directory called build at ANY depth -- and this tree has
    # thirdparty/libwebm/build/cxx_flags.cmake, which defines require_cxx_flag_nomsvc.
    # Dropping it fails configure with "Unknown CMake command", which reads like a CMake
    # version problem and is not one. Anchored, it means only the top-level build output.
    rsync -a --delete --exclude '.git/' --exclude '/build/' "$src/" "$dst/"

    # The CLI prints its own product name in its version banner, which is a third-party
    # name in output a person reads. One line, and it has to be done HERE rather than by
    # hand in the fork, because the rsync above re-syncs the tree on every run and would
    # wipe a manual edit. Asserted, not hoped: if an upstream refresh moves this string the
    # build stops rather than quietly shipping the old name again.
    local banner='symoneural-diffuse/examples/common/common.cpp'
    banner="$dst/examples/common/common.cpp"
    if grep -q '"stable-diffusion.cpp version "' "$banner"; then
        sed -i 's/"stable-diffusion.cpp version "/"SyMoNeuRaL Diffuse version "/' "$banner"
    elif ! grep -q '"SyMoNeuRaL Diffuse version "' "$banner"; then
        echo "fork_engines: the version banner in $banner is not where it was; find it and" >&2
        echo "  rename it, or this engine ships under somebody else's product name." >&2
        return 1
    fi

    log "installing our names"
    mkdir -p "$dst/cmake"
    cat > "$dst/cmake/symoneural-names.cmake" <<'CMAKE'
# See the note in symoneural-llm/cmake/symoneural-names.cmake -- same mechanism, same
# reason. "cuda" is the exempt vendor name and stays.
if(GGML_BACKEND_DL)
    message(FATAL_ERROR "symoneural-names.cmake: GGML_BACKEND_DL is ON; refusing.")
endif()

set(SYMONEURAL_NAME_MAP
    "stable-diffusion"  "symoneural_diffuse_core"
    "ggml"              "symoneural_tensor"
    "ggml-base"         "symoneural_tensor_base"
    "ggml-cpu"          "symoneural_tensor_cpu"
    "ggml-cuda"         "symoneural_tensor_cuda"
    "sd-cli"            "symoneural-diffuse"
)

list(LENGTH SYMONEURAL_NAME_MAP _n)
math(EXPR _last "${_n} / 2 - 1")
foreach(_i RANGE ${_last})
    math(EXPR _ti "${_i} * 2")
    math(EXPR _ni "${_ti} + 1")
    list(GET SYMONEURAL_NAME_MAP ${_ti} _target)
    list(GET SYMONEURAL_NAME_MAP ${_ni} _outname)
    if(TARGET ${_target})
        set_target_properties(${_target} PROPERTIES OUTPUT_NAME "${_outname}")
        message(STATUS "symoneural: ${_target} -> ${_outname}")
    endif()
endforeach()
CMAKE

    if ! grep -qF 'symoneural-names.cmake' "$dst/CMakeLists.txt"; then
        printf '\n# SyMoNeuRaL: rename the shipped artefacts. Must stay last.\n%s\n' \
            'include(${CMAKE_CURRENT_LIST_DIR}/cmake/symoneural-names.cmake)' \
            >> "$dst/CMakeLists.txt"
    fi

    log "configuring diffuse (CUDA, sm_120)"
    cmake -S "$dst" -B "$dst/build" \
        -DCMAKE_BUILD_TYPE=Release \
        -DSD_CUDA=ON \
        -DCMAKE_CUDA_ARCHITECTURES=120 \
        -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc \
        -DCMAKE_C_FLAGS="$SYMONEURAL_HARDEN_C" \
        -DCMAKE_CXX_FLAGS="$SYMONEURAL_HARDEN_C" \
        -DCMAKE_EXE_LINKER_FLAGS="$SYMONEURAL_HARDEN_LD" \
        -DCMAKE_SHARED_LINKER_FLAGS="$SYMONEURAL_HARDEN_LD" \
        -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
        -DCMAKE_C_COMPILER_LAUNCHER=ccache \
        -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
        -DCMAKE_CUDA_COMPILER_LAUNCHER=ccache

    log "building diffuse cli"
    cmake --build "$dst/build" --target sd-cli -j "$JOBS"

    stamp_licence symoneural-diffuse stable-diffusion.cpp
}

# ---------------------------------------------------------------- symoneural-listen
#
# THE ASR ENGINE, AND WHY IT IS CPU-ONLY. This is not a default being accepted, it is the
# same choice `scripts/fetch-whisper.sh` made and argued: one card, one tenant at a time.
# A spoken sticker is ASR -> text -> render, and if the ASR were a CUDA tenant that becomes
# take the lock, transcribe, release, wait out the drain floor, take the lock again. So the
# transcription stays off the card, where it runs *while* another surface holds the GPU.
# RavenCalc is the precedent. `-DGGML_CUDA=OFF` below is that decision, written down.
#
# WHY IT LIVES HERE RATHER THAN IN contrib/. `contrib/` is banned by
# `backend/apps/test_references_boundary.py` and, more to the point, `/contrib` is
# gitignored -- which is how this capability disappeared the first time, and how the miner's
# benchmark binary disappeared too. Two instances made it a pattern; building into
# `engines/` under our own name is the fix for the pattern, not just for this engine.
fork_listen() {
    local src dst="$DST/symoneural-listen"
    if ! src="$(upstream_src whisper.cpp)"; then
        echo "no whisper upstream found under external/ -- looked beside the other two" >&2
        echo "  engines and under the vendored tree that actually holds it." >&2
        return 1
    fi

    log "syncing listen source -> $dst  (from ${src#"$ROOT"/})"
    mkdir -p "$dst"
    # '/build/' anchored for the reason fork_diffuse spells out at length, and here it also
    # drops the 973 KB whisper-cli already sitting in the vendored tree -- a binary under a
    # third-party name that must not be what we ship.
    rsync -a --delete --exclude '.git/' --exclude '/build/' "$src/" "$dst/"

    # The CLI prints a third-party product name in output a person reads. Same treatment and
    # same assertion as diffuse: if an upstream refresh moves this string the build stops
    # rather than quietly shipping somebody else's name again.
    local banner="$dst/examples/cli/cli.cpp"
    if grep -q '"whisper\.cpp version: %s' "$banner"; then
        sed -i 's/"whisper\.cpp version: %s/"SyMoNeuRaL Listen version: %s/' "$banner"
    elif ! grep -q '"SyMoNeuRaL Listen version: %s' "$banner"; then
        echo "fork_engines: the version banner in $banner is not where it was; find it and" >&2
        echo "  rename it, or this engine ships under somebody else's product name." >&2
        return 1
    fi

    log "installing our names"
    mkdir -p "$dst/cmake"
    cat > "$dst/cmake/symoneural-names.cmake" <<'CMAKE'
# See the note in symoneural-llm/cmake/symoneural-names.cmake -- same mechanism, same
# reason. "cuda" is the exempt vendor name and stays.
if(GGML_BACKEND_DL)
    message(FATAL_ERROR "symoneural-names.cmake: GGML_BACKEND_DL is ON; refusing.")
endif()

set(SYMONEURAL_NAME_MAP
    "whisper"       "symoneural_listen_core"
    "ggml"          "symoneural_tensor"
    "ggml-base"     "symoneural_tensor_base"
    "ggml-cpu"      "symoneural_tensor_cpu"
    "whisper-cli"   "symoneural-listen"
)

list(LENGTH SYMONEURAL_NAME_MAP _n)
math(EXPR _last "${_n} / 2 - 1")
foreach(_i RANGE ${_last})
    math(EXPR _ti "${_i} * 2")
    math(EXPR _ni "${_ti} + 1")
    list(GET SYMONEURAL_NAME_MAP ${_ti} _target)
    list(GET SYMONEURAL_NAME_MAP ${_ni} _outname)
    if(TARGET ${_target})
        set_target_properties(${_target} PROPERTIES OUTPUT_NAME "${_outname}")
        message(STATUS "symoneural: ${_target} -> ${_outname}")
    endif()
endforeach()
CMAKE

    if ! grep -qF 'symoneural-names.cmake' "$dst/CMakeLists.txt"; then
        printf '\n# SyMoNeuRaL: rename the shipped artefacts. Must stay last.\n%s\n' \
            'include(${CMAKE_CURRENT_LIST_DIR}/cmake/symoneural-names.cmake)' \
            >> "$dst/CMakeLists.txt"
    fi

    log "configuring listen (CPU only -- this never takes the GPU lock)"
    # CMAKE_BUILD_RPATH_USE_ORIGIN makes the RUNPATH `$ORIGIN` instead of the absolute path
    # of whatever directory this happened to be built in. That is a packaging requirement,
    # not a tidiness one: an engine whose RUNPATH names /home/google/... loads nothing once
    # an installer puts it under /opt or /usr/lib, and it fails at load time on the user's
    # machine rather than at build time on ours. `symoneural-llm` already reads `$ORIGIN`;
    # `symoneural-diffuse` does NOT -- it carries an absolute CUDA path -- so the claim in
    # this file's header that both are $ORIGIN is currently true of one of them. Recorded
    # here because the fix for diffuse is the same flag and is not this commit's job.
    cmake -S "$dst" -B "$dst/build" \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_CUDA=OFF \
        -DWHISPER_BUILD_TESTS=OFF \
        -DWHISPER_BUILD_EXAMPLES=ON \
        -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
        -DCMAKE_C_FLAGS="$SYMONEURAL_HARDEN_C" \
        -DCMAKE_CXX_FLAGS="$SYMONEURAL_HARDEN_C" \
        -DCMAKE_EXE_LINKER_FLAGS="$SYMONEURAL_HARDEN_LD" \
        -DCMAKE_SHARED_LINKER_FLAGS="$SYMONEURAL_HARDEN_LD" \
        -DCMAKE_C_COMPILER_LAUNCHER=ccache \
        -DCMAKE_CXX_COMPILER_LAUNCHER=ccache

    log "building listen cli"
    cmake --build "$dst/build" --target whisper-cli -j "$JOBS"

    stamp_licence symoneural-listen whisper.cpp
}

# ---------------------------------------------------------------- symoneural-miner
#
# THE THIRD TIME THIS EXACT BUG HAS BEEN FOUND. `cryptominer/__init__.py` resolved its miner to
# `contrib/kawpowminer/build/kawpowminer/kawpowminer`, and `/contrib` is gitignored -- so the
# binary the Miner surface needs could vanish leaving nothing in `git log` to say it had. That
# is how the ASR engine disappeared, and how this repo's own 52-53 MH/s benchmark binary
# disappeared. Two instances made it a pattern; this is the third, and the fix is the same one:
# build into `engines/` under our own name, from a script that is tracked.
#
# WHY THE DEPENDENCIES ARE COPIED RATHER THAN POINTED AT. The vendored tree carries a prebuilt
# `kawpow-deps` prefix -- boost 1.83, jsoncpp, and cpp-kawpow's libethash, all STATIC. Pointing
# CMAKE_PREFIX_PATH straight at it under `external/` would work and would leave this engine
# unable to build without a read-only tree it is not supposed to depend on. They are static, so
# they are linked in and nothing is loaded from there at runtime either way; copying makes that
# true at BUILD time as well, which is what "first-party" has to mean if it means anything.
#
# WHAT IS NOT RENAMED, and why the exception is stated rather than taken silently: `project()`.
# Unlike llama.cpp, PROJECT_NAME is load-bearing here -- `CMakeLists.txt` feeds it to
# `cable_add_buildinfo_library` and to CPACK_PACKAGE_FILE_NAME -- so renaming it would rewrite
# generated build-info symbols and packaging paths for a name no user ever sees. The strings a
# person actually reads are renamed below.
fork_miner() {
    local src dst="$DST/symoneural-miner" deps
    src="$ROOT/external/referencestochatgpt/kawpowminer"
    deps="$ROOT/external/referencestochatgpt/kawpow-deps"
    [ -f "$src/CMakeLists.txt" ] || {
        echo "no kawpowminer upstream at ${src#"$ROOT"/}" >&2; return 1; }
    [ -d "$deps/lib" ] || {
        echo "no prebuilt dependency prefix at ${deps#"$ROOT"/} -- boost/jsoncpp/ethash" >&2
        echo "  are built by external/contrib/build-kawpowminer.sh and are expected to" >&2
        echo "  already exist; building them here would add ~40 minutes and a network fetch." >&2
        return 1; }

    log "syncing miner source -> $dst"
    mkdir -p "$dst"
    # '/build/' anchored, and it matters more here than elsewhere: the vendored tree carries a
    # working kawpowminer binary from 2026-08-17 under a third-party name. That binary is
    # exactly what must NOT be what we ship, and an unanchored pattern would also eat
    # cmake/cable's own build helpers.
    rsync -a --delete --exclude '.git/' --exclude '/build/' "$src/" "$dst/"

    log "vendoring the static dependency prefix"
    rsync -a --delete "$deps/" "$dst/deps/"

    log "installing our identity"
    # The banner and the --version line, which are the two places a person reads a name.
    subst kawpowminer/main.cpp \
        'kawpowminer - GPU ProgPOW(0.9.3) miner for Zing' \
        'SyMoNeuRaL Miner - GPU ProgPOW(0.9.3) miner for Zing'
    subst kawpowminer/main.cpp '"kawpowminer "' '"SyMoNeuRaL Miner "'

    log "installing our names"
    mkdir -p "$dst/cmake"
    cat > "$dst/cmake/symoneural-names.cmake" <<'CMAKE'
# See symoneural-llm/cmake/symoneural-names.cmake -- same mechanism, same reason. OUTPUT_NAME
# rewrites the artefact written to disk and leaves every CMake target reference alone, so the
# build graph is untouched. "cuda" stays: it names the vendor's toolkit, not a product.
if(TARGET kawpowminer)
    set_target_properties(kawpowminer PROPERTIES OUTPUT_NAME "symoneural-miner")
    message(STATUS "symoneural: kawpowminer -> symoneural-miner")
endif()
CMAKE

    if ! grep -qF 'symoneural-names.cmake' "$dst/CMakeLists.txt"; then
        printf '\n# SyMoNeuRaL: rename the shipped artefacts. Must stay last.\n%s\n' \
            'include(${CMAKE_CURRENT_LIST_DIR}/cmake/symoneural-names.cmake)' \
            >> "$dst/CMakeLists.txt"
    fi

    # COMPUTE=120 is sm_120, this card. HUNTER_ENABLED=OFF because Hunter would go to the
    # network for the dependencies we just vendored. BOOST_BIND_GLOBAL_PLACEHOLDERS is not
    # optional: Boost >= 1.73 stopped injecting `_1` into the global namespace, and the source
    # patches for that are already applied in the vendored checkout.
    log "configuring miner (CUDA, sm_120)"
    cmake -S "$dst" -B "$dst/build" \
        -DHUNTER_ENABLED=OFF \
        -DCOMPUTE=120 \
        -DETHASHCL=OFF -DETHASHCUDA=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_PREFIX_PATH="$dst/deps" \
        -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
        -DCMAKE_C_FLAGS="$SYMONEURAL_HARDEN_C" \
        -DCMAKE_EXE_LINKER_FLAGS="$SYMONEURAL_HARDEN_LD" \
        -DCMAKE_SHARED_LINKER_FLAGS="$SYMONEURAL_HARDEN_LD" \
        -DCMAKE_CXX_FLAGS="-DBOOST_BIND_GLOBAL_PLACEHOLDERS $SYMONEURAL_HARDEN_C"

    log "building the miner"
    cmake --build "$dst/build" -j "$JOBS"

    stamp_licence symoneural-miner kawpowminer
}

case "${1:-all}" in
    llm)     fork_llm ;;
    diffuse) fork_diffuse ;;
    listen)  fork_listen ;;
    miner)   fork_miner ;;
    all)     fork_llm; fork_diffuse; fork_listen; fork_miner ;;
    licences)
        # Stamp only. Nothing is synced and nothing is compiled, so this is safe to run
        # against engines that are already built -- which is the whole reason it exists:
        # the licence position needed fixing on 2026-09-08 without spending an hour of
        # CUDA rebuild to do it.
        for e in llm:llama.cpp diffuse:stable-diffusion.cpp listen:whisper.cpp \
                 miner:kawpowminer ui:ComfyUI; do
            dst="$DST/symoneural-${e%%:*}"
            [ -d "$dst" ] || { echo "  skip symoneural-${e%%:*} (not forked)"; continue; }
            echo "symoneural-${e%%:*}:"
            stamp_licence "symoneural-${e%%:*}" "${e##*:}" || true
            case "${e%%:*}" in
              llm)     r="Language-model serving. HTTP on 127.0.0.1:8081." ;;
              diffuse) r="Diffusion image generation on the RTX 5070 Ti." ;;
              listen)  r="Speech recognition. CPU only." ;;
              miner)   r="Mining control: GPU, ASIC and settlement." ;;
              ui)      r="Graph and workflow editor for the render surface." ;;
            esac
            stamp_readme "symoneural-${e%%:*}" "$r" "${e##*:}" || true
        done
        ;;
    *)       echo "usage: $0 [llm|diffuse|listen|miner|all|licences]" >&2; exit 2 ;;
esac

log "done -- artefacts under $DST"
# Scoped to the five runtime directories. `DST` became `$ROOT` when the runtimes were
# promoted to top level, which made this walk the whole repo and try to readelf
# `bin/symoneural-cli` -- a shell script. "Not an ELF file" at the end of a successful
# build reads as a build failure to anyone skimming.
for d in "$DST"/symoneural-*/; do
    [ -d "$d" ] || continue
    find "$d" -maxdepth 3 -type f -name 'symoneural-*' -perm -u+x 2>/dev/null | while read -r b; do
        file -b "$b" | grep -q ELF || continue
        printf '  %s\n' "${b#$ROOT/}"
        readelf -d "$b" | grep -E 'RUNPATH|RPATH' | sed 's/^/      /'
    done
done
