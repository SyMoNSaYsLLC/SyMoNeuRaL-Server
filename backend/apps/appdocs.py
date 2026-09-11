"""Per-application documentation, scoped by ownership and read from the live router.

Every application on this box gets one canonical docs URL, `/docs/<id>`, and the global
platform reference stays at `/docs`. This module owns the registry that says which routes
belong to which application, and the renderer that turns that into a page.

## Why the routes are read from the router and never typed here

`/docs` already works this way and says why: *"Everything rendered comes from the schema
FastAPI already generates, so the reference cannot drift from the service."* A per-application
page has the same problem twice over -- it can drift from the service AND it can drift from
the ownership boundary -- so neither half is written down as prose. The registry carries
PREFIXES; the operation list is computed by walking `app.routes` at request time, exactly the
structure Starlette matches requests against. `apps/route_matrix.py` records what happens when
a route list is inferred instead of read: a "25 broken endpoints" report that was a bad test.

## Why leakage is a property and not a review item

The handshake requires that no application docs surface leaks routes owned by another
application. That is guaranteed here by construction rather than by inspection:

  * `OWNERS` maps each prefix to exactly one application id, so two applications cannot
    claim the same prefix -- `_check_registry()` raises at import if they do;
  * `owner_of()` picks the LONGEST matching prefix, so `/api/streamer/guide/*` resolves to
    the guide child of streamer and not to `/api/streamer` by accident;
  * a page renders `routes_for(id)`, which is `[r for r in router if owner_of(r) == id]`.

The set of routes on any two pages is therefore disjoint because it is a partition. The test
suite asserts the partition is total as well -- every `/api/*` route has an owner -- so a new
router mounted without an entry here is a red test rather than a route that quietly appears on
no documentation page at all.

## Roles

`audience` is the boundary the page mirrors, not a decoration. A route marked operator-only is
excluded from a customer-facing page entirely, because "documented but forbidden" reads to a
customer as an instruction they are failing to follow. `/demo/dispatchos/docs` is the case the
handshake names explicitly: it documents the customer surface for Donnie's role and must not
present operator actions as things he can do.
"""

from __future__ import annotations

import dataclasses
import html

from .ratelimits import prose as _limits   # published figures come from the
                                          # enforced table, never retyped



@dataclasses.dataclass(frozen=True)
class Application:
    """One documented application surface.

    `id` is the docs slug AND, where the surface is on the rack, the rack id -- deliberately
    the same string, so `/docs/train` documents the row `/api/status` calls `train`. `parent`
    is the application that owns this one; `runtime` is the functional runtime that executes
    its work. Those are different questions and were being answered with one word: Reinforce's
    parent is Studio and its runtime is `symoneural-studio`, while Streamer's parent is Live
    and its runtime is `symoneural-live`.
    """

    id: str
    label: str
    kind: str                     # application | child | platform | compatibility
    parent: str | None
    runtime: str
    page: str | None
    prefixes: tuple[str, ...]
    summary: str
    auth: str
    limits: str = ""
    operator_only: tuple[str, ...] = ()


# The functional runtimes, from the controlling architecture. Named here so a docs page can
# state its runtime owner without every entry repeating the prose.
#
# Two kinds, and mixing them with nothing to tell them apart is what let two wrong names
# survive. Corrected 2026-09-08:
#
#   `symoneural-image-engine` was in this set and is not a component -- it is an ALIAS,
#   recorded as such in COMPONENT-MAP.tsv's ALIASES column for `symoneural-diffuse`. An
#   earlier note here called it fictional, which overstated it; the accurate statement is
#   that an alias was being used where the component ID belongs, while the component ID
#   itself -- `symoneural-diffuse`, what `sigils/render.py:73` actually executes -- was
#   absent from this set entirely. So the validator would have REFUSED the real name and
#   did accept the nickname. A guard that rejects the truth is worse than no guard.
#
#   `symoneural-listen` was likewise absent, and `voice` therefore declared
#   `symoneural-llm` -- the language engine -- for a speech-recognition surface that runs
#   `symoneural-listen/build/bin/symoneural-listen` (`voice/asr.py:64`).
#
# Neither error broke anything, because this field is read by people and by /docs rather
# than by a loader. Both were found by reading the registry against the source.

