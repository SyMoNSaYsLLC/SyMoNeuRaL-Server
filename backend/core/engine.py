"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.config import CHAT_ADAPTER, CHAT_CTX_TOTAL, CHAT_MODEL, DRAFT_MODEL, JOB_TIMEOUT_S, LLAMA_PORT, LLM_ENGINE, SPEC_DRAFT_MAX

import asyncio
import json
import os
import signal
import subprocess
import time
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from hardware.lib.gpu import record_engine
from hardware.lib import modelmetrics  # noqa: E402
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the
import live  # noqa: E402  -- his OBS stream, watchable while it runs and after it

from core.context import ctx


def _gguf_arch(path):
    """`general.architecture` out of a GGUF header, or None if it cannot be read.

    Reads a few KB, not the weights: the architecture is one of the first KV pairs, so this
    returns long before it has touched any tensor data. Deliberately total -- a truncated
    file, a non-GGUF file, a missing file and an unknown value type all return None rather
    than raising, because every caller is a status surface or a launch decision and neither
    should crash over metadata.
    """
    import struct
    _SCALAR = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    try:
        with open(path, "rb") as fh:
            if fh.read(4) != b"GGUF":
                return None
            _version, _n_tensors, n_kv = struct.unpack("<IQQ", fh.read(20))

            def skip(vtype):
                if vtype == 8:                                    # string
                    (n,) = struct.unpack("<Q", fh.read(8))
                    fh.seek(n, 1)
                elif vtype == 9:                                  # array
                    (elem,) = struct.unpack("<I", fh.read(4))
                    (n,) = struct.unpack("<Q", fh.read(8))
                    for _ in range(n):
                        skip(elem)
                else:
                    fh.seek(_SCALAR[vtype], 1)

            for _ in range(min(n_kv, 4096)):
                (klen,) = struct.unpack("<Q", fh.read(8))
                key = fh.read(klen)
                (vtype,) = struct.unpack("<I", fh.read(4))
                if key == b"general.architecture" and vtype == 8:
                    (n,) = struct.unpack("<Q", fh.read(8))
                    return fh.read(n).decode("utf-8", "replace")
                skip(vtype)
    except Exception:
        return None
    return None
def draft_applies():
    """Whether DRAFT_MODEL can be used with CHAT_MODEL -- not merely whether it is on disk.

    Same defect as `adapter_applies` and the same fix, one flag along. `-md` was added
    whenever the file existed, which was safe only while chat and draft were both qwen2.
    The 30B-A3B is `qwen3moe`; the draft is `qwen2`. Speculative decoding needs the two to
    share a vocabulary, and a mismatched draft either refuses at load or -- worse -- starts
    and buys nothing while looking like it works. MEASURED 2026-09-11: the production argv
    with this draft against the 30B exits 1 at load, `cudaMalloc failed` after the draft's
    own weights and KV are added on top.

    Architecture equality is a coarse proxy for vocabulary equality and deliberately so: it
    is readable from the file without loading either model, and it fails in the safe
    direction. Losing speculative decoding costs throughput; applying a mismatched draft
    costs the surface.
    """
    if not DRAFT_MODEL.exists():
        return False
    a, b = _gguf_arch(DRAFT_MODEL), _gguf_arch(CHAT_MODEL)
    return bool(a) and a == b
def adapter_applies():
    """Whether CHAT_ADAPTER can actually be applied to CHAT_MODEL -- not merely whether the
    file is on disk.

    Every caller used to ask `CHAT_ADAPTER.exists()`, which answers a different question, and
    the difference is not academic. MEASURED 2026-08-22: launching the production argv with
    this qwen2 adapter against the gpt-oss candidate exits 1 with

        llama_adapter_lora_init: failed to apply lora adapter: model arch and LoRA arch mismatch

    so on a mismatch the chat surface does not degrade, it fails to start. Worse, the status
    surfaces would have gone on reporting `adapter: true` and advertising "+ persona adapter"
    for an adapter the engine had refused -- a product claiming a persona it is not running.

    Unknown counts as NO. If either architecture cannot be read, this returns False, and the
    asymmetry is deliberate: not applying a matching adapter costs the persona and still
    serves, while applying a mismatched one takes the whole surface down.
    """
    if not CHAT_ADAPTER.exists():
        return False
    model_arch = _gguf_arch(CHAT_MODEL)
    adapter_arch = _gguf_arch(CHAT_ADAPTER)
    if not model_arch or not adapter_arch:
        return False
    return model_arch == adapter_arch
