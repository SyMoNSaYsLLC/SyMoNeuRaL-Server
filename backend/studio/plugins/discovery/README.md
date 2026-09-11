# Symon Say Discovery

Search to crawl to answer. A search API finds candidate URLs, a real browser renders and
extracts them, and an optional synthesis step turns the extracted pages into a cited answer.

    query --[search backend]--> URLs --[crawl queue]--> rendered pages
          --[extractor]--> structured text --[LLM, optional]--> cited answer

This is the engine Garrett asked for when he asked for the ticker: *"I want a live ticker like
this on the symoneural website but instead of sports live fed news… I believe we will need a
symoneural webscraping agent and web search agent to accomplish this."* `apps/news`
is a consumer of it, not a competitor to it.

## Half of it runs right now, and it tells you which half

| Path | State on this box, 2026-08-20 | Needs |
|---|---|---|
| `search`, `stats`, `export` | **working, no key needed** | `requests`, `bs4`, `lxml` — present |
| `discover`, `crawl`, `login` | raises with the install command | `playwright` + its chromium |
| `answer` | returns a string saying what is missing | `anthropic` + `ANTHROPIC_API_KEY` |

Measured, not asserted: `bin/symoneural-discovery stats` reads the interpreter and prints the
five dependency booleans. `search --backends duckduckgo` needs no credential at all and was
run end to end on 2026-08-20 — four results, exit 0.

Exit codes: `0` success · `1` the search returned nothing · `3` a dependency is missing (the
message is the install command, printed instead of a traceback) · `130` interrupted.

## Install

Nothing is installed and an agent may not install it: `python3` on this box is what
`symoneural-api` runs under, and `.claude/CLAUDE.md` forbids pip touching it. See
`symoneural-discovery.requirements.txt` for the four commands, and `GARRETT-INBOX.md`.

## Credentials

One env file per app, named after the app:

    cp symoneural-discovery.env.example symoneural-discovery.env
    # edit symoneural-discovery.env

`envfile.py` loads it automatically on every run — no `export` per session, and no
`python-dotenv` either, since that would be a new dependency to parse `KEY=value`. Anything
already set in the shell **wins** over the file, so a systemd unit's `EnvironmentFile=` is
never clobbered by a checkout.

`bin/symoneural-credentials` walks through obtaining the keys: it opens each provider's console
page, tells you what to click, and takes the paste. The login, the CAPTCHA and the MFA are
yours — nothing here automates proving you are a person, and nothing here reads a key out of an
already-authenticated page. Every one of these providers shows the raw key exactly once, at
creation, so there would be nothing to read even if it did.

Three files, one stem, differing only in role — Garrett's rule, so that
`symoneural-discovery.*` finds the whole set and a file seen in a diff says which app it
belongs to without its path:

    symoneural-discovery.env               the real one (gitignored, never tracked)
    symoneural-discovery.env.example       the template (tracked, every value empty)
    symoneural-discovery.requirements.txt  the deps
    symoneural-discovery.venv/             the venv, once Garrett creates it

The vendor-spelled names (`GOOGLE_CSE_API_KEY`, `ANTHROPIC_API_KEY`, `HF_TOKEN`) are kept as
the vendors spell them, because their own SDKs read those exact names. The app's own two knobs
take the house spelling: `SYMONEURAL_DISCOVERY_ENABLED`, `SYMONEURAL_DISCOVERY_TOKEN`.

**`BING_SEARCH_API_KEY` is unverified and may be unobtainable.** Microsoft retired the
standalone Bing Search APIs in mid-2025 in favour of "Grounding with Bing Search", scoped to
Azure AI Agent Service rather than a key you drop into a script. The `bing` backend still
speaks the classic `api.bing.microsoft.com` shape and nobody has authenticated against it from
here. If a new sign-up cannot produce a key for that endpoint, delete the class rather than
leave a `--backends` choice that cannot work.

## What it does not do

No CAPTCHA solving, no defeating bot-detection or fingerprinting, no paywall bypass, and no
scraping a search engine's own results page — the keyed backends are official APIs. If a target
is actively blocking automated access that is a signal to stop, not a gap to route around.

`robots.txt` is honoured by default, with a per-run `--ignore-robots` opt-out that exists so the
owner of the run makes that call rather than this tool making it for him. As of 2026-08-20 no
content filter, domain allow-list or query inspection is implemented — a deliberate pre-launch
state, not a cleared posture (request ledger R-98, held). The limits that do exist are the ones a crawler
needs in order to keep working: a per-domain delay and concurrency cap, bounded retries with
backoff, and a `User-Agent` that says who is calling and gives a human to write to.

## Not on the rack yet

`status()` is written and returns a valid `Unit` — but `href` is `/discovery.html`, which does
not exist. `apps/voice` is the precedent: *"A rack row pointing at a 404 is worse than no row."*
There is deliberately no `router` export and no `include_router` in `api.py`, and
`test_the_router_is_not_exported_while_the_page_does_not_exist` is what keeps the page and the
row moving together.

`status()` also does **not** report `degraded`, which is the honest word for this box.
`api.py`'s `Unit.state` is `Literal["ready", "busy", "queued", "offline"]`, and a fifth value is
a pydantic error when the rack is assembled rather than a nicer label. The distinction lives in
`detail` instead: `search only: playwright not installed`.

`bus` is `net`. Nothing in this package takes a GPU lease, which puts it with RavenCalc and
Voice — a crawl waits on somebody else's web server, not on this card.

## Layout

    __init__.py     enabled() · token_ok() · installed() · ready() · status()
    discovery.py    the whole tool: storage, backends, robots, throttle, crawl, synthesis, CLI
    envfile.py      the stdlib KEY=value loader
    credentials.py  the guided key-setup agent (bin/symoneural-credentials)

`../test_symoneuraldiscovery.py` is the suite, stdlib-only and collected by the ordinary
`pytest apps/` run. **Every third-party import in this package is lazy, and that is structural
rather than tidy.** A module-level `import playwright` on a box without playwright does not
fail one test — it aborts *collection*, which is `Interrupted: 2 errors` and no pass count at
all, and reads exactly like the suite was broken by whatever landed last.
`test_no_third_party_import_at_module_level` walks the AST and enforces it.