#: Runtimes that are a process on disk, in their own top-level directory.
PROCESS_RUNTIMES = {
    "symoneural-llm": "language model serving on the RTX 5070 Ti",
    "symoneural-diffuse": "diffusion image generation on the RTX 5070 Ti",
    "symoneural-listen": "speech recognition, CPU only",
    "symoneural-miner": "mining control: GPU, ASIC and settlement",
}

#: Logical groupings of in-process modules. Real components in the architecture, but not a
#: separate process, so there is no directory to point at. Kept distinct from the set above
#: so a reader can tell which kind a name is, and so a typo cannot hide among them.
LOGICAL_RUNTIMES = {
    "symoneural-project": "project and CLI state, CPU only",
    "symoneural-ravencalc": "symbolic algebra, CPU only, never queues",
    "symoneural-studio": "graph and workflow orchestration, adapters and plugins",
    "symoneural-live": "streaming and broadcast I/O",
    "symoneural-platform": "the web, gateway and API chain itself",
}

RUNTIMES = {**PROCESS_RUNTIMES, **LOGICAL_RUNTIMES}


APPLICATIONS: tuple[Application, ...] = (
    # ---- symoneural-llm -----------------------------------------------------------------
    Application(
        id="chat", label="SyMoNeuRaL Chat", kind="application", parent=None,
        runtime="symoneural-llm", page="/chat.html", prefixes=("/api/chat",),
        summary="Streamed conversation with the model resident on the card. Takes the GPU "
                "lease; other GPU surfaces queue behind it.",
        auth="public", limits=_limits("chat")),
    Application(
        id="remix", label="SyMoNeuRaL Remix", kind="application", parent=None,
        runtime="symoneural-llm", page="/remix.html", prefixes=("/api/remix",),
        summary="Track and set generation. A client of the same language runtime as Chat, "
                "listed separately because an operator taking one offline must not take "
                "the other with it.",
        auth="public", limits=_limits("remix")),
    Application(
        id="coder", label="SyMoNeuRaL Coder", kind="application", parent=None,
        runtime="symoneural-llm", page="/livestack/coder", # `/local/coders` as well as `/local/coder`: the routes are plural
        # (`/local/coders/ask`, `/local/coders/sessions`, ...) and the declared
        # prefix was singular, so six real routes matched no owner. Both spellings
        # are kept because the singular form is the page path.
        prefixes=("/local/coder", "/local/coders"),
        summary="The local workspace agent: a browser terminal over this box's own tree.",
        auth="loopback only — every route below is refused to any caller that did not come "
             "from a process on this machine, and refused again if it carries proxy headers. "
             "There is no public audience for these paths and there is not meant to be.",
        limits="none; the surface is not reachable off-box."),
    Application(
        id="dispatchos", label="SyMoNeuRaL DispatchOS", kind="application", parent=None,
        runtime="symoneural-llm", page="/demo/dispatchos",
        prefixes=("/api/dispatchos",),
        summary="Booking, quoting, dispatch and customer messaging for a working "
                "operator/customer business surface.",
        auth="session cookie, HttpOnly and SameSite=Lax, plus the door in front of "
             "/demo/dispatchos. Two roles: customer and operator.",
        limits="login attempts are throttled per account and per address.",
        operator_only=("/api/dispatchos/bookings/{bid}/quote",
                       "/api/dispatchos/bookings/{bid}/advance",
                       "/api/dispatchos/bookings/{bid}/message",
                       "/api/dispatchos/rules",
                       "/api/dispatchos/drivers")),
    # ---- symoneural-image-engine --------------------------------------------------------
    Application(
        id="image", label="SyMoNeuRaL Image", kind="application", parent=None,
        runtime="symoneural-diffuse", page="/livestack/image",
        prefixes=("/api/image", "/api/gen"),
        summary="Diffusion rendering. `POST /api/image` queues a render and answers with a "
                "name; `GET /api/gen/<name>` serves the produced file.",
        auth="public", limits=_limits("image")),
    Application(
        id="sigils", label="SyMoNeuRaL Sigils", kind="application", parent=None,
        runtime="symoneural-diffuse", page="/sigils.html",
        prefixes=("/api/sigils",),
        summary="Sticker and sigil packs rendered from an image or from audio. Its own "
                "surface rather than a mode of Image, because it takes the card under its "
                "own governor name and the rack's who-holds-it readout keys off that name.",
        auth="public", limits="shares the image budget."),
    # ---- symoneural-ravencalc -----------------------------------------------------------
    Application(
        id="ravencalc", label="SyMoNeuRaL RavenCalc", kind="application", parent=None,
        runtime="symoneural-ravencalc", page="/ravencalc.html",
        prefixes=("/api/ravencalc",),
        summary="Symbolic algebra on the CPU. It never queues, which is why it stays "
                "available while the rack shows every GPU surface busy.",
        auth="public", limits=_limits("ravencalc")),
    # ---- symoneural-project -------------------------------------------------------------
    Application(
        id="project", label="SyMoNeuRaL Project", kind="application", parent=None,
        runtime="symoneural-project", page="/project.html", prefixes=("/api/project",),
        summary="Projects, items, events, files and backups. SQLite and text; it stores "
                "nothing executable.",
        # Corrected 2026-09-08. This read "public read, write on the same surface" and the
        # surface answers 401 on every route, including the parameterless GETs -- measured,
        # all three. `project/store.py:150` requires SYMONEURAL_PROJECT_TOKEN and the app's
        # own README says "both, or the surface does not exist". The enforcement was right;
        # the declaration was wrong, and appdocs.py is what renders /docs/project, so this
        # page was telling visitors a credentialled surface was open.
        auth="token — `X-Symoneural-Token` on every route, read and write alike. The "
             "surface does not exist at all unless SYMONEURAL_PROJECT_ENABLED=1 and "
             "SYMONEURAL_PROJECT_TOKEN are both set.",
        limits="no GPU lease is taken."),
    # ---- symoneural-studio --------------------------------------------------------------
    Application(
        id="studio", label="SyMoNeuRaL Studio", kind="application", parent=None,
        runtime="symoneural-studio", page="/studio",
        prefixes=("/api/studio", "/studio/editor"),
        summary="The parent workspace: graphs, workflows, tools, models and the agent that "
                "drives them. Reinforce and Exp are its child surfaces and are documented "
                "separately below rather than mixed in here.",
        auth="off by default; both switches must be set before it reports anything but "
             "offline, because it can write to the host.",
        limits="orchestrates work other surfaces report; it never goes busy itself."),
    Application(
        id="train", label="Reinforce · adapter training", kind="child", parent="studio",
        runtime="symoneural-studio", page="/reinforce.html", prefixes=("/api/train",),
        summary="Adapter and low-rank training for the chat persona. A child surface of "
                "Studio, not a runtime of its own — `/api/train/*` is served by "
                "`apps.studio.plugins.reinforce`.",
        auth="public read of datasets, models and presets; starting a run takes the card.",
        limits="a run holds the GPU lease and every serving surface queues behind it."),
    Application(
        id="exp", label="Exp · experience plugins", kind="child", parent="studio",
        runtime="symoneural-studio", page="/exp", prefixes=("/api/exp",),
        summary="The experience-plugin runtime: catalogue, mount, patch and call plugin "
                "services. A child surface of Studio — `/api/exp/*` is served by "
                "`apps.studio.plugins.exp`.",
        auth="public", limits="CPU only; it takes no GPU lease."),
    # ---- symoneural-live ----------------------------------------------------------------
    Application(
        id="live", label="SyMoNeuRaL Live", kind="application", parent=None,
        runtime="symoneural-live", page="/livestack/live", prefixes=("/api/live",),
        summary="The broadcast surface: what is on now, HLS segments, VODs and usage.",
        auth="public",
        limits="bus is `net`, not `gpu`. OBS does encode with NVENC, but outside "
               "gpu-governor.sh, which cannot see the session and does not count it "
               "against the drain floor. The GPU cost is recorded as unmeasured."),
    Application(
        id="streamer", label="SyMoNeuRaL Streamer", kind="child", parent="live",
        runtime="symoneural-live", page="/streamer.html", prefixes=("/api/streamer",),
        summary="IPTV tuning and playback: playlists, EPG, sessions and stream files. A "
                "child application of the Live family with its own task and its own routes.",
        auth="public",
        limits="stream copy, not transcode — the work is network I/O and muxing, so it "
               "never contends for the card."),
    Application(
        id="guide", label="Streamer Guide", kind="child", parent="streamer",
        runtime="symoneural-live", page="/streamer.html",
        prefixes=("/api/streamer/guide",),
        summary="The guide grid: catalogue and filtering. Folded into Streamer as one "
                "product; its routes stay nested under `/api/streamer/guide/*`.",
        auth="public", limits="none of its own."),
    # ---- symoneural-miner ---------------------------------------------------------------
    Application(
        id="miner", label="SyMoNeuRaL Miner", kind="application", parent=None,
        runtime="symoneural-miner", page="/miner.html", prefixes=(),
        summary="One surface over three children: the GPU miner in this box, ASIC rigs "
                "reached over the network, and the settlement gateway. The row carries the "
                "merged headline; each child below carries its own reading, because the "
                "halves fail independently.",
        auth="public read of state; control is operator-gated.",
        limits="the row never merges the child states into one, which is where a merged "
               "reading would start lying."),
    Application(
        id="gpuminer", label="GPU · Ravencoin", kind="child", parent="miner",
        runtime="symoneural-miner", page="/miner.html", prefixes=("/api/gpuminer",),
        summary="KawPow on the RTX 5070 Ti — the only mining hardware physically in this "
                "box.",
        auth="public read; `control` is an operator action.",
        limits="takes the card and contends with every GPU surface.",
        operator_only=("/api/gpuminer/control",)),
    Application(
        id="asicminer", label="ASIC · Antminer + MicroBT", kind="child", parent="miner",
        runtime="symoneural-miner", page="/miner.html", prefixes=("/api/asicminer",),
        summary="Antminer and MicroBT rigs reached over the network, plus the firmware "
                "inventory and the emulator.",
        auth="public read; scan and emulator are operator actions.",
        limits="remote by definition; readings are labelled with their age rather than "
               "presented as current.",
        operator_only=("/api/asicminer/scan", "/api/asicminer/emulator")),
    Application(
        id="gateway", label="Miner gateway · TRON USDT settlement", kind="child",
        parent="miner", runtime="symoneural-miner", page="/gateway.html",
        prefixes=("/api/gateway",),
        summary="Licence settlement on TRON. THIS IS NOT THE PLATFORM GATEWAY. The platform "
                "gateway is `symoneural-gateway`, the Rust service in the "
                "web → gateway → api chain; this is a mining subunit that settles USDT and "
                "never handles a request for a page. The two share a word and nothing else.",
        auth="public read of state; there is no contract, wallet or key material installed.",
        limits="bus is `net`; it never touches the card."),
    # ---- platform -----------------------------------------------------------------------
    Application(
        id="platform", label="SyMoNeuRaL platform", kind="platform", parent=None,
        runtime="symoneural-platform", page="/livestack",
        prefixes=("/api/status", "/api/ws", "/api/news"),
        summary="The rack reading itself, the live socket and the site ticker. The serving "
                "chain is symoneural-web → symoneural-gateway → symoneural-api; these are "
                "the routes that describe it.",
        auth="public",
        limits="`/api/status` supports If-None-Match; the socket sends patches rather than "
               "full snapshots, so prefer it to polling."),
    Application(
        id="accounts", label="Accounts", kind="platform", parent="platform",
        runtime="symoneural-platform", page="/account.html", prefixes=("/api/accounts",),
        summary="Site accounts: signup, login, sessions and password changes.",
        auth="session cookie, HttpOnly. Every route below either establishes or requires "
             "one.",
        limits="login attempts are throttled per account and per address."),
    Application(
        id="controlboard", label="Control Board", kind="platform", parent="platform",
        runtime="symoneural-platform", page="/controlboard",
        # `/local/*` added 2026-09-08. These three were mounted and owned by nobody, so they
        # appeared on no documentation page -- and the totality test could not have caught
        # them, because it only looked at `/api/*`. They belong here: `.claude/CLAUDE.md`
        # describes /local/progress and the Ready/Drop buttons that POST to /local/intake as
        # the operator's controls on the progress page, and /local/tasknote appends a task
        # comment from the same page. Operator surfaces are exactly the ones that end up
        # undocumented, because nobody reading the public docs notices they are missing.
        prefixes=("/api/rack", "/local/progress", "/local/intake", "/local/tasknote"),
        summary="The operator's rack power switches, and the progress page's own controls. "
                "Taking a unit off the rack refuses its HTTP work as well as changing its "
                "light — the reading and the gate are two halves of one fact. The /local/* "
                "routes are loopback-only and refuse anything that crossed the proxy.",
        auth="operator; the /local/* routes are additionally loopback-only and refuse any "
             "request carrying a proxy header",
        limits="only five surfaces are switchable; the exclusions are "
               "reasoned, not accidental.",
        operator_only=("/api/rack/power/{unit_id}",)),
    Application(
        id="voice", label="SyMoNeuRaL Voice", kind="application", parent=None,
        # `symoneural-listen`, not `symoneural-llm`. Corrected 2026-09-08: this said the
        # language engine, and `voice/asr.py:64` builds a path to
        # `symoneural-listen/build/bin/symoneural-listen` -- its own docstring
        # describes the whisper CPU build. Nothing failed; the registry simply named
        # the wrong runtime, which is the kind of error only reading one against the
        # other finds.
        runtime="symoneural-listen", page=None, prefixes=("/api/voice",),
        summary="Speech in and speech out. It has routes and no page yet, so it is "
                "deliberately not a rack row — a row pointing at a 404 is worse than no "
                "row. It is documented here because the routes are real and mounted.",
        auth="public", limits="CPU build; it takes no GPU lease."),
)