async def run(*argv: str, timeout: int = JOB_TIMEOUT_S, env_owner: bool = False,
              is_engine: bool = False) -> tuple[int, bytes, bytes]:
    """Run a subprocess in its own session, and kill the whole group on timeout.

    Killing only the direct child is not enough: the governor is a wrapper script and the
    engine (sd-cli, llama-server) is its child. SIGKILL to the wrapper leaves the engine
    orphaned, still holding several gigabytes of VRAM, and skips the wrapper's release trap
    so the lock leaks too. A process group makes "stop this job" mean all of it.

    `is_engine` must be opt-in, and the default must be False. This helper is general: it
    also runs `gpu-governor.sh acquire` and `release` at :829 and :843. Recording EVERY
    child as the engine was a real regression, shipped and caught on the live box the same
    day: a chat request left `run/engine` naming the governor's own acquire shell, which had
    already exited, while the actual engine ran on under a different pid. Eviction would
    then have found a dead pid, logged "already exited -- nothing to signal", cleared the
    record and never stopped the engine holding 8.3 GB. Worse than the pattern kill it
    replaced, because it fails silently and looks correct in the ctx.log.
    """
    env = dict(os.environ)
    if env_owner:
        # Name ourselves as the lock owner so the holder pid is a process that will still
        # exist while the card is held.
        env["SYMONEURAL_OWNER_PID"] = str(os.getpid())
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True, env=env)
    if is_engine:
        await record_engine(proc.pid)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HTTPException(504, "That took too long and was stopped.")
    return proc.returncode or 0, out, err
async def anticipate(prompt: str) -> dict | None:
    """Speculatively solve any mathematics in the prompt, on the CPU, in parallel.

    Started before the GPU surface is ready and awaited after, so on a cold chat the whole
    computation happens inside time that was going to be spent loading weights anyway.
    """
    found = ctx.extract_math(prompt)
    if not found:
        return None
    operation, expression, variable = found
    started = time.time()
    result = await asyncio.to_thread(ctx._compute_exact, operation, expression, variable)
    if not result:
        return None
    result["_anticipated_ms"] = round((time.time() - started) * 1000, 1)
    result["_operation"] = operation
    await ctx.bus.announce("ravencalc", "anticipated", operation=operation,
                       expression=expression, ms=result["_anticipated_ms"])
    ctx.log.info("anticipated %s(%s) in %sms", operation, expression, result["_anticipated_ms"])
    return result
