# Surfaces under maintenance — the named list

**Written 2026-08-26.** Garrett, the same day: *"I do not care about any of the livestack apps
rn donnies site is getting 100% attention and 100% priority"*, *"Maintenance banner would be
great for the symoneural portion and we will be 100% powering dispatch through symoneural
domain"*, and, against a screenshot of the Live stack rack: *"all of these in image can be
taken off and maintenance banners up"*.

This file is the list. `site/ui.js` reads the same list and stamps the banner from it, and
`backend/apps/test_maintenance_banner.py` fails if the two disagree — so the list cannot be
changed in one place and left in the other.

## Why a list and not "everything except dispatch"

Because the honesty rule cuts both ways. This project's standing rule is that every LED and
gauge reflects a real reading; a banner is a much bigger claim than an LED, made in words, at
the top of the page. **A surface that answers requests correctly and is labelled down is as
false as a dead one labelled ready.** "Everything except dispatch" would put the banner over
RavenCalc, Coder, Project, Streamer and Live, which the rack showed as `READY` at 08:20 on
2026-08-26 — and a visitor who clicks one and finds it working has been told a lie by the
banner rather than reassured by it.

So the list names surfaces we have actually stopped attending to. It is short on purpose and it
is expected to be **deleted**, not grown.

## The list

Paths are matched exactly as `location.pathname`, with and without the `.html`, because the
site is reachable both ways (`/livestack` via `@sections` in `ops/Caddyfile`, and
`/livestack.html` off disk).

**Every state below was read from `GET https://symoneural.com/api/status` at 08:23 EDT on
2026-08-26**, not copied off the screenshot that prompted this file — the screenshot agreed
with the reading on all thirteen units, but a figure this file asserts should be one this file
took. Re-run that call before trusting the third column; a unit that has come back up and is
still listed here is exactly the false claim described above. Note the rack calls Reinforce
`train`, which is the id to look for in the JSON.

    curl -s https://symoneural.com/api/status \
      | python3 -c "import json,sys; [print(u['id'].ljust(12), u['state']) for u in json.load(sys.stdin)['units']]"

| path | surface | why it is on the list |
|---|---|---|
| `/miner.html` | Miner | `offline`; started by hand, and nobody is starting it this week |
| `/exp.html` | Exp | `queued` — waiting on a card nobody is attending, which is a wait with no end |

## Deliberately NOT on the list

- **`/demo/dispatchos`** — the customer application. This is the one that must never carry the
  banner, and it is the failure this list exists to prevent: Donnie is being sent that URL.
  It is also structurally safe rather than only listed as safe, because it is served by
  `backend/api.py` and does not load `site/ui.js` at all. The test asserts both.
- **`/share-dispatchos.html`** — the customer preview. Same reason. It does not load `ui.js`
  either.
- **`/overview`, `/controlboard`, `/receipts`, `/documentation.html`, `/training.html`,
  `/build.html`, `/account.html`, `/credits.html`** — these are documents and company pages,
  not surfaces. Nothing about them is degraded and a maintenance banner on the page that
  explains what the company does would cost a sale rather than set an expectation.
- **`/ravencalc.html`, `/coder.html`, `/project.html`, `/streamer.html`, `/live.html`,
  `/gateway.html`** — these read `READY` on the rack. They work. Do not label them down.

## Taking it down

Delete the row from the table here and the matching entry in `site/ui.js`, run the test, run
`python3 tools/build_cachebust.py` twice (the second run must be a no-op), and deploy. The
banner disappears with the row; there is no separate switch to remember, which is the point.