BY_ID = {a.id: a for a in APPLICATIONS}

# prefix -> application id. Built rather than written so the two cannot disagree.
OWNERS: dict[str, str] = {}


class RegistryError(ValueError):
    """The registry says something that cannot be true of a partition."""


def _check_registry() -> None:
    """Refuse to import a registry that cannot guarantee disjoint pages.

    Raising here rather than returning a warning is the same choice `roster.py` makes and for
    the same reason: the symptom of a silently-accepted duplicate prefix is a docs page
    quietly showing somebody else's routes, which is the exact failure this module exists to
    make impossible. A crash at import is loud; a leak is not.
    """
    for app in APPLICATIONS:
        if app.parent and app.parent not in BY_ID:
            raise RegistryError(f"{app.id}: parent {app.parent!r} is not an application")
        if app.runtime not in RUNTIMES:
            raise RegistryError(f"{app.id}: runtime {app.runtime!r} is not a known runtime")
        for p in app.prefixes:
            if p in OWNERS:
                raise RegistryError(
                    f"prefix {p!r} is claimed by both {OWNERS[p]!r} and {app.id!r}")
            OWNERS[p] = app.id


_check_registry()


def owner_of(path: str) -> str | None:
    """Which application owns `path`, by LONGEST matching prefix.

    Longest wins, and that is the whole reason this is not a `startswith` loop over an
    arbitrary order: `/api/streamer/guide/filter` matches both `/api/streamer` and
    `/api/streamer/guide`, and the shorter one would put the guide's routes on the streamer
    page and the streamer page's claim to them would be wrong rather than merely broad.
    """
    best_id: str | None = None
    best_len = -1
    for prefix, app_id in OWNERS.items():
        if path == prefix or path.startswith(prefix + "/"):
            # Compare the length of the prefix that MATCHED, not the longest prefix the
            # candidate owns. Those differ, and using the latter is a real bug: `miner`
            # owns no prefixes at all, while `streamer` owns a long one, so a comparison
            # over the owner's longest prefix would let an unrelated application win a
            # match it never made.
            if len(prefix) > best_len:
                best_id, best_len = app_id, len(prefix)
    return best_id