async def llama_up() -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", LLAMA_PORT), timeout=2)
        writer.write(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        head = await asyncio.wait_for(reader.read(64), timeout=3)
        writer.close()
        return b"200" in head
    except Exception:
        return False
async def start_llama() -> bool:
    global _llama
    async with ctx._llama_lock:
        if await llama_up():
            return True
        if not CHAT_MODEL.exists() or not LLM_ENGINE.exists():
            return False
        # No acquire here: every caller is already inside gpu.hold("chat"), so the card
        # is ours. Taking a second, longer-lived lock here is exactly what locked the CLI
        # out for the lifetime of the process.
        argv = [str(LLM_ENGINE), "-m", str(CHAT_MODEL), "-ngl", "99",
                "--host", "127.0.0.1", "--port", str(LLAMA_PORT),
                # `-c` is the TOTAL context, divided by `-np`. At the old 8192/4 every
                # chat slot had 2,048 tokens -- roughly 8,000 characters of prompt, reply
                # and entire replayed transcript combined. That, not MAX_PROMPT_CHARS, was
                # the real ceiling on a long conversation, and raising the character cap
                # without raising this would have moved the failure rather than removed it.
                #
                # 65536/2 gives each slot 32,768 -- the full context Qwen2.5-7B was trained
                # for, so it is now the model's own limit rather than one we imposed.
                #
                # MEASURED on this card 2026-08-17, not projected. Started with exactly this
                # argv including --lora, confirmed `n_slots = 2, n_ctx_slot = 32768` in the
                # server ctx.log, and generated a real completion:
                #     9,485 MiB of 16,303 used     (idle baseline 1,084 MiB)
                # so chat costs ~8.2 GiB here, up from the ~5.4 GiB measured at -c 8192 in
                # run/governor.log. 6.6 GiB stays free, which clears the governor's 1.5 GB
                # drain floor with room to spare.
                #
                # An earlier revision of this comment said "~8.7 GB" and was ARITHMETIC I
                # had done, written in a voice that read as a reading off the card. On a
                # site whose entire argument is that its numbers are measured, that is the
                # one mistake that matters. It was also, at the time, describing a config
                # that had never once been started. Measure it, or label it projected.
                #
                # 2026-09-11: 65536 was measured for Qwen2.5-7B (4.36 GiB of weights) and
                # OOMs on the 30B-A3B (10.55 GiB): `cudaMalloc failed: out of memory`
                # allocating the KV. So the number moved into CHAT_CTX_TOTAL beside the
                # model it belongs to, because a context size is a property of the MODEL and
                # the CARD together, and hardcoding one here made it look like a property of
                # the surface.
                "-c", str(CHAT_CTX_TOTAL), "--no-warmup",
                # Continuous batching: one pass over the weights serves every slot in
                # flight, which is the single highest-value lever measured on this card
                # (47.3x from batch 1 to batch 64). Two slots rather than four, because
                # slots divide the context and context is what was actually scarce.
                "-cb", "-np", "2"]
        if draft_applies():
            argv += ["-md", str(DRAFT_MODEL), "-ngld", "99",
                     "--spec-draft-n-max", str(SPEC_DRAFT_MAX)]
        elif DRAFT_MODEL.exists():
            # On disk but not applicable. Say so, for the reason the adapter branch says it:
            # a surface that quietly runs without an accelerator it believes it has produces
            # a throughput number nobody can explain.
            ctx.log.warning("draft model NOT applied: %s is %s, chat model is %s",
                        DRAFT_MODEL.name, _gguf_arch(DRAFT_MODEL), _gguf_arch(CHAT_MODEL))
        if adapter_applies():
            argv += ["--lora", str(CHAT_ADAPTER)]
        elif CHAT_ADAPTER.exists():
            # On disk but not applicable. Say so loudly: the alternative is a surface that
            # quietly serves without its persona and a ctx.log that never mentions it.
            ctx.log.warning("persona adapter NOT applied: %s is %s, chat model is %s",
                        CHAT_ADAPTER.name, _gguf_arch(CHAT_ADAPTER), _gguf_arch(CHAT_MODEL))
        ctx.log.info("starting chat surface")
        _llama = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        # No `start_new_session=True` here, deliberately: the chat engine is long-lived and
        # `stop_llama()` already stops it by handle. So this child shares OUR process group,
        # `record_engine` will decline to offer a pgid, and eviction signals the single pid.
        # That is still an identity, which the pattern it replaces was not.
        await record_engine(_llama.pid)
        for _ in range(120):
            if await llama_up():
                ctx.log.info("chat surface up")
                return True
            await asyncio.sleep(1)
        ctx.log.error("chat surface failed to come up")
        return False
async def stop_llama() -> None:
    global _llama
    async with ctx._llama_lock:
        if _llama and _llama.returncode is None:
            _llama.terminate()
            try:
                await asyncio.wait_for(_llama.wait(), timeout=20)
            except asyncio.TimeoutError:
                _llama.kill()
        _llama = None
async def chat_deltas(messages: list[dict], max_tokens: int, temperature: float,
                      surface: str = "chat"):
    """Yield content deltas from llama-server's OpenAI-compatible endpoint.

    Also captures the engine's own measurements on the way past -- see the `timings` branch
    below. `surface` only labels which caller produced the sample on the metrics page.
    """
    body = json.dumps({"model": "symoneural", "messages": messages, "stream": True,
                       "max_tokens": max_tokens, "temperature": temperature}).encode()
    reader, writer = await asyncio.open_connection("127.0.0.1", LLAMA_PORT)
    writer.write(
        b"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
        b"Content-Type: application/json\r\nConnection: close\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    await writer.drain()
    try:
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=JOB_TIMEOUT_S)
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except Exception:
                continue
            # llama-server appends a `timings` object to the FINAL chunk of every stream:
            # tokens read and written, tok/s both ways, prompt-cache hits -- all measured by
            # the engine while it was already doing the work. Until 2026-09-11 this loop
            # read the content out of each chunk and discarded everything else, so those
            # numbers were measured on every request this box has ever served and thrown
            # away every time. This is the line that keeps them.
            #
            # Cost is one dict copy. NO probe request is issued: a metrics page that asks the
            # model a question to find out how fast the model is would take the GPU lease to
            # do it, and would be measuring itself.
            if "timings" in chunk:
                modelmetrics.record_timings(chunk["timings"], surface=surface)
            try:
                delta = chunk["choices"][0].get("delta", {})
            except (KeyError, IndexError, TypeError):
                continue
            if piece := delta.get("content"):
                yield piece
    finally:
        writer.close()
def guide_ask_model(prompt: str) -> str:
    """Ask the chat surface for one line, on Guide's behalf. Called from a worker thread.

    **It never starts the model.** If chat is not already resident this raises, and Guide
    falls back to its local pass and says so. Starting a 7B to answer "show me motorsport"
    would evict whatever holds the card -- possibly an image render somebody is waiting
    on -- to do work that the CPU already did in under a millisecond. The contended card
    is the whole reason Guide has a local pass at all.
    """
    loop = _LOOP
    if loop is None:
        raise guide.ModelUnusable("the api is not running an event loop yet")

    async def _run() -> str:
        if not await llama_up():
            raise guide.ModelUnusable(
                "the chat surface is not resident; Guide will not evict another surface "
                "to answer a channel filter")
        pieces: list[str] = []
        async for piece in chat_deltas([{"role": "user", "content": prompt}],
                                       max_tokens=64, temperature=0.2):
            pieces.append(piece)
        return "".join(pieces)

    try:
        return asyncio.run_coroutine_threadsafe(_run(), loop).result(timeout=45)
    except guide.ModelUnusable:
        raise
    except Exception as exc:                      # noqa: BLE001
        # Never surface the underlying message: it can quote a socket path or an internal
        # address, and Guide's answer is shown to a visitor.
        raise guide.ModelUnusable(f"chat surface unreachable ({type(exc).__name__})") from None
