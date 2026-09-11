# SyMoNeuRaL Sigils — design spec and background-removal research

**This is a proposal, not state.** `.claude/HANDOVER.md` is the one state document and
`.claude/CLAUDE.md` is the one rulebook; this file is an input to a decision, in the same
sense as its neighbours in `backend/authority/docs/` (see `ops/backend/authority/docs/README.md`). Nothing here is
built. `docs/` is not deployed — `scripts/deploy.sh` publishes `site/` only — so nothing in
this file reaches a visitor.

Written 2026-08-17 against HANDOVER §5 item 13, which already fixes the scope. This file
does not re-derive it; it answers the one question item 13 leaves open — **how the alpha
channel gets made** — and specifies the surface around that answer.

**Every figure in this file carries a label.** `measured` means taken on this box today and
the command is stated. `vendor` means read off a publisher. `projected` means arithmetic.
No render was generated and the GPU was not taken to write this: the card was contended.
That has a consequence stated plainly in §7 — **the single number that decides the
recommendation has not been measured yet**, and the recommendation is conditional on it.

---

## 1. The name is not settled

Working name: **SyMoNeuRaL Sigils**. A sigil is literally a small drawn symbol carrying
meaning, which is what the artefact is, and it sits beside RavenCalc without sounding like a
different company. **Garrett has not confirmed it.** Alternatives and their collision checks
are in §8, at the back, because the name is the cheap decision and the matte is the expensive
one. One finding belongs up here because it bears directly on his stated criterion ("a name
other companies are not using"): **Sigil is an established open-source EPUB editor**
(sigil-ebook.com), and in Perl and Ruby "sigil" is the ordinary jargon for the `$`/`@`
prefix character — a developer audience reads the word as jargon before it reads it as a
brand. Neither is fatal to *SyMoNeuRaL Sigils* as a phrase. Both are things he should know
before he says yes.

Everything below is written with `sigil` as the placeholder identifier. If the name changes,
the identifiers change with it in one pass — route path, output prefix, env var, directory —
and §6.1 explains why the output prefix in particular is not a free choice.

---

## 2. What this is, restated in one paragraph

A sticker in the iPhone sticker-drawer sense: small, **one** subject, hard-edged,
**transparent background**, no scene, no ground shadow, no border decoration. It is a
constrained variant of SyMoNeuRaL Image, not a new agent — the same FLUX.1-schnell GGUF
weights, the same `sd-cli`, a fixed prompt suffix, a smaller canvas — plus one genuinely new
step: **producing an alpha channel, which FLUX does not give you.** Output is PNG with alpha,
written to `backend/output/` and served as `/api/gen/<name>` (HANDOVER §3.3). The
`tools/build/build_gallery.py` watermark bar is **not** applied; §5.6 says what replaces it, because
"do not apply it" on its own loses the provenance the bar exists to carry.

---

## 3. The background-removal decision

This is the deliverable. Four candidate paths, in ascending cost.

### 3.0 What is actually on this box — checked, not assumed

Checked with `find / -xdev` for `u2net`, `rembg`, `birefnet`, `sam_vit`, `isnet`, `modnet`,
`mobile_sam`, and with `ls` on every model directory:

| Claim | Result | Evidence |
|---|---|---|
| Any segmentation weights under `backend/models/` | **None.** `hf/` (Qwen2.5-7B-Instruct), `image/` (FLUX set), `llm/`, `licenses/` | `ls backend/models/*` |
| Any under `references/` | **None.** Thirteen trees, none vision-segmentation; `stable-diffusion-webui-master/` is a design reference with no weights | `ls references/` |
| A root `models/` directory | **Does not exist.** `.claude/CLAUDE.md`'s build block says `fetch-models.sh` writes to `models/`; the tree has `backend/models/`. Cosmetic, but it sent this audit to a non-existent path first — worth one line in HANDOVER when someone next edits it | `ls models/` → No such file or directory |
| `~/.u2net`, `~/.cache/rembg` (rembg's default weight cache) | **Neither exists** | `ls` |
| `rembg`, `onnxruntime`, `cv2`, `torch`, `skimage` in the serving interpreter | **None present** | `python3 -c "import importlib.util…"` |
| `PIL`, `numpy`, `scipy` in the serving interpreter | **All present** — PIL 11.1.0, numpy 2.2.4, scipy 1.15.3 | same |

So: **nothing exists here yet, and the only image-processing capability already inside the
serving path is PIL + numpy + scipy.** That asymmetry drives the whole recommendation, because
`.claude/settings.local.json` denies `pip install` into the system interpreter by design.

The serving path also has **no torch and no ONNX runtime at all** — `/api/image` shells out to
`contrib/stable-diffusion.cpp/build/bin/sd-cli` (a C++ binary, `master-820-de298c2`). Adding
an ML matte is not "adding a model", it is adding an ML *runtime* to a process that has
deliberately never had one.

### 3.1 Option A — prompt-side chroma field + non-ML colour key (recommended)

Constrain FLUX to draw the subject on a flat, saturated field the sticker will never contain
(magenta `#FF00FF` is the classic choice and is essentially absent from natural imagery), then
key it out arithmetically.

**Cost in packages: zero.** PIL, numpy and scipy are already in the serving interpreter.

**Cost in time — measured on this box, 2026-08-17, on six real 768×768 renders from
`backend/output/`, system interpreter, i9-10900KF:**

| Step | Time | Note |
|---|---|---|
| key + `binary_fill_holes` + feather, 768² | **23.6–26.4 ms** (mean ≈ 25.3) | measured |
| RGBA PNG encode, 768² | **66–134 ms** | measured; content-dependent |
| LANCZOS 768 → 512 | **7.1 ms** | measured |

Those timings are **content-independent for the array ops** (fixed-size numpy/scipy work) and
**content-dependent for the PNG encode** (deflate). The keying *quality* on real FLUX output
is **not** measured — see §7. An earlier pass of this bench used a random-noise subject and
produced a 531 KiB encode; that is an incompressible worst case and is not quoted here. The
numbers above are from actual renders.

Against `~11.2 s` for a 768×768 4-step render (HANDOVER §8, measured), a ~25 ms matte is
**~0.2% of the job** (projected from the two measured figures).

**Why it is likely to work here specifically, and why that is not a promise.** Stickers are
the easy case for a colour key: hard-edged, single subject, no hair, no glass, no motion blur,
no depth-of-field. The hard cases for chroma keying — fine hair, transparency, soft focus — are
the cases a sticker is defined by not having. But diffusion models are *suggestible*, not
*obedient*: FLUX will sometimes tint the subject toward the field colour, or shade the field,
or place a soft contact shadow it was not asked for. The pass rate is an empirical question
and §7.1 is the experiment that answers it.

**The algorithm, stated so it can be implemented without re-deriving it:**

1. Distance from the key colour per pixel (sum of absolute channel deltas), threshold to a
   coarse subject mask.
2. `scipy.ndimage.binary_fill_holes` — recovers interior regions that happen to be near the
   key colour (a magenta eye inside a subject would otherwise punch a hole).
3. Border-connected component check: only background regions touching the frame edge are
   background. An enclosed magenta region is subject detail.
4. **Despill.** Non-optional, and it was the gap in the first draft of this spec. Edge pixels
   pick up the field colour and it shows the instant the sticker lands on a white iMessage
   bubble — a magenta halo. Clamp the key channel against the others in **straight
   (non-premultiplied) colour** before the alpha is attached.
5. Feather: a sub-pixel Gaussian on the alpha only. One pixel, not more; a sticker's edge is
   supposed to be hard.
6. Tight-crop to the subject bounding box + a small margin, then resize to the delivery
   canvas (§5.2).

Steps 4 and 6 are not in the timing bench above. Both are cheap array ops on the same buffers;
budget ~40 ms projected for the complete matte and **measure it** rather than publishing 25 ms.

### 3.2 Option B — rembg on CPU, in its own venv, behind a subprocess (recommended fallback)

If §7.1 shows the colour key failing too often, this is the fallback, and it is a fallback
with a shape the repo already uses: **`backend/apps/asicminer/` runs pyasic's 31 packages in
`backend/apps/asicminer/.venv` behind `probe.py`, which prints JSON, and the API execs it.**
Same boundary here: `backend/apps/sigils/.venv`, a `matte.py` that takes a PNG path and writes
an RGBA PNG, and no new package anywhere near the system interpreter.

**Availability and size — measured 2026-08-17 by `pip download --no-deps` (downloads only; no
install, and this does not touch the denied `pip install` path):**

| Wheel | Size | Note |
|---|---|---|
| `rembg-2.0.80-py3-none-any.whl` | **60 KB** | pure python |
| `onnxruntime-1.28.0-cp313…whl` | **19.2 MB** | CPU EP, cp313 wheel exists — the box is Python 3.13.5 |
| `pymatting-1.1.15` | 55 KB | alpha matting refinement |
| `opencv-python-headless-5.0.0.93` | 61.2 MB | **not** a core dep of 2.0.80; listed only because older guidance assumes it |

rembg 2.0.80's non-extra dependencies, read out of the wheel's `METADATA`: `jsonschema`,
`numpy`, `pillow`, `pooch`, `pymatting`, `scikit-image`, `scipy`, `tqdm`. The runtime is an
extra: `onnxruntime` under `[cpu]`, `onnxruntime-gpu` under `[gpu]`.

**Weights — sizes measured by HTTP HEAD against the rembg release URLs read out of the wheel's
session modules, not from memory:**

| Model | Bytes | Licence | Verdict |
|---|---|---|---|
| `u2netp.onnx` | 4,574,861 (4.4 MiB) | Apache-2.0 (vendor) | the cheap one; lower quality |
| `u2net.onnx` | 175,997,641 (167.8 MiB) | Apache-2.0 (vendor) | the default; the one to try first |
| `isnet-general-use.onnx` | 178,648,008 (170.4 MiB) | Apache-2.0 / DIS (vendor) | often better on hard edges |
| `silueta.onnx` | 44,173,029 (42.1 MiB) | Apache-2.0 (vendor) | u2net, size-reduced |
| `BiRefNet-general-…-tiny.onnx` | 224,005,088 (213.6 MiB) | MIT (vendor) | quality ceiling, swin-tiny backbone |
| `BiRefNet-general-epoch_244.onnx` | 972,666,916 (927.6 MiB) | MIT (vendor) | fp32; CPU cost is seconds, not ~1 s |
| `bria-rmbg-2.0.onnx` | 1,024,331,469 (976.9 MiB) | **CC BY-NC 4.0** (vendor) | **disqualified — non-commercial** |
| `birefnet-general.onnx` (lower-case) | — | — | **404**; the real asset names are the mixed-case ones above |

**The licence column is a gate, not a footnote.** `scripts/fetch-models.sh` sources ungated,
permissively licensed weights on purpose and `LICENSES.md` tracks them. BRIA RMBG-2.0 is
CC BY-NC 4.0 with commercial use behind a BRIA agreement; it is the best-known background
remover in this list and it must not be shipped in a commercial product on this basis.
Whichever model is chosen, its licence goes into `LICENSES.md` in the same commit, and if the
attribution is a licence condition it must not be ellipsised anywhere it is displayed —
CLAUDE.md's rule about `…7B-Ins…` applies verbatim.

**CPU inference time is UNMEASURED.** u2net at 320×320 is commonly reported around one second
on a desktop CPU, and this is a 10-core i9-10900KF with 20 threads and 94 GB of RAM, so the
projection is favourable — but no number for it appears in this file, and none may appear on
the site, until §7.5 is run. The 927 MiB fp32 BiRefNet in particular should be assumed to be
seconds, not ~1 s.

**Disk:** ~20 MB of wheels + deps, plus one weight file, plus a venv. Free space measured:
**884 GB on `/home`, 281 GB on `/`.** Not a constraint.

### 3.3 Option C — GPU segmentation as a governor tenant (rejected, with the arithmetic)

**The card, measured 2026-08-17:** `nvidia-smi` reports **16,303 MiB total, 1,012 MiB used at
idle, 0% utilisation** — 15.92 GiB, matching HANDOVER §8.

**What the image surface occupies (file sizes measured, residency from HANDOVER §8):**

```
symoneural-image-unet-q4_k.gguf   6,884,606,880 B   6.41 GiB   on card
symoneural-image-vae.safetensors              335,304,388 B   0.31 GiB   on card
symoneural-image-clip.safetensors          246,144,152 B   0.23 GiB   text encoder
symoneural-image-t5-q8_0.gguf           5,199,794,784 B   4.84 GiB   on CPU -- api.py passes --backend te=cpu
```

`/api/image` already fights for this space, and `backend/server.py` documents why: without
`te=cpu` and `--vae-tiling`, "a 768x768 render dies in VAE decode: it wants a 3.7 GB compute
buffer, and with the 5.2 GB T5 encoder also resident there is nothing left."

**Concurrent with the render — rejected.** Nominal headroom is
`15.92 − 0.99 idle − 6.72 weights ≈ 8.2 GiB` (projected), but the VAE compute buffer moves
through that space in bursts and there is no mechanism to reserve against it. A second CUDA
tenant sharing the card mid-render is exactly the failure the governor exists to prevent, and
its floor is a *drain* check between tenants, not an allocator.

**Sequential, after `sd-cli` exits — rejected on wall-clock.** It means a second governor
acquire: `scripts/gpu-governor.sh` polls at 1 s intervals for compute-context VRAM below
`DRAIN_FLOOR_MIB=1024` (it was 1500 against a whole-card reading until R-171; see
`.claude/HANDOVER.md` §0a-sexies)
with `DRAIN_TIMEOUT_S=60` and `ACQUIRE_TIMEOUT_S=300`. So the sticker path would add a second
drain wait — measured in seconds, bounded at 60 — to an 11.2 s render, to accelerate a step
whose CPU version is projected at ~1 s. That is a straight loss, and it makes the surface a
third tenant in a queue that already serialises chat against image.

**And the runtime does not exist here.** `onnxruntime-gpu-1.28.0` is a **249.8 MB** wheel
(measured) needing a CUDA 12 + cuDNN 9 runtime; the serving interpreter has neither, and the
only CUDA-capable venv is `training/.venv` (torch cu128), which is the fine-tune environment
and must not become a serving dependency — HANDOVER's rule that `train` is never evicted for a
page view cuts both ways.

**Conclusion: no GPU segmentation.** Not "later, maybe" — the arithmetic says a ~1 s CPU step
is cheaper than the lock transition alone.

### 3.4 Option D — SAM / interactive segmentation (rejected for this surface)

SAM needs a prompt: a point, a box, or a mask. There is no user in the loop on a
generate-and-return endpoint, and inventing one ("assume the subject is centred") is just a
worse version of the centre-crop heuristic Option A already gets for free from the chroma
field. SAM ViT-B is ~375 MB and ViT-H ~2.4 GB (vendor, not verified here — no SAM weights
exist on this box). If an interactive "refine this edge" feature is ever wanted **in the
iPhone app**, iOS 17+ ships `VNGenerateForegroundInstanceMaskRequest` on-device, which is
free, private and does not touch this server. That is the right home for interactivity, and it
is worth noting for the app design even though it is out of scope here.

### 3.5 One thing `sd-cli` can already do, and one thing it cannot

Read from `sd-cli --help` on the built binary:

- It **can** take `-i/--init-img` and `--mask` (inpainting), has `-M adetailer` with a YOLOv8
  detection model, `--canny`, `--control-net`, and `--max-vram`. So a mask can be fed *in*.
- It **cannot** emit one. There is no alpha, RGBA or transparency output option. ADetailer
  detects *regions to re-render*, not a matte, and it would need its own YOLO weights.

So the engine confirms the shape of the problem: FLUX gives you three channels and the fourth
is entirely ours to make.

### 3.6 Recommendation

**Ship Option A (chroma field + non-ML key). Keep Option B (rembg u2net/isnet on CPU, in its
own venv behind a subprocess) specified and ready as the fallback, selected by measurement,
not by taste.**

The argument that wins it is not speed, it is the dependency boundary: **Option A adds zero
packages to the serving interpreter**, and CLAUDE.md's deny rules make any addition there the
expensive option by policy. The 25 ms matte is a bonus.

The recommendation is **conditional on §7.1**. If the chroma key passes on fewer than roughly
four renders in five, Option B is correct and the extra ~190 MB and one subprocess boundary are
worth paying. A hybrid is also legitimate and probably where this lands in practice: key first,
and fall through to the ML matte when the keyed alpha looks degenerate (subject area outside a
sane band, or the mask touching all four borders) — that check is a handful of numpy lines and
it turns the fallback into an automatic one.

**One correction to a tempting argument.** RavenCalc is the precedent for *staying off the
lock*, and it applies here, but not as "the matte overlaps the render" — the matte is strictly
serial after its own render and cannot overlap it. The correct, narrower claim is: **the matte
runs outside `async with gpu.hold("image")`, so it does not extend the lock hold and the next
tenant gets the card sooner.** `prune_gallery` in the existing `/api/image` handler is already
exactly that shape — after the hold, via `asyncio.to_thread` — and the matte must copy it. In
a thread, not on the event loop: 25–130 ms of numpy on the loop stalls the console WebSocket
pushes, and the rack's "pushed live over one socket" claim is a thing this repo has already had
to defend once.

---

## 4. Prompt construction

Fixed suffix appended to the user's subject, not exposed as a free-form field:

> `, sticker illustration, single subject, centred, thick clean outline, flat vector shading,
> no background, no shadow, isolated on a solid flat magenta #FF00FF background, no gradient,
> no text`

Notes that are not decoration:

- **"no background" alone does not work.** Diffusion models have no concept of absence; they
  render *something*. Naming a specific flat colour gives the key something to find, which is
  the entire reason Option A is viable.
- **"no shadow"** matters more than it looks. A contact shadow is semi-transparent grey over
  the field and keys out as a grey smear attached to the subject.
- The existing `denied()` filter (the child-term ∩ sexual-term intersection) applies unchanged —
  it is a property of the prompt, not of the surface.
- The suffix is a **product decision, and it belongs to the site's honesty rules**: if the page
  ever says "your prompt, unmodified", it is lying. The page should say the surface constrains
  the prompt, and ideally show the suffix.

---

## 5. Pipeline

### 5.1 Steps

1. Validate and compose the prompt (§4).
2. `gpu.hold("sigil")` → run `sd-cli` with the image surface's proven flags
   (`--cfg-scale 1.0`, `--sampling-method euler`, `--steps 4`, `--backend te=cpu`,
   `--diffusion-fa`), `-W/-H` at the render canvas, seed from `secrets` — **not** the clock;
   `/api/image` has the scar tissue and the comment explaining why.
3. Release the hold. **Everything below is outside it.**
4. Matte in a worker thread: key → fill → border-connect → despill → feather → crop.
5. Resize to the delivery canvas, encode RGBA PNG with provenance in `tEXt` (§5.6).
6. Prune (§6.2), return JSON.

### 5.2 Canvas — decided by measurement, not by preference

**Apple's constraint:** each Messages sticker may not exceed **500 KB** (vendor — Apple's
Human Interface Guidelines, messaging extensions). A maximum dimension of **618×618**, with
408×408 typical, is also widely cited — but the source found for that one was an Apple
Developer Forums thread, not the HIG itself, so it is **unconfirmed and must be verified
against Apple's current guidance before it is relied on.** It is flagged rather than quietly
labelled `vendor` because the canvas decision below rests on it, and a forum paraphrase dressed
as a specification is exactly the error this project's labelling rules exist to catch. The
500 KB figure is solid; the pixel cap needs one check.

**Measured here, on six real renders with a synthesised subject matte:**

| Canvas | Median RGBA PNG | Range |
|---|---|---|
| 768×768 | **298 KiB** | 218–512 KiB |
| 512×512 | **150 KiB** | 109–249 KiB |

768 is over Apple's 618-pixel maximum, and one of six samples already exceeded 500 KB at that
size. 512 fits the dimension cap, halves the bytes, and is a multiple of 64 — which
`ImageRequest.size` documents as a hard requirement (the VAE downsamples by 8 and the
transformer patches by 2).

**So: render at 768, deliver at 512.** The downsample costs a measured 7.1 ms and buys edge
quality — a matte computed at 768 and reduced is cleaner than one computed at 512. These
figures used a large opaque subject (~62% of the frame); a real sticker has more transparent
area and will compress better, so treat them as an upper bound. Confirm on real stickers
(§7.4) before publishing a byte figure.

### 5.3 One flag to re-examine

`/api/image` passes `--vae-tiling`, added because a 768 render died in VAE decode without it.
Tiled decode can leave faint seams — and a *flat keyable background* is precisely where a
threshold goes ragged along a seam. At 512, tiling may not be needed at all. **Test both ways
at the sticker canvas** (§7.6). This interaction is invisible on ordinary renders and would be
found late and blamed on the matte.

### 5.4 Governor surface name — and the second job that name has

Register `sigil` as its own governor surface rather than reusing `image`. The log line, the
queue-depth accounting and the rack's "who has the card" display all key off the name, and
merging them makes the surface invisible in exactly the readout the site is built to be honest
about. This is the *opposite* of the ASIC-vs-GPU-miner conflation HANDOVER §5 item 8 warns
against, and for the same reason.

**But a surface name in this governor is not only a label — it is a `case` in `evict()`,** and
that changes what registering one costs. Read from `scripts/gpu-governor.sh`:

```sh
case "$prev" in
  chat)  … _stop-chat  || pkill -f 'llama-server' ;;
  image) pkill -f 'sd-cli' ;;
  train) … REFUSING to evict a training run … ;;
  miner) … cryptominer.stop() … ;;
  *)     pkill -f 'llama-server|sd-cli' ;;
esac
```

Three consequences, none of them obvious:

- An unregistered `sigil` falls to `*)`, which pkills `llama-server|sd-cli`. That happens to
  stop a sigil render — but it also kills chat as collateral, and the `miner)` comment in that
  file exists precisely because someone already found the `*)` arm logging a successful
  eviction while the real tenant kept the card. **Add an explicit `sigil) pkill -f 'sd-cli'`
  case in the same commit that starts writing `sigil` into `run/resident`.**
- `sigil` and `image` share one process pattern. `pkill -f 'sd-cli'` cannot tell them apart, so
  evicting one kills the other. In practice the global lock serialises them and `sd-cli` is not
  resident between jobs, so the window is small — but it is a case this governor has never had,
  and it should be written down rather than discovered.
- Registering a name without the `case` is the same class of split contract as CLAUDE.md's
  BEGIN/END markers: two files have to change together or the mechanism silently half-works.

### 5.5 Where output lands

`backend/output/`, served by `GET /api/gen/<name>` — never `site/`. See §6.1 and §6.2 for the
two traps in doing that naively.

### 5.6 The watermark, resolved rather than merely forbidden

HANDOVER §5 item 13 says `tools/build/build_gallery.py`'s bar must not be applied. Mechanically that
is already true — `build_gallery.py` is a separate script for homepage art and never touches
`/api/image` output — so the real instruction is: **do not reuse `stamp()`, and do not let a
later change add a caption pass to this surface.**

But the bar exists for a reason the honesty rules care about: it prints the model, the size and
the seed, so a picture carries how it was made. Burning that into a sticker defaces it.
Replace it, do not drop it:

- **The JSON response carries the provenance** — model, seed, steps, canvas, seconds — exactly
  as `ImageResult` already does. That is the primary record.
- **PNG `tEXt` chunks** via PIL's `PngInfo` embed the same fields in the file itself, so a
  sticker saved to a phone still knows what made it, with zero visible pixels changed.

Write that down in the code with the reason, or someone re-adds the bar for consistency.

---

## 6. API contract — this is for an iPhone app, not for this website

Both item 12 (Voice) and item 13 are for an app Garrett intends to build against this server,
which is a constraint on the API that lands **before** any UI work. Three traps are specific
and each would be found by a user rather than by a test.

### 6.1 The `/api/gen/{name}` regex will 404 every sticker

```python
if not re.fullmatch(r"gen-\d{13}-\d{1,10}\.png", name):
    raise HTTPException(404, "No such render.")
```

`name` is attacker-controlled and lands in a filesystem path, so the exact-shape match is
correct and must stay. But it means **a `sticker-…` prefix 404s on every single request until
that regex is widened in the same commit.** This is the same class of contract break as
CLAUDE.md's BEGIN/END marker rule. Two acceptable resolutions:

- keep emitting the `gen-` prefix and let stickers be indistinguishable by URL; or
- widen to `(?:gen|sigil)-\d{13}-\d{1,10}\.png` **in the same change** that starts emitting the
  new prefix.

Either is fine. Silently picking a new prefix is not.

### 6.2 `prune_gallery` will delete a user's saved sticker

`prune_gallery(keep=60)` globs `RENDERS/gen-*.png` and unlinks everything past the newest 60.
It exists for a good reason — a public endpoint producing ~800 KB per request fills a disk
quietly. But an app that shows a *sticker library* is a different contract from a website that
shows the last render: an image and a sticker sharing one directory evict each other, and a URL
the phone cached goes 404 for reasons the user experiences as data loss.

Pick one and write it down:

- **`backend/output/sigils/` with its own keep count** (and a prune that does not glob across
  both), or
- **the app downloads the bytes on receipt and the server URL is explicitly ephemeral** — in
  which case the JSON must say so, and the app must not be built assuming otherwise.

The second is simpler and is probably right for a first version; it is only right if it is
stated in the contract rather than discovered.

### 6.3 Rate limiting already keys on the right thing

Checked, because it is the discriminating detail for a non-browser client:

```python
def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")
```

It reads `X-Forwarded-For` first, so behind Caddy each phone gets its own bucket rather than
every user sharing Caddy's socket peer. **No change needed there** — though phones on a shared
carrier NAT can still collide, and the 429 message currently advertises RavenCalc as the less
restricted alternative, which is nonsense to an app that only wants stickers.

**The part that is not a nicety: an unregistered surface is not rate limited at all.**

```python
pair = _limiters.get(surface)
if pair is None:            # unmetered by configuration -- the default now
    return True
```

`throttled_for("sigil")` with no `sigil` in `LIMITS` returns `True` for every request — it
**fails open**, on a public image-generation endpoint reachable from a phone app, and it does
so while the code reads as if it were throttled. That is the same failure mode as HANDOVER §5
item 1's fail-open DRM, which that file calls "the most serious item here."

Two things are needed, not one: the name must be added to `_RATE_SUGGESTED` (`LIMITS` is built
by iterating it), **and** `SYMONEURAL_RATE_SIGIL=<per-min>/<per-hour>` must actually be set, because
`_rate_for` returns `(0, 0)` — no bucket — when the environment variable is unset. Every
surface is currently unmetered by that route, deliberately; a public app endpoint is the case
where that default should be reconsidered rather than inherited.

### 6.4 Contract shape

```
POST /api/sigil
  { "prompt": str, "seed": int|null, "steps": int=4 }
->{ "schema": "sigil/result/v1",
    "url": "/api/gen/<name>", "seconds": float, "matte_seconds": float,
    "seed": int, "steps": int,
    "render_size": int,        // canvas FLUX drew at        (768)
    "delivered_size": int,     // canvas in the returned PNG (512)
    "model": "FLUX.1-schnell q4_k", "bytes": int,
    "matte": "chroma"|"u2net",
    "transparent_fraction": float }   // measured share of non-opaque pixels
```

`size` is deliberately **not** a field: the pipeline has two canvases (§5.2) and one ambiguous
name for them is how a client ends up scaling by the wrong number. `transparent_fraction`
replaces a constant `"alpha": true`, which would carry no information — as a real measurement
it is also the value the §7 test assertion checks, so the client and the test agree on what
"has an alpha channel" means.

Rules that make it usable by something that is not this site:

- **No session, no cookie, no CSRF, no referer check.** Every field the client needs is in the
  response body; nothing is inferred from browser state.
- **Absolute-path URL, one origin.** The app resolves it against the same host it posted to.
- **Additive versioning.** New fields may be added; existing field names and types do not
  change meaning. RavenCalc's `ravencalc/result/v1` schema tag is the precedent worth copying —
  put a `"schema": "sigil/result/v1"` in the response and the app can branch on it forever.
- **`matte` and `matte_seconds` are in the contract deliberately.** They say which path
  produced the alpha. That is the honesty rule applied to an API: a client should be able to
  tell a keyed sticker from a segmented one.
- Errors stay as they are: a 429 with a real reason, a 503 when weights are missing, a 500 when
  the render fails. An app can render those; it cannot render an HTML error page.

### 6.5 Authentication — a straight answer, per the task

`/api/chat` and `/api/image` are open to whatever reaches the origin, protected only by rate
limits. For a public phone app that is the same exposure with a much bigger audience.

The pattern already in this repo is `backend/apps/asicminer/__init__.py`: `SYMONEURAL_ASIC_ENABLED=1`
plus `SYMONEURAL_ASIC_TOKEN`, presented in `X-Symoneural-Token`, compared with `hmac.compare_digest`, and the
surface 503s with both unset — a misconfiguration fails **closed**. Copy that shape:
`SYMONEURAL_SIGIL_ENABLED` + `SYMONEURAL_SIGIL_TOKEN`.

**And state its limit honestly, because the difference matters.** asicminer is an *operator*
surface — one operator, one token, off by default. This is a *consumer* surface. **A shared
token compiled into an iPhone app is extractable** — anyone with the IPA and ten minutes has
it. So the token gates *who can call the endpoint at all* and stops casual drive-by use of a
public URL; it is **not** per-user authentication and the spec must not describe it as
security. If per-user identity is ever needed (quotas, a paid tier, abuse attribution), that is
real auth — device attestation or accounts — and it is a separate decision that should be taken
deliberately rather than grown out of a shared secret. Rate limiting by `X-Forwarded-For`
(§6.3) remains the actual abuse control either way.

---

## 7. What must be MEASURED here before any figure about this is published

In priority order. The first one decides the design.

1. **Chroma-key pass rate on real FLUX output.** Generate n ≈ 20–30 stickers across subject
   types — animal, object, person, text-heavy, dark subject, light subject, thin/spindly
   subject — and count the fraction whose keyed alpha needs no manual fixing. This is the
   number that chooses Option A over Option B and it **could not be measured in this session**:
   the card was contended and the task forbade generation. Until it exists, §3.6 is a
   recommendation resting on an argument, not on a result, and nothing about matte quality may
   appear on the site.

   **Run it over at least two key colours — magenta and green — on the same prompts and the
   same seeds.** Otherwise the experiment cannot distinguish "chroma keying fails here" from
   "magenta fails here", and those have opposite consequences. Green is the film industry's
   default precisely because it is far from skin and warm tones; magenta sits close to pink
   noses, tongues, lips and anything purple. A colour-specific failure is a one-word prompt
   fix; reading it as a mandate would buy ~190 MB of ONNX and a subprocess boundary for
   nothing.
2. **Sticker render seconds at the chosen canvas**, measured — never scaled from the 11.2 s
   768×768 figure. A 512 render is not 11.2 × (512/768)²; step count, attention and tiling do
   not scale that way.
3. **Complete matte wall-clock on real renders**, including despill and crop, which are not in
   the 25 ms figure.
4. **Final PNG bytes on real stickers**, against Apple's 500 KB cap. The 150 KiB median here
   used a synthesised opaque matte and is an upper bound.
5. **If Option B: u2netp / u2net / isnet CPU seconds at 320×320 on this i9.** Currently
   unmeasured. It must not be published as a projection, and the site's labelling rule means it
   cannot be published at all until it is run.
6. **`--vae-tiling` on and off at the sticker canvas** — seams, and whether the render survives
   without it at 512.
7. **Governor behaviour with a third surface name** — that `sigil` and `image` interleave
   without a spurious eviction, read from `run/governor.log`.

Add a `tests/frontend.mjs` assertion when this is built, per CLAUDE.md: **that the returned PNG
actually decodes *and has a non-opaque alpha channel*.** The existing image assertion exists
because a render succeeded server-side and still showed as a broken image to every visitor;
the sticker equivalent of that failure is a PNG that decodes perfectly and is a solid magenta
square, which curl and a naive decode test would both call a pass.

---

## 8. The name — alternatives, each with a collision check

Garrett's criterion was a name other companies are not using. Checked by search, 2026-08-17:

| Candidate | Already a well-known tech product? |
|---|---|
| **Sigils** (working name, recommended) | **Partly.** *Sigil* is an established open-source EPUB editor (sigil-ebook.com), and "sigil" is standard Perl/Ruby jargon for the `$`/`@` prefix. The plural plus the SyMoNeuRaL prefix separates it, and neither collision is in this market — but a developer audience hears the jargon first. |
| **Wards** (the runner-up he was offered) | **Weakly, and awkwardly.** Several small open-source *server dashboards* are called Ward (Rudolf-Barbu/Ward, AntonyLeons/Ward, ward-rs). Minor as a trademark matter; bad as positioning, because server monitoring is this repo's *other* product line — the rack. |
| **Decals** | **No collision found.** No software product named Decal; "decal" is the ordinary industry word for a die-cut sticker, which makes it descriptive and instantly understood, if less distinctive than Sigils. Cleanest of the four. |
| **Marks** | Not searched; flagged as too generic to be defensible and likely to collide with everything. Listed only so nobody proposes it as new. |

Checked and **rejected**, so they are not re-proposed:

- **Glyphs** — *Glyphs* is the professional macOS font editor (glyphsapp.com). Hard no.
- **Charms** — *Charm* (charm.sh / charmbracelet) is a well-known CLI/TUI ecosystem; "charms"
  are also Canonical's Juju packaging unit. Hard no.
- **Runes** — *Runes* is Casey Rodarmor's Bitcoin fungible-token protocol. Doubly bad here,
  since this repo already has a Ravencoin miner surface and the collision would be read as a
  crypto claim.
- **Cutouts** — cutout.pro is a well-known AI background-removal SaaS; naming our background-
  removal feature after a direct competitor is the worst option in the list.

**Recommendation: Sigils, with Decals as the fallback if the EPUB editor bothers him.** He has
not confirmed either. Nothing in this spec depends on the answer except identifier naming, and
§1 says how that is changed in one pass.

---

## 9. Open decisions for Garrett

1. **The name** (§1, §8).
2. **Do stickers persist?** §6.2 — own directory with its own retention, or explicitly
   ephemeral URLs with the app saving bytes on receipt.
3. **Is the surface public or token-gated at launch?** §6.5 — and, given that a token in an app
   is extractable, whether per-user identity is wanted eventually or never.
4. **Does this get a page on the site, or is it API-only for the app?** A page means a rack
   unit, a generator, and the CSS collision discipline; API-only means none of that and is the
   smaller first step.

## 10. What was NOT done here

No GPU work, no renders generated, no packages installed, no code written, no files changed.
The only new file is this one. `training/` was not read, opened or referenced — `corpus.jsonl`
and `build_dataset.py` are out of scope for this surface in every direction, and a sticker
pipeline has no reason to touch either.