def routes_for(app_id: str, router_routes) -> list[dict]:
    """Every registered route this application owns, read from the live router.

    `router_routes` is `app.routes` -- the structure Starlette matches requests against, not
    the OpenAPI schema. WebSocket routes and `include_in_schema=False` routes are invisible to
    OpenAPI and are real; a docs page built from the schema would omit `/api/ws` and
    `/studio/editor/ws`, which is precisely the false negative `apps/route_matrix.py` was
    written about.
    """
    out: list[dict] = []
    for r in router_routes:
        path = getattr(r, "path", None)
        if not path:
            continue
        if owner_of(path) != app_id:
            continue
        # A WebSocket route has no `methods` at all -- that absence is how Starlette
        # distinguishes it, and it is also why OpenAPI cannot see one. `HEAD` is dropped
        # because Starlette adds it to every GET and nobody reads a docs page to learn that.
        raw = getattr(r, "methods", None)
        if raw is None:
            methods = ["WEBSOCKET"]
        else:
            methods = sorted(m for m in raw if m not in ("HEAD", "OPTIONS"))
            if not methods:
                continue
        doc = (getattr(getattr(r, "endpoint", None), "__doc__", "") or "").strip()
        out.append({
            "path": path,
            "methods": methods,
            "summary": doc.split("\n", 1)[0][:200],
        })
    out.sort(key=lambda d: d["path"])
    return out


