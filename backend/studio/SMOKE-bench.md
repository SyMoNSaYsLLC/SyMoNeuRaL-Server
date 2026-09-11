# The bench gets the window — smoke record

Written after running it. Every figure below was measured on this box on **2026-08-21**, in real
Chrome via `tests/browser.mjs` (`channel: 'chrome'` — no browser was downloaded), against **my
own API on a spare port**, never the service:

```
bash scripts/symoneural-ui.sh start                       # loopback :8188, no lock held
cd backend && SYMONEURAL_STUDIO_ENABLED=1 SYMONEURAL_STUDIO_TOKEN=devtest \
    python3 -m uvicorn server:app --port 8876
SYMONEURAL_STUDIO_TOKEN=devtest node tests/studio.mjs http://127.0.0.1:8876
```

The check on this work is `exists backend/apps/studio/SMOKE-bench.md`, for the reason
`SMOKE-cleanroom.md` states: `exists`, `grep` and `ngrep` ask what is written on disk and none of
them can ask whether the thing works. This defect is the strongest example of that in the repo's
history — **every check on the Studio task was green, `tests/studio.mjs` was 16/16, and the
editor those checks were about had never been seen by the person who asked for it.**

## The defect

`/studio/editor/` was already a complete, working reverse proxy of ComfyUI's own frontend
(`comfyui_frontend_package 1.49.6`) on our origin. Nothing was broken. The page was the bug:

| | before | after |
|---|---|---|
| position in `#studio` | 4th block — after the gate, status strip and both panels | 2nd — straight after the gate |
| frame CSS | `height:min(78vh,760px)` | `height:calc(100vh - 150px);min-height:520px` |
| frame top at 1440×1000 | **y = 962** | y = 449 |
| visible inside the first viewport | **38 px of 1000 — 4 %** | 551 px of 1000 — **55 %** |

A node canvas is the one surface on this site that is unusable at part size: the palette, the
minimap and the properties rail are all edge-anchored, so they overlap each other before they
overflow. At 4 % of the viewport the operator saw one line of tab bar, and only after scrolling
past two panels to find it.

## What was measured, at three viewports

`Expand` toggles `st-wide` on `.st-bench` — `position:fixed;inset:0`. `inset:0` rather than
`100vw/100vh` because `100vw` counts the scrollbar and would open a horizontal one on the way to
going full-screen. Confirmed: **no horizontal overflow at any of the three.**

| viewport | frame in flow | expanded | covers | `body.overflow` | Escape |
|---|---|---|---|---|---|
| 1600 × 1000 | 850 px at y=451 | 1580 × 933 | 93 % | `hidden` | → `static` |
| 1301 × 740 | 590 px at y=449 | 1281 × 675 | 91 % | `hidden` | → `static` |
| 390 × 844 | 694 px at y=713 | 370 × 697 | 83 % | `hidden` | → `static` |

1301×740 is in the table because it is the binding viewport for the one-screen budget elsewhere
in this repo (`.claude/HANDOVER.md` §0). 390×844 is a phone: the head row wraps to three lines
there, which is why the in-flow top is 713 rather than 449 — it wraps, it does not truncate.

**Nothing was reparented.** `st-wide` is a class on `.st-bench` itself, because
`body.appendChild(bench)` would reload the iframe's document and throw away the graph the
operator was editing — the same argument as `mountBench`'s never-remount guard, from the other
side. Asserted: the `src` attribute is byte-identical before and after expanding.

**Escape gets out.** A fixed panel covers the site header, so without it there is nothing left to
click. The listener is on `document` and the button stays visible while wide, because focus is
usually inside the iframe and the keydown never reaches this document at all.

## Nothing was dropped to make room

The five-line bench description moved into a `<details>` at the bottom of the block with every
word intact — it carries the upstream attribution (`its editor, not a copy of it`) and the reason
a render queued there cannot lock out chat, and `.claude/CLAUDE.md` bars trimming content to fit.
The one-line attribution stays visible above the frame at all times, expanded included. The
status strip, both panels and the tool table are all still on the page, below the bench.
`grep -c text-overflow page.html` returns **1** — the comment promising there is no ellipsis
rule — and `build_studio.py` asserts against the comment-stripped page, so that 1 is the promise
and not a rule.

## The suite

**21/21 passed**, measured 2026-08-21 at the commit this file lands in, including a real
**1024 × 1024** FLUX-schnell render decoding in the browser in **11.4 s** (10.3 s server-side,
lock released). It was 16/16 before; the five new assertions are the four geometry ones above
plus the remount check.

Two failures found on the way there were **not** caused by this work, and both are recorded
because they are the more useful half of the run:

1. **`26 tools` was stale.** `23f2f64` added `extract_spec` and `generate_native_code` (group
   `cleanroom`), updated `test_studio.py`'s `EXPECTED_TOOLS`, and did not touch `tests/studio.mjs`
   — so this suite reported two failures for work that was correct. Now 28, in both places.
2. **`the render decoded in the browser` was racy.** It waited on
   `waitForSelector('#st-shots img')`, which returns the moment `page.js` sets `src` — before a
   byte has arrived. `naturalWidth` is 0 until the PNG decodes, so a good render read `0x0` and
   failed. Verified from the other end at the same moment: `curl` on
   `/api/studio/image?filename=studio_00001_.png&subfolder=symoneural&type=output` answered
   `200 image/png content-length: 996780`. Now waits on `complete && naturalWidth > 0`.
   That assertion exists because a render once succeeded server-side and still showed as a broken
   image to every visitor, so it has to go red for that and nothing else — a racy version of it
   is worse than not having it.

## The deliberate break

Per `.claude/CLAUDE.md`: a test that passes before and after the change tested nothing.
`#studio .st-bench{margin:0 0 18px}` → `margin:1200px 0 18px`, rebuilt, re-measured:

```
top=962 visible=38px of 1000 = 4%   =>  FAIL      # and 962 is the original bug's own number
top=449 visible=551px of 1000 = 55% =>  PASS      # restored
```

Note **what** is asserted: the frame's area inside the first viewport, not its height. The old
`min(78vh,760px)` is 76 % of a 1000 px viewport, so a height assertion would have passed
throughout the entire period the editor was invisible.

## Two things that are true and are not defects

- **The three `net::ERR_ABORTED` lines** (`user.css` ×2, `comfy.templates.json`) are labelled
  optional by the suite and 404 identically direct to `127.0.0.1:8188`. Verified again here,
  along with `api/userdata?dir=workflows`, `api/userdata?dir=subgraphs` and
  `api/userdata/workflows%2F.index.json`: **the proxy is faithful** — every one of those is a
  404 upstream too, for files ComfyUI has never created.
- **The editor's Workflows panel reads "No workflows found."** That is accurate:
  `engines/symoneural-ui/user/default/workflows/` is empty. Our own `flux-schnell` lives in
  `apps/studio/workflows.py` in ComfyUI's **prompt** format (`{"1": {"class_type": …}}`), and the
  panel reads the **graph** format (nodes, links, positions) from that directory. Two different
  shapes, so it is a conversion nobody has written, not a broken panel. Every other rail item was
  clicked and returned real content: Node Library 29 rows, Model Library 58, Templates 488, Assets
  and Apps their own honest empty states.
