# frontend/desktop-search — Alt+Space, type a surface name, the surface opens

Desktop search for the rack. One process answers two interfaces:

| Interface | Desktop | Answers on this box |
|---|---|---|
| `org.kde.krunner1` | KDE Plasma | **yes** — the session here is Plasma 6.3.6 |
| `org.gnome.Shell.SearchProvider2` | GNOME Shell | no — `gnome-shell` is not installed |

Both read `rack.py`, which reads `backend/registry/ROSTER.md` and `ops/PORTS.tsv`.
**There is no second copy of the surface list.** Add a row to the roster and it is
searchable on the next keystroke — no restart, no edit here.

## Install

```bash
./install.sh                # detects the desktop, installs only what it can use
kquitapp6 krunner           # pick it up now instead of at next login
```

Everything lands under `$HOME`. `./install.sh --remove` takes it back out.

## Verify without a desktop

```bash
./search.py --once chat     # chat  gpu  http://127.0.0.1:8800/chat.html
./search.py --once gpu      # the six GPU surfaces
./search.py --once zzzz     # "no surface matches" and exit 1
```

Measured 2026-09-11: twelve roster rows, all resolving to `symoneural-api` on
8800. `gpu` returns chat, image, miner, remix, sigils, studio.

## Why it is shaped this way

- **D-Bus activated, and it exits.** Nothing runs at boot for a feature nobody
  has searched with yet; two idle minutes and the process is gone. The desktop
  starts it again on the next keystroke.
- **Both interfaces, one process.** The GNOME half is twenty lines over the same
  data layer. A search provider that exists for only one desktop is the kind of
  thing found missing at the worst moment, and `install.sh` refuses to install
  the GNOME half when `gnome-shell` is absent, so it costs nothing here.
- **`Run` re-resolves the id.** KRunner hands back the id it was given at match
  time. The roster could have been edited in between, and an id that no longer
  exists must open nothing rather than something stale.
- **A malformed roster row raises.** It is not skipped. A surface silently
  missing from search looks exactly like a surface nobody ever added.
- **No credential anywhere.** These are loopback URLs to Garrett's own surfaces.
  Nothing here asks for a token and nothing here may grow one.

## Files

| File | What it is |
|---|---|
| `rack.py` | the roster and port table, parsed; `search(query)` lives here |
| `krunner.py` | the `org.kde.krunner1` interface |
| `gnomeshell.py` | the `org.gnome.Shell.SearchProvider2` interface |
| `search.py` | owns the bus name, exports both, idles out; `--once` for testing |
| `install.sh` | per-desktop install, all under `$HOME` |

Tests are `tests/desktop/test_desktop_search.py`. They exercise the D-Bus
handlers directly with a fake opener, so they need no desktop and no browser.