def visible_routes(app_id: str, router_routes, *, audience: str = "all") -> list[dict]:
    """`routes_for`, with operator-only paths removed for a customer audience.

    A route a customer may not call is not merely uninteresting to them -- documenting it on
    a customer page presents an action they will be refused as one they should be taking. The
    handshake names this for DispatchOS specifically and the rule is the same everywhere.
    """
    rows = routes_for(app_id, router_routes)
    if audience != "customer":
        return rows
    blocked = set(BY_ID[app_id].operator_only)
    return [r for r in rows if r["path"] not in blocked]


def e(s: str) -> str:
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------------------------------
# The page.
#
# Inline, like `/docs` and for the reason its docstring gives: a page assembled at request
# time is never seen by `tools/build_cachebust.py`, so a stylesheet of its own would ship
# unstamped and be cacheable for a week against markup that changes whenever a route does.
# It borrows `/symoneural.css` and `/rack-detail.css`, which ARE stamped, and adds only
# `ad-`-prefixed rules. The prefix is not tidiness: `.bar` collapsed this site's header to
# 7px everywhere, and an unprefixed `.path` or `.method` here would be that bug rewritten.

DOCS_STYLE = """<style>
.ad-wrap{max-width:1080px;margin:0 auto;padding:0 clamp(16px,4vw,28px) 96px}
.ad-head{padding:clamp(22px,4vw,38px) 0 4px}
.ad-kind{display:inline-flex;align-items:center;gap:8px;font-size:var(--t6);
  letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:600}
.ad-title{margin:10px 0 0;font-size:clamp(26px,3.4vw,40px);letter-spacing:-.022em;
  font-weight:680;line-height:1.1}
.ad-sum{margin:14px 0 0;color:var(--dim);font-size:var(--t4);line-height:1.62;max-width:68ch}
.ad-facts{display:grid;gap:12px;margin:26px 0 0;
  grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.ad-fact{background:var(--sf3);border:1px solid var(--sfline);border-radius:var(--r-panel);
  padding:14px 16px}
.ad-fact b{display:block;font-size:var(--t6);letter-spacing:.12em;text-transform:uppercase;
  color:var(--faint);font-weight:600;margin-bottom:6px}
.ad-fact span{color:var(--fg);font-size:var(--t5);line-height:1.55}
.ad-fact a{color:var(--accent)}
.ad-sec{margin-top:clamp(30px,5vw,52px)}
.ad-sec h2{margin:0 0 6px;font-size:clamp(19px,2.2vw,25px);letter-spacing:-.014em;
  font-weight:660}
.ad-sec p.ad-note{margin:0 0 18px;color:var(--dim);font-size:var(--t5);line-height:1.6;
  max-width:74ch}
.ad-rows{border:1px solid var(--sfline);border-radius:var(--r-panel);overflow:hidden}
.ad-row{display:grid;grid-template-columns:minmax(96px,auto) 1fr;gap:0 16px;
  padding:13px 16px;border-bottom:1px solid var(--sfline);align-items:baseline}
.ad-row:last-child{border-bottom:0}
.ad-m{font:600 var(--t6)/1.4 ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  letter-spacing:.06em;color:var(--accent-ink);background:var(--accent);
  border-radius:var(--r-sm);padding:3px 8px;justify-self:start;white-space:nowrap}
.ad-m.ad-read{background:transparent;color:var(--accent);
  border:1px solid var(--sfline)}
.ad-p{font:var(--t5)/1.5 ui-monospace,"SF Mono",Menlo,Consolas,monospace;color:var(--fg);
  word-break:break-word}
.ad-d{grid-column:2;margin:5px 0 0;color:var(--dim);font-size:var(--t5);line-height:1.55}
.ad-kids{display:grid;gap:12px;margin-top:16px;
  grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.ad-kid{display:block;text-decoration:none;background:var(--sf3);
  border:1px solid var(--sfline);border-radius:var(--r-panel);padding:16px 18px;
  transition:border-color var(--dur1) var(--ease),background var(--dur1) var(--ease)}
.ad-kid:hover{border-color:var(--accent);background:var(--sf2)}
.ad-kid b{display:block;color:var(--fg);font-size:var(--t4);font-weight:645;
  letter-spacing:-.004em}
.ad-kid span{display:block;margin-top:5px;color:var(--dim);font-size:var(--t5);
  line-height:1.5}
.ad-back{display:inline-block;margin-top:34px;color:var(--dim);font-size:var(--t5)}
.ad-back a{color:var(--accent)}
@media (max-width:620px){
  .ad-row{grid-template-columns:1fr;gap:6px}
  .ad-d{grid-column:1}
}
</style>"""


