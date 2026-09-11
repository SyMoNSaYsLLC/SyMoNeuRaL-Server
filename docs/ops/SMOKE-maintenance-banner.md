# SMOKE — maintenance banner, run against the live site

**Run 2026-08-26, 08:33–08:36 EDT, at `c3be92b9`, against `https://symoneural.com` — not
against a local port and not against the working tree.**

This file exists because #107 read **100% while the banner existed only in the repository**.
Its four `exists`/`grep` checks all passed on files in the working tree, and the working tree
is not the webroot: `scripts/deploy.sh` copies `site/` into `/var/www/symoneural`, and until it
runs a visitor sees the previous `ui.js`. With `archive_tasks.py` on a two-minute timer, the
task was inside two minutes of filing itself as done with a banner nobody could see.

## The deploy actually happened

Production serves **`/yocto/Symoneural`**, not `/home/google/Symoneural` —
`symoneural-api.service` and `symoneural-deploy.service` both carry
`WorkingDirectory=/yocto/Symoneural`, and the deploy unit is **enabled**, so it re-publishes
that checkout at every boot. Deploying from the wrong checkout would therefore have looked
correct until the next reboot silently reverted it.

    git -C /yocto/Symoneural merge --ff-only   7d1a5529 -> c3be92b9   28 files changed
    sudo bash /yocto/Symoneural/scripts/deploy.sh
    cmp /var/www/symoneural/ui.js /yocto/Symoneural/site/ui.js     -> identical

    curl -s https://symoneural.com/ui.js | grep -c "Maintenance banner"   -> 2
    curl -s https://symoneural.com/livestack | grep -o 'ui\.js?v=[a-z0-9]*'
                                                                  -> ui.js?v=9972072f21

The cache-bust stamp is not decoration: Caddy sets `Cache-Control: max-age=604800` on `*.js`,
so an unstamped `ui.js` change is invisible for a week. `tools/build_cachebust.py` was run
twice — 335 asset links across 26 pages, second run byte-identical.

## It renders — proved in a real browser, not by grep

The banner is injected by JavaScript. `curl` can fetch `ui.js` and prove the *code* shipped;
it cannot prove a `.maint` element ever appears. Driven with the repo's own harness
(`tests/browser.mjs`, system Chrome, 1440×900) against the live HTTPS site:

| page | `.maint` present | expected |
|---|---|---|
| `/livestack` | yes | yes |
| `/chat.html` | yes | yes |
| `/miner.html` | yes | yes |
| `/overview` | **no** | no |
| `/ravencalc.html` | **no** | no |
| `/index.html` | **no** | no |

Rendered text: *"Down for maintenance. This surface is not being attended to right now, so
treat anything it shows as stale. The rest of the site still works. Nothing here is lost — it
is paused."* Screenshot: `/home/google/.claude/jobs/9ca96a2e/tmp/livestack-banner.png`.

The three negatives matter as much as the three positives. `/ravencalc.html` reads `ready` on
the rack and works; a banner there would be a false claim in the other direction.

## The customer surface is clean, two independent ways

- `/demo/dispatchos` and `/share-dispatchos.html` are **not on the list**.
- Neither page loads `ui.js` at all, so the banner cannot reach them even if the list were
  wrong. `curl -s .../share-dispatchos.html | grep -c ui.js` → **0**.

Both are asserted by `backend/apps/test_maintenance_banner.py`, because the second one stays
true only until somebody adds a script tag.

## The tests were sabotaged on purpose before being believed

Four mutations, each applied, each caught, each reverted:

| mutation | caught by |
|---|---|
| add `/demo/dispatchos` to the list | `test_dispatch_never_carries_the_banner` |
| add `/ravencalc.html` (reads `ready`) to the list | `test_no_ready_surface_is_labelled_down` |
| delete a row from `MAINTENANCE-SURFACES.md` | `test_list_matches_the_document` |
| empty the `DOWN` list entirely | `test_banner_exists` |

## Not proved here

- **No claim that the nine listed surfaces are still down.** The states were read at 08:23 on
  2026-08-26 and a banner outlives its reading. Re-run the `/api/status` command in
  `MAINTENANCE-SURFACES.md` before trusting the list.
- **Pre-existing and untouched**, verified against the pristine `/yocto/Symoneural` checkout
  before any of this landed: `test_brand_boundary` raises 3 collection errors
  (`ModuleNotFoundError: steps`), and `check_links.py` reports 3 broken links — `/studio` and
  `/livestack/live` are Caddy routes rather than files, so the link checker is wrong about
  them rather than the site being broken.