def _fact(label: str, value: str) -> str:
    return f'<div class="ad-fact"><b>{e(label)}</b><span>{value}</span></div>'


def render(app: Application, rows: list[dict], *, audience: str = "all",
           children: tuple[Application, ...] = (), docs_root: str = "/docs") -> str:
    """One application's documentation page.

    `docs_root` exists so DispatchOS's customer page can live at `/demo/dispatchos/docs`,
    behind the same door as the application it documents, while every other page hangs off
    `/docs/<id>`. A customer who has been given one address should not have to learn a second
    one to read about it.
    """
    parent = BY_ID.get(app.parent or "")
    kind = {"application": "Application", "child": "Child surface",
            "platform": "Platform", "compatibility": "Compatibility surface"}[app.kind]

    facts = [
        _fact("Runtime owner", f'{e(app.runtime)}<br><span style="color:var(--faint)">'
                              f'{e(RUNTIMES[app.runtime])}</span>'),
        _fact("Parent", f'<a href="{docs_root}/{e(parent.id)}">{e(parent.label)}</a>'
                        if parent else "none &mdash; this is a top-level surface"),
        _fact("Authentication", e(app.auth)),
    ]
    if app.page:
        facts.append(_fact("Application", f'<a href="{e(app.page)}">{e(app.page)}</a>'))
    if app.limits:
        facts.append(_fact("Operational limits", e(app.limits)))

    if rows:
        body = []
        for r in rows:
            read = all(m in ("GET", "WEBSOCKET") for m in r["methods"])
            ms = " ".join(f'<span class="ad-m{" ad-read" if read else ""}">{e(m)}</span>'
                          for m in r["methods"])
            d = (f'<p class="ad-d">{e(r["summary"])}</p>' if r["summary"] else "")
            body.append(f'<div class="ad-row">{ms}'
                        f'<code class="ad-p">{e(r["path"])}</code>{d}</div>')
        table = f'<div class="ad-rows">{"".join(body)}</div>'
    else:
        table = ('<div class="ad-rows"><div class="ad-row">'
                 '<span class="ad-m ad-read">&mdash;</span>'
                 '<code class="ad-p">This surface mounts no HTTP routes of its own.</code>'
                 '</div></div>')

    hidden = ""
    if audience == "customer" and app.operator_only:
        hidden = ('<p class="ad-note">This page documents the customer surface. Operator '
                  'actions on this application exist and are deliberately not listed here: '
                  'they are refused to a customer account, and documenting an action you '
                  'will be refused reads as an instruction you are failing to follow.</p>')

    kids = ""
    if children:
        cards = "".join(
            f'<a class="ad-kid" href="{docs_root}/{e(c.id)}"><b>{e(c.label)}</b>'
            f'<span>{e(c.summary.split(".")[0])}.</span></a>' for c in children)
        kids = (f'<div class="ad-sec"><h2>Child surfaces</h2>'
                f'<p class="ad-note">These belong to {e(app.label)} and run on the same '
                f'runtime. They are separate pages because they own separate routes &mdash; '
                f'not because they are separate runtimes.</p>'
                f'<div class="ad-kids">{cards}</div></div>')

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(app.label)} &middot; documentation &middot; SyMoNeuRaL</title>"
        '<link rel="icon" href="/favicon-32.png" sizes="32x32">'
        '<link rel="stylesheet" href="/symoneural.css">'
        '<link rel="stylesheet" href="/rack-detail.css">'
        '<meta name="theme-color" content="#0e100f">'
        f"{DOCS_STYLE}</head><body>"
        '<header><div class="bar wrap">'
        '<a class="logo" href="/"><img src="/mark-64.png" alt="" width="30" height="30">'
        '<b>SyMoNeu<i>RaL</i></b></a>'
        '<nav>'
        f'<a href="{docs_root}">All documentation</a>'
        '<a href="/livestack">Live Stack</a>'
        + (f'<a class="cta ghost" href="{e(app.page)}">Open {e(app.label)}</a>'
           if app.page else '<a class="cta ghost" href="/docs">Platform API</a>')
        + '</nav></div></header>'
        '<div class="ad-wrap">'
        f'<div class="ad-head"><p class="ad-kind">{e(kind)}</p>'
        f'<h1 class="ad-title">{e(app.label)}</h1>'
        f'<p class="ad-sum">{e(app.summary)}</p>'
        f'<div class="ad-facts">{"".join(facts)}</div></div>'
        f'{kids}'
        '<div class="ad-sec"><h2>Routes</h2>'
        '<p class="ad-note">Every route below is read from this service&rsquo;s own router at '
        'the moment you loaded the page &mdash; not from a schema and not from a list typed '
        'by hand. It cannot describe a route that no longer exists, omit one that was just '
        'added, or show a route belonging to another application: ownership is a partition '
        'over path prefixes, so these sets are disjoint by construction.</p>'
        f'{hidden}{table}</div>'
        f'<p class="ad-back">Platform-wide reference: <a href="/docs">/docs</a> &middot; '
        f'raw schema: <a href="/openapi.json">/openapi.json</a></p>'
        '</div>'
        '<script src="/shell.js" defer></script>'
        '</body></html>'
    )
