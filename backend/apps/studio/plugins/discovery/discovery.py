#!/usr/bin/env python3
"""symoneural-discovery — search to crawl to answer, one tool, one database.

A search API finds candidate URLs; the crawler renders and extracts them with real browser
fidelity rather than trusting the search engine's snippet; an optional synthesis step turns the
extracted pages into a cited answer.

    query --[search backend]--> URLs --[crawl queue]--> rendered pages
          --[extractor]--> structured text --[LLM, optional]--> cited answer

    login     open a visible browser, log in by hand, session persists
    search    hit search backends only, no page fetching — fast, cheap, works today
    discover  search, then crawl and render each result (the main command)
    crawl     crawl from --seeds or --sitemap, no search step at all
    answer    discover, then synthesise a cited answer from the rendered pages
    export    dump the stored pages table to JSON
    stats     counts by status, queue depth, cache size

One SQLite file holds the search cache, the crawl queue and every result, so a `discover` run
and a later `crawl` run share history and nothing is fetched twice without being asked for.

## What this does not do

No CAPTCHA solving, no defeating bot-detection or fingerprinting, no paywall bypass, and no
scraping a search engine's own results page — the keyed backends below are official APIs. If a
target is actively blocking automated access that is a signal to stop, not a gap to route
around. `robots.txt` is honoured by default. The `--ignore-robots` and `--ignore-crawl-delay`
flags exist because Garrett asked for no safeguards he had not set himself, and they are opt-in
per run; the default is the polite path.

## Half of this runs today and half does not, and it says which

Measured on this box 2026-08-20: `requests`, `bs4`, `lxml`, `httpx` and `websockets` are on
the system interpreter; `playwright` and `anthropic` are not, and installing them is Garrett's
action (see `symoneural-discovery.requirements.txt`). So `search`, `stats` and `export` work
now; every rendering path and `answer` raise `MissingDependency` naming the install command.

**Every third-party import in this file is lazy, and that is structural rather than tidy.**
`backend/apps/` is a pytest root. A module-level `from playwright.async_api import ...` on a box
without playwright does not fail the one test that needs it — it aborts *collection*, and an
aborted collection is not a smaller pass count, it is `Interrupted: 2 errors` and no count at
all. Two suites in this repo (`apps/studio/plugins/reinforce/tests`, `apps/remix/tests`) are already excluded
by `--ignore` for exactly that reason and this app declines to become the third.

## Credentials

`symoneural-discovery.env` beside this file, loaded automatically by `envfile.py` — one env
file per app, named after the app. The tracked template is `symoneural-discovery.env.example`
with every value empty. Vendor-spelled names (`GOOGLE_CSE_API_KEY`, `ANTHROPIC_API_KEY`) are
kept as the vendors spell them because their SDKs read those exact names; our own knobs are
`SYMONEURAL_DISCOVERY_*`, per the house rule.

## Usage

    python3 -m apps.studio.plugins.discovery.discovery search "EU AI Act enforcement 2026"
    python3 -m apps.studio.plugins.discovery.discovery discover "…" --backends google --n 8 --depth 1
    python3 -m apps.studio.plugins.discovery.discovery crawl --seeds seeds.txt --depth 2 --same-domain
    python3 -m apps.studio.plugins.discovery.discovery answer "…" --backends google --n 6
    python3 -m apps.studio.plugins.discovery.discovery stats

or `bin/symoneural-discovery <subcommand>` from anywhere, which is the same code with the
import path already set up.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

# ==========================================================================
# Where things live
# ==========================================================================


def repo_root() -> Path:
    """The repo, found by its own signature rather than by counting `..` hops.

    `backend/api.py` plus `scripts/gpu-governor.sh` is the pair `api.py` itself probes for, so
    this agrees with the rest of the stack by construction. Counting parents instead would
    break the day this module moves one directory, and it would break silently — landing on
    `/home/google` and writing a database there.
    """
    for parent in Path(__file__).resolve().parents:
        if ((parent / "backend" / "api.py").exists()
                and (parent / "scripts" / "gpu-governor.sh").exists()):
            return parent
    # A checkout without the signature is not a fatal error for `search`, which needs no
    # database at all, so fall back to the package's grandparent rather than raising here.
    return Path(__file__).resolve().parents[2]


# `run/` and not `logs/`: it holds the GPU governor's lock as well as output, and the lock is
# the point of the name. `run/` is gitignored, so neither the database nor a logged-in browser
# profile can reach a commit or the .deb.
RUN_DIR = repo_root() / "run"
DB_PATH = RUN_DIR / "symoneural-discovery.sqlite3"
PROFILE_DIR = RUN_DIR / "symoneural-discovery-profile"

DEFAULT_TIMEOUT_MS = 15_000

# A crawler that will not say who it is deserves the blocks it gets. The address is the one
# CLAUDE.md already publishes for enquiries, so a site operator has a real human to write to.
USER_AGENT = "symoneural-discovery/0.1 (+contact: symonsayadmin@symoneural.com)"

# The `answer` and `--expand` paths. Named once so there is a single line to change, rather
# than a string literal in two functions that drift apart.
SYNTH_MODEL = "claude-sonnet-5"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("discovery")


# ==========================================================================
# Lazy third-party imports
# ==========================================================================

class MissingDependency(RuntimeError):
    """A dependency that is not installed, with the command that installs it.

    Raised, never printed-and-continued. A crawl that silently degrades to "fetched the
    snippet instead of the page" produces results that look like the real thing and are not.
    """


_VENV = "backend/apps/studio/plugins/discovery/symoneural-discovery.venv"

_INSTALL_HINT = {
    "playwright": (f"{_VENV}/bin/pip install playwright && "
                   f"{_VENV}/bin/playwright install chromium"),
    "bs4": f"{_VENV}/bin/pip install beautifulsoup4 lxml",
    "lxml": f"{_VENV}/bin/pip install lxml",
    "requests": f"{_VENV}/bin/pip install requests",
    "anthropic": f"{_VENV}/bin/pip install anthropic",
}


def _require(module: str):
    """Import a third-party module or raise with the fix.

    The hint names the app's own venv and never a bare `pip install`, because a bare one lands
    in the system interpreter — which is what serves `symoneural-api` and is off limits.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        hint = _INSTALL_HINT.get(module, f"{_VENV}/bin/pip install {module}")
        raise MissingDependency(
            f"{module} is not installed on this interpreter ({sys.executable}). "
            f"From the repo root: {hint}"
        ) from exc


def available() -> dict[str, bool]:
    """Which optional dependencies are importable right now.

    Used by `stats`, by `__init__.status()` for the rack row, and by the tests. It answers the
    question the rack actually asks — can this surface do its job — instead of asserting that
    it can.
    """
    out = {}
    for module in ("requests", "bs4", "lxml", "playwright", "anthropic"):
        try:
            importlib.import_module(module)
            out[module] = True
        except ImportError:
            out[module] = False
    return out


# ==========================================================================
# Storage — one DB: pages, queue, search cache
# ==========================================================================

class Store:
    """One SQLite file, reached from two kinds of caller.

    The crawl side is single-threaded asyncio and is serialised by `self.lock`, an
    `asyncio.Lock`. The search side is **not**: `fan_out_search` runs each backend inside
    `asyncio.to_thread`, so `cache_get`/`cache_set` are entered from several worker threads at
    once, where an `asyncio.Lock` provides no exclusion whatsoever — it is not thread-safe and
    it is not even bound to those threads' event loop. `check_same_thread=False` makes that
    legal rather than safe.

    Hence the second, plain `threading.Lock` guarding exactly the cache methods. Both locks are
    needed and neither substitutes for the other; the asyncio one orders coroutines on one
    thread, the threading one orders threads.
    """

    def __init__(self, path: Path):
        path = Path(path)
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = asyncio.Lock()
        self._tlock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS pages (
                url TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                depth INTEGER NOT NULL,
                title TEXT,
                text TEXT,
                fields_json TEXT,
                snippet TEXT,
                rank INTEGER,
                query TEXT,
                error TEXT,
                attempt INTEGER DEFAULT 1,
                fetched_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queue (
                url TEXT PRIMARY KEY,
                depth INTEGER NOT NULL,
                snippet TEXT,
                rank INTEGER,
                query TEXT,
                enqueued_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS search_cache (
                cache_key TEXT PRIMARY KEY,
                results_json TEXT NOT NULL,
                cached_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS pages_query_idx ON pages (query, status);
        """)
        self.conn.commit()

    # ---- crawl queue / results -------------------------------------

    async def seen(self, url: str) -> bool:
        async with self.lock:
            row = self.conn.execute("SELECT 1 FROM pages WHERE url = ?", (url,)).fetchone()
            return row is not None

    async def enqueue(self, url: str, depth: int, snippet: str = "", rank: int = 0,
                      query: str = "") -> None:
        async with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO queue (url, depth, snippet, rank, query, enqueued_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (url, depth, snippet, rank, query, time.time()),
            )
            self.conn.commit()

    async def dequeue_batch(self, n: int) -> list[tuple[str, int, str, int, str]]:
        async with self.lock:
            rows = self.conn.execute(
                "SELECT url, depth, snippet, rank, query FROM queue ORDER BY enqueued_at LIMIT ?",
                (n,),
            ).fetchall()
            if rows:
                self.conn.executemany("DELETE FROM queue WHERE url = ?", [(r[0],) for r in rows])
                self.conn.commit()
            return rows

    async def requeue(self, url: str, depth: int, snippet: str, rank: int, query: str) -> None:
        await self.enqueue(url, depth, snippet, rank, query)

    async def save(self, url: str, depth: int, result: "FetchResult", snippet: str = "",
                   rank: int = 0, query: str = "") -> None:
        async with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO pages (url, status, depth, title, text, fields_json, "
                "snippet, rank, query, error, attempt, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, result.status, depth, result.title, result.text,
                 json.dumps(result.fields), snippet, rank, query, result.error,
                 result.attempts, time.time()),
            )
            self.conn.commit()

    def queue_depth(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]

    def get_pages_for_query(self, query: str) -> list[dict]:
        """Every successfully rendered page attributed to this query, seeds and children alike.

        `worker()` propagates `query` when it enqueues a link at depth+1, which is why a
        `--depth 1` run's crawled pages appear here at all. They arrive with `rank = 0`, so
        `ORDER BY rank` puts them ahead of the ranked seeds; the second sort key pushes them
        after it. Without it a `--depth 2` run would hand the synthesiser a page nobody
        searched for as source `[1]`.
        """
        rows = self.conn.execute(
            "SELECT url, title, text, snippet, rank FROM pages "
            "WHERE query = ? AND status = 'ok' ORDER BY (rank = 0), rank",
            (query,),
        ).fetchall()
        return [{"url": r[0], "title": r[1], "text": r[2], "snippet": r[3], "rank": r[4]}
                for r in rows]

    def stats(self) -> dict:
        by_status = dict(self.conn.execute(
            "SELECT status, COUNT(*) FROM pages GROUP BY status").fetchall())
        cached = self.conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        return {
            "db": str(self.path),
            "by_status": by_status,
            "queued": self.queue_depth(),
            "search_cache_entries": cached,
            # Names only. `env_keys_loaded` is a list of names and never values, so `stats`
            # output is safe to paste into a bug report.
            "dependencies": available(),
        }

    def export(self, out_path: Path) -> int:
        rows = self.conn.execute(
            "SELECT url, status, depth, title, text, fields_json, snippet, rank, query, error "
            "FROM pages").fetchall()
        data = [{"url": r[0], "status": r[1], "depth": r[2], "title": r[3], "text": r[4],
                 "fields": json.loads(r[5] or "{}"), "snippet": r[6], "rank": r[7],
                 "query": r[8], "error": r[9]} for r in rows]
        Path(out_path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return len(data)

    # ---- search cache -------------------------------------------------

    @staticmethod
    def _cache_key(backend: str, query: str, n: int) -> str:
        return f"{backend}::{n}::{query.strip().lower()}"

    def cache_get(self, backend: str, query: str, n: int, ttl: float) -> Optional[list[dict]]:
        with self._tlock:
            row = self.conn.execute(
                "SELECT results_json, cached_at FROM search_cache WHERE cache_key = ?",
                (self._cache_key(backend, query, n),),
            ).fetchone()
        if row is None:
            return None
        results_json, cached_at = row
        if time.time() - cached_at > ttl:
            return None
        return json.loads(results_json)

    def cache_set(self, backend: str, query: str, n: int, results: list[dict]) -> None:
        with self._tlock:
            self.conn.execute(
                "INSERT OR REPLACE INTO search_cache (cache_key, results_json, cached_at) "
                "VALUES (?, ?, ?)",
                (self._cache_key(backend, query, n), json.dumps(results), time.time()),
            )
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# ==========================================================================
# Search backends
# ==========================================================================

@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    rank: int
    source: str


class SearchBackend(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str, n: int) -> list[SearchHit]:
        ...


class GoogleCSEBackend(SearchBackend):
    """Google Programmable Search Engine (Custom Search JSON API).

    The official keyed path. There is no supported way to script Google's own results page, and
    this does not try — see the module docstring.
    """

    name = "google"
    ENDPOINT = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, cx: str):
        self.api_key, self.cx = api_key, cx

    def search(self, query: str, n: int) -> list[SearchHit]:
        requests = _require("requests")
        results: list[SearchHit] = []
        # The API pages ten at a time and `start` is 1-based, so this is not an off-by-one:
        # start=1 wants num=10, start=11 wants the next ten.
        for start in range(1, n + 1, 10):
            resp = requests.get(self.ENDPOINT, params={
                "key": self.api_key, "cx": self.cx, "q": query,
                "start": start, "num": min(10, n - start + 1),
            }, timeout=10)
            resp.raise_for_status()
            items = resp.json().get("items", [])
            for i, item in enumerate(items):
                results.append(SearchHit(item.get("title", ""), item.get("link", ""),
                                         item.get("snippet", ""), start + i, self.name))
            if len(items) < 10:
                break
        return results[:n]


class BingSearchBackend(SearchBackend):
    """Bing Web Search API via Azure Cognitive Services. **Untested here — possibly retired.**

    Garrett's note, 2026-08-20: Microsoft retired the standalone Bing Search APIs in mid-2025
    in favour of "Grounding with Bing Search", scoped to Azure AI Agent Service rather than a
    key you drop into a script. This class still speaks the classic `api.bing.microsoft.com`
    shape. Nobody has authenticated against it from this box, so it is unverified rather than
    working; if a new sign-up cannot produce a key for this endpoint, delete the class rather
    than leave a backend in `--backends` that cannot work.
    """

    name = "bing"
    ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, n: int) -> list[SearchHit]:
        requests = _require("requests")
        resp = requests.get(self.ENDPOINT,
                            headers={"Ocp-Apim-Subscription-Key": self.api_key},
                            params={"q": query, "count": n}, timeout=10)
        resp.raise_for_status()
        pages = resp.json().get("webPages", {}).get("value", [])
        return [SearchHit(p.get("name", ""), p.get("url", ""), p.get("snippet", ""),
                          i + 1, self.name) for i, p in enumerate(pages[:n])]


class SerpApiBackend(SearchBackend):
    """serpapi.com — third-party aggregator, paid, fronts several engines."""

    name = "serpapi"
    ENDPOINT = "https://serpapi.com/search"

    def __init__(self, api_key: str, engine: str = "google"):
        self.api_key, self.engine = api_key, engine

    def search(self, query: str, n: int) -> list[SearchHit]:
        requests = _require("requests")
        resp = requests.get(self.ENDPOINT, params={
            "engine": self.engine, "q": query, "api_key": self.api_key, "num": n,
        }, timeout=10)
        resp.raise_for_status()
        organic = resp.json().get("organic_results", [])
        return [SearchHit(r.get("title", ""), r.get("link", ""), r.get("snippet", ""),
                          r.get("position", i + 1), self.name)
                for i, r in enumerate(organic[:n])]


class DuckDuckGoHTMLBackend(SearchBackend):
    """No-key fallback via DuckDuckGo's own no-JS result page.

    Caveats, stated because this is the default and therefore the one most likely to be
    believed: no SLA, undocumented rate limits, and markup that can change without notice —
    when it does, this returns zero results rather than wrong ones, which is the failure mode
    to prefer. Fine for proving the pipeline; move to a keyed backend above once reliability
    matters.
    """

    name = "duckduckgo"
    ENDPOINT = "https://html.duckduckgo.com/html/"

    def search(self, query: str, n: int) -> list[SearchHit]:
        requests = _require("requests")
        _require("bs4")
        from bs4 import BeautifulSoup
        resp = requests.post(self.ENDPOINT, data={"q": query},
                             headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[SearchHit] = []
        for i, block in enumerate(soup.select(".result")[:n]):
            link = block.select_one(".result__a")
            if not link:
                continue
            snippet = block.select_one(".result__snippet")
            results.append(SearchHit(link.get_text(strip=True), link.get("href", ""),
                                     snippet.get_text(strip=True) if snippet else "",
                                     i + 1, self.name))
        return results


BACKEND_NAMES = ("google", "bing", "serpapi", "duckduckgo")


def build_backend(name: str) -> SearchBackend:
    """Name to constructed backend, raising `SystemExit` with the missing variable named.

    Every check is on the *value* being truthy, not the name being present: the tracked
    template ships every name with an empty value, so `"GOOGLE_CSE_API_KEY" in os.environ` is
    true on a completely unconfigured install and would send an empty key to Google to be
    rejected as a 400. See `envfile.parse`, which keeps empty values deliberately.
    """
    if name == "google":
        key, cx = os.environ.get("GOOGLE_CSE_API_KEY"), os.environ.get("GOOGLE_CSE_CX")
        if not (key and cx):
            raise SystemExit("Set GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX to use the google "
                             "backend (symoneural-discovery.env).")
        return GoogleCSEBackend(key, cx)
    if name == "bing":
        key = os.environ.get("BING_SEARCH_API_KEY")
        if not key:
            raise SystemExit("Set BING_SEARCH_API_KEY to use the bing backend "
                             "(symoneural-discovery.env) — but read the class docstring "
                             "first, this API may have been retired.")
        return BingSearchBackend(key)
    if name == "serpapi":
        key = os.environ.get("SERPAPI_API_KEY")
        if not key:
            raise SystemExit("Set SERPAPI_API_KEY to use the serpapi backend "
                             "(symoneural-discovery.env).")
        return SerpApiBackend(key)
    if name == "duckduckgo":
        return DuckDuckGoHTMLBackend()
    raise SystemExit(f"Unknown backend: {name}. Known: {', '.join(BACKEND_NAMES)}")


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 15.0


def search_with_retry(backend: SearchBackend, query: str, n: int,
                      retry: RetryConfig) -> list[SearchHit]:
    """Exponential backoff around one backend, returning `[]` when it never answers.

    `[]` rather than a raise, because `fan_out_search` may be running four backends and one
    dead key should cost its own results, not the whole run's. The error is logged at ERROR so
    the empty list is never silent.
    """
    requests = _require("requests")
    last_error: Optional[Exception] = None
    for attempt in range(1, retry.max_attempts + 1):
        try:
            return backend.search(query, n)
        except MissingDependency:
            # Not retryable and not this function's to swallow: no amount of backoff installs
            # a package, and the caller needs to see the install command.
            raise
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 429:
                log.warning("%s: rate limited (429), attempt %d/%d",
                            backend.name, attempt, retry.max_attempts)
            last_error = exc
        except requests.exceptions.RequestException as exc:
            last_error = exc
        if attempt < retry.max_attempts:
            time.sleep(min(retry.base_delay * (2 ** (attempt - 1)), retry.max_delay))
    log.error("%s: search failed after %d attempts (%s)",
              backend.name, retry.max_attempts, last_error)
    return []


def reciprocal_rank_fusion(result_sets: list[list[SearchHit]], k: int = 60) -> list[SearchHit]:
    """Merge ranked lists from several backends or query phrasings.

    A URL ranked well across several sources outranks a fluke first place in one. `k=60` is the
    conventional constant from the original RRF paper; it flattens the difference between rank
    1 and rank 2 so that agreement matters more than position.
    """
    scores: dict[str, float] = {}
    best: dict[str, SearchHit] = {}
    for results in result_sets:
        for hit in results:
            url = hit.url.rstrip("/")
            scores[url] = scores.get(url, 0.0) + 1.0 / (k + hit.rank)
            if url not in best or hit.rank < best[url].rank:
                best[url] = hit
    ranked = sorted(scores, key=lambda u: scores[u], reverse=True)
    return [SearchHit(best[u].title, best[u].url, best[u].snippet, i + 1,
                      f"fused({best[u].source})") for i, u in enumerate(ranked)]


def expand_query(query: str, n_variants: int, anthropic_client=None) -> list[str]:
    """Alternate phrasings to widen recall — LLM if a client is given, heuristic otherwise.

    Expansion is a nice-to-have, so a failed LLM call falls back rather than aborting the run.
    The heuristic is crude on purpose: quoting the phrase and rotating the leading word are
    cheap and do change what a search engine returns, and pretending to more than that would
    be inventing a capability.
    """
    if n_variants <= 1:
        return [query]
    if anthropic_client is not None:
        try:
            resp = anthropic_client.messages.create(
                model=SYNTH_MODEL, max_tokens=200,
                messages=[{"role": "user", "content":
                           f"Generate {n_variants - 1} alternate search-engine phrasings of "
                           f"this query. Different wording or angle, same intent. One per "
                           f"line, no numbering.\n\nQuery: {query}"}],
            )
            lines = [ln.strip() for ln in resp.content[0].text.splitlines() if ln.strip()]
            if lines:
                return [query] + lines[:n_variants - 1]
            log.warning("Query expansion returned nothing usable — using heuristic fallback.")
        except Exception as exc:
            log.warning("Query expansion via LLM failed (%s) — using heuristic fallback.", exc)
    variants = [query, f'"{query}"']
    words = query.split()
    if len(words) > 3:
        variants.append(" ".join(words[1:] + words[:1]))
    return variants[:n_variants]


async def fan_out_search(backends: list[SearchBackend], queries: list[str], n: int,
                         store: Optional[Store], ttl: float,
                         retry: RetryConfig) -> list[SearchHit]:
    """Every backend against every query phrasing, concurrently, fused.

    The per-backend work is blocking `requests`, so it goes to `asyncio.to_thread` — which is
    exactly why `Store`'s cache methods carry a `threading.Lock` and not only the `asyncio`
    one. See `Store`'s docstring.
    """
    async def one(backend: SearchBackend, query: str) -> list[SearchHit]:
        def cached_search() -> list[SearchHit]:
            if store is not None:
                cached = store.cache_get(backend.name, query, n, ttl)
                if cached is not None:
                    log.info("%s | %r: cache hit", backend.name, query)
                    return [SearchHit(**d) for d in cached]
            results = search_with_retry(backend, query, n, retry)
            log.info("%s | %r: %d results", backend.name, query, len(results))
            if store is not None and results:
                store.cache_set(backend.name, query, n, [r.__dict__ for r in results])
            return results
        return await asyncio.to_thread(cached_search)

    result_sets = await asyncio.gather(*[one(b, q) for b in backends for q in queries])
    result_sets = [rs for rs in result_sets if rs]
    if not result_sets:
        return []
    if len(result_sets) == 1:
        return result_sets[0]
    return reciprocal_rank_fusion(result_sets)


# ==========================================================================
# robots.txt
# ==========================================================================

_robots_cache: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
_robots_lock = threading.Lock()


def _load_robots(origin: str) -> Optional[urllib.robotparser.RobotFileParser]:
    """Fetch and parse one origin's robots.txt, once. `None` means "could not read it".

    The lock is not decoration: this runs under `asyncio.to_thread` from several crawl workers,
    which will hit the same origin at the same moment on the first page of a domain.

    `None` is treated as permission by the caller. That is the standard reading — an
    unreachable or absent robots.txt is not a disallow — but it is a decision, so it is written
    down here rather than left to be inferred from a falsy check.
    """
    with _robots_lock:
        if origin in _robots_cache:
            return _robots_cache[origin]
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    try:
        parser.read()
    except Exception:
        parser = None  # type: ignore[assignment]
    with _robots_lock:
        _robots_cache[origin] = parser
    return parser


async def robots_check(url: str, user_agent: str = "*") -> tuple[bool, Optional[float]]:
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    parser = await asyncio.to_thread(_load_robots, origin)
    if parser is None:
        return True, None
    delay = parser.crawl_delay(user_agent)
    return parser.can_fetch(user_agent, url), (float(delay) if delay else None)


# ==========================================================================
# Sitemap discovery — seeding with no search step
# ==========================================================================

async def discover_sitemap_urls(sitemap_url: str) -> list[str]:
    """Flatten a sitemap, following one level of sitemap index.

    One level and not recursive: a sitemap index pointing at another index is legal and rare,
    and an unbounded walk over a hostile or looping index is a hang. If a real target needs
    two levels, that is a change to make deliberately.
    """
    def fetch(url: str) -> str:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")

    try:
        xml_text = await asyncio.to_thread(fetch, sitemap_url)
    except Exception as exc:
        log.error("Could not fetch sitemap %s: %s", sitemap_url, exc)
        return []

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        log.error("Could not parse sitemap %s: %s", sitemap_url, exc)
        return []

    sub = [el.text for el in root.findall(".//sm:sitemap/sm:loc", ns) if el.text]
    if sub:
        urls: list[str] = []
        for child in sub:
            try:
                sub_root = ElementTree.fromstring(await asyncio.to_thread(fetch, child))
                urls += [el.text for el in sub_root.findall(".//sm:url/sm:loc", ns) if el.text]
            except Exception as exc:
                log.warning("Skipping sub-sitemap %s: %s", child, exc)
        return urls
    return [el.text for el in root.findall(".//sm:url/sm:loc", ns) if el.text]


# ==========================================================================
# Per-domain rate and concurrency limiting
# ==========================================================================

class DomainThrottle:
    """Politeness, per domain: at most N in flight and at least `delay` between starts.

    Per *domain* and not global, because the thing that gets a crawler blocked is hammering one
    host, while four hosts at once costs nobody anything.
    """

    def __init__(self, default_delay: float = 2.0, per_domain_concurrency: int = 2):
        self.default_delay = default_delay
        self.per_domain_concurrency = per_domain_concurrency
        self._delays: dict[str, float] = {}
        self._last_start: dict[str, float] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    def set_delay(self, domain: str, delay: float) -> None:
        self._delays[domain] = delay

    async def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        async with self._lock:
            if domain not in self._semaphores:
                self._semaphores[domain] = asyncio.Semaphore(self.per_domain_concurrency)
            return self._semaphores[domain]

    async def acquire(self, url: str) -> asyncio.Semaphore:
        """Hold a slot for this domain and wait out its delay. Returns the semaphore to release.

        The reservation is made *before* sleeping — `_last_start` is set to the time this
        request will actually start, not to now — so two workers arriving together space
        themselves properly instead of both reading the same stale `last` and both going.

        The `try` is what stops a shutdown from leaking a permit: `asyncio.sleep` here is a
        cancellation point, and `run_crawl` cancels workers. Without it a cancelled wait would
        return a permit to nobody and the domain's concurrency would shrink by one for the rest
        of the run.
        """
        domain = urlparse(url).netloc
        sem = await self._get_semaphore(domain)
        await sem.acquire()
        try:
            delay = self._delays.get(domain, self.default_delay)
            async with self._lock:
                last = self._last_start.get(domain, 0.0)
                wait = delay - (time.time() - last)
                self._last_start[domain] = time.time() + max(wait, 0.0)
            if wait > 0:
                await asyncio.sleep(wait)
        except BaseException:
            sem.release()
            raise
        return sem

    def release(self, sem: asyncio.Semaphore) -> None:
        sem.release()


# ==========================================================================
# Extraction
# ==========================================================================

@dataclass
class FetchResult:
    status: str
    title: str = ""
    text: str = ""
    fields: dict = field(default_factory=dict)
    error: str = ""
    attempts: int = 1


ExtractorFn = Callable[..., Awaitable[dict]]
_extractors: dict[str, ExtractorFn] = {}


def register_extractor(domain: str):
    """`@register_extractor('example.com')` on an `async fn(page, soup) -> dict`.

    Unregistered domains fall back to `generic_extractor`. The registry is the extension point:
    a real target gets a function that knows its DOM, and everything else still returns
    readable text.
    """
    def deco(fn: ExtractorFn) -> ExtractorFn:
        _extractors[domain] = fn
        return fn
    return deco


async def generic_extractor(page, soup) -> dict:
    """`innerText` plus any filled form fields — what a reader would see, not the markup."""
    text = await page.evaluate("document.body.innerText")
    fields = await page.evaluate(
        """() => Object.fromEntries(
            [...document.querySelectorAll('input,textarea,select')]
                .map(e => [e.name || e.id || e.type, e.value])
                .filter(([k, v]) => v)
        )"""
    )
    return {
        "title": soup.title.string.strip() if soup.title and soup.title.string else "",
        "text": text,
        "fields": fields,
    }


async def run_extractor(page) -> dict:
    _require("bs4")
    from bs4 import BeautifulSoup
    domain = urlparse(page.url).netloc
    fn = _extractors.get(domain, generic_extractor)
    return await fn(page, BeautifulSoup(await page.content(), "lxml"))


def extract_links(html: str, base_url: str, same_domain_only: bool) -> list[str]:
    _require("bs4")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    base_domain = urlparse(base_url).netloc
    out: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor["href"]).split("#")[0]
        if not href.startswith(("http://", "https://")):
            continue
        if same_domain_only and urlparse(href).netloc != base_domain:
            continue
        out.append(href)
    return out


async def wait_for_stable(page, quiet_ms: int = 500, timeout_ms: int = 8000) -> None:
    """Wait until the DOM stops changing for `quiet_ms`, or give up quietly.

    `domcontentloaded` fires long before a client-rendered page has content, and
    `networkidle` never settles on a page with a polling widget. Watching for the mutations to
    stop is the closest thing to "the page has finished". A timeout here is not an error — it
    means the page never went quiet, and extracting what is there beats extracting nothing.
    """
    _require("playwright")
    from playwright.async_api import TimeoutError as PWTimeout
    try:
        await page.wait_for_function(
            """() => new Promise(resolve => {
                let timer;
                const obs = new MutationObserver(() => {
                    clearTimeout(timer);
                    timer = setTimeout(() => { obs.disconnect(); resolve(true); }, %d);
                });
                obs.observe(document.body, {childList: true, subtree: true, attributes: true});
                timer = setTimeout(() => { obs.disconnect(); resolve(true); }, %d);
            })""" % (quiet_ms, quiet_ms),
            timeout=timeout_ms,
        )
    except PWTimeout:
        pass


# ==========================================================================
# Crawl
# ==========================================================================

@dataclass
class CrawlConfig:
    depth: int = 1
    same_domain_only: bool = True
    respect_robots: bool = True
    honor_crawl_delay: bool = True
    default_delay: float = 2.0
    per_domain_concurrency: int = 2
    max_attempts: int = 3
    base_backoff: float = 1.5
    max_backoff: float = 20.0
    workers: int = 4
    headless: bool = True


async def fetch_one(page, url: str, cfg: CrawlConfig) -> tuple[FetchResult, list[str]]:
    _require("playwright")
    from playwright.async_api import TimeoutError as PWTimeout
    last_error = ""
    for attempt in range(1, cfg.max_attempts + 1):
        try:
            await page.goto(url, timeout=DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
            await wait_for_stable(page)
            data = await run_extractor(page)
            links = extract_links(await page.content(), url, cfg.same_domain_only)
            return FetchResult(status="ok", attempts=attempt, **data), links
        except PWTimeout:
            last_error = "timeout"
        except Exception as exc:
            last_error = str(exc)
        if attempt < cfg.max_attempts:
            backoff = min(cfg.base_backoff * (2 ** (attempt - 1)), cfg.max_backoff)
            log.warning("retry %d/%d for %s after %s (%.1fs backoff)",
                        attempt, cfg.max_attempts, url, last_error, backoff)
            await asyncio.sleep(backoff)
    return FetchResult(status="error", error=last_error, attempts=cfg.max_attempts), []


async def worker(name: str, context, store: Store, throttle: DomainThrottle,
                 cfg: CrawlConfig, shutdown: asyncio.Event) -> None:
    """One browser tab, draining the shared queue until it is empty or shutdown is set.

    The whole body is inside `try/finally` so the tab is closed on every exit path. The draft
    this came from returned early in three places — empty queue, shutdown mid-flight — and each
    of those leaked a tab. Four workers over a long run leaks four, and Chromium does not
    reclaim them.
    """
    page = await context.new_page()
    log_ = logging.getLogger(name)
    try:
        while not shutdown.is_set():
            batch = await store.dequeue_batch(1)
            if not batch:
                await asyncio.sleep(0.5)
                if store.queue_depth() == 0:
                    return
                continue

            url, depth, snippet, rank, query = batch[0]
            if await store.seen(url):
                continue

            if cfg.respect_robots:
                allowed, crawl_delay = await robots_check(url)
                if not allowed:
                    log_.info("SKIP  %s  (robots.txt disallows)", url)
                    await store.save(url, depth,
                                     FetchResult(status="skipped", error="robots.txt"),
                                     snippet, rank, query)
                    continue
                if cfg.honor_crawl_delay and crawl_delay:
                    throttle.set_delay(urlparse(url).netloc, crawl_delay)

            sem = await throttle.acquire(url)
            try:
                if shutdown.is_set():
                    # Put it back rather than dropping it: the queue is the resume point, and
                    # a URL dequeued-but-never-saved would be lost on the next run.
                    await store.requeue(url, depth, snippet, rank, query)
                    return
                result, links = await fetch_one(page, url, cfg)
            finally:
                throttle.release(sem)

            await store.save(url, depth, result, snippet, rank, query)

            if result.status == "ok":
                log_.info("OK    %s  (%d chars, depth %d)", url, len(result.text), depth)
                if depth < cfg.depth:
                    for link in links:
                        if not await store.seen(link):
                            # `query` is carried down so that `answer` can see pages found by
                            # following a link, not only the seeds. Rank 0 marks "not ranked by
                            # anyone" and `get_pages_for_query` sorts on that.
                            await store.enqueue(link, depth + 1, query=query)
            else:
                log_.error("FAIL  %s  (%s)", url, result.error)
    finally:
        await page.close()


async def run_crawl(store: Store, cfg: CrawlConfig) -> None:
    """Start the browser, run `cfg.workers` tabs against the queue, and always drain first.

    **The browser context is closed only after every worker has stopped.** `asyncio.wait` with
    `FIRST_EXCEPTION` returns as soon as the first task *finishes* — which on a healthy run is
    the first worker to find the queue empty, with three still fetching. Closing the context
    there tears the browser out from under them and the run ends in a pile of
    `TargetClosedError` that looks like a crawler bug rather than a shutdown ordering bug. So
    the pending set is always awaited, on both the healthy and the failed path.
    """
    _require("playwright")
    from playwright.async_api import async_playwright

    throttle = DomainThrottle(default_delay=cfg.default_delay,
                              per_domain_concurrency=cfg.per_domain_concurrency)
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown.set)
        except (NotImplementedError, RuntimeError):
            # Not available on every platform, and not available at all off the main thread.
            pass

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=cfg.headless, user_agent=USER_AGENT)
        tasks = [asyncio.create_task(worker(f"worker-{i}", context, store, throttle, cfg,
                                            shutdown))
                 for i in range(cfg.workers)]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            crashed = [t.exception() for t in done if t.exception()]
            for exc in crashed:
                log.error("Worker crashed: %s", exc)
            if crashed or shutdown.is_set():
                # A crash is a reason to stop the others, not to abandon them mid-fetch.
                shutdown.set()
                log.info("Stopping — waiting for %d in-flight worker(s).", len(pending))
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        finally:
            await context.close()

    remaining = store.queue_depth()
    if remaining:
        log.info("Stopped with %d URL(s) still queued. Run the same command again to resume.",
                 remaining)
    else:
        log.info("Crawl complete — queue empty.")


async def interactive_login(url: str) -> None:
    """A visible browser, a human logging in, and a profile that outlives the process.

    Deliberately manual. This is the CAPTCHA-and-2FA path, and the tool's position is that a
    person does that part; nothing here automates it.
    """
    _require("playwright")
    from playwright.async_api import async_playwright
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, user_agent=USER_AGENT)
        page = await context.new_page()
        await page.goto(url)
        print("Log in manually in the opened browser window.")
        await asyncio.to_thread(input, "Press Enter once logged in... ")
        await context.close()
    print(f"Session saved to {PROFILE_DIR}.")


# ==========================================================================
# Answer synthesis
# ==========================================================================

ANSWER_SYSTEM_PROMPT = """You answer questions using ONLY the source excerpts provided below. \
Each excerpt is labeled with a number.

Rules:
- Cite every claim with its source number in brackets, e.g. [2].
- If the excerpts don't support an answer, or conflict, say so explicitly rather than guessing \
or filling the gap from general knowledge.
- Do not state anything as fact that isn't traceable to a specific excerpt.
- Keep the answer proportional to what the sources actually support."""


def build_answer_prompt(query: str, pages: list[dict], max_chars: int = 3000) -> str:
    """Numbered excerpts, so `[2]` in the answer resolves to a URL in the output.

    Falling back to `snippet` when `text` is empty is what keeps the numbering contiguous: a
    page that failed to render would otherwise appear as a labelled blank, and a citation to
    an empty source is worse than one fewer source.
    """
    sources = []
    for i, page in enumerate(pages, 1):
        excerpt = (page.get("text") or page.get("snippet") or "")[:max_chars]
        sources.append(f"[{i}] {page.get('title', '')}\nURL: {page['url']}\n{excerpt}")
    return f"Question: {query}\n\nSources:\n\n" + "\n\n---\n\n".join(sources)


def synthesize_answer(query: str, pages: list[dict], api_key: Optional[str] = None) -> str:
    """A cited answer, or a string saying exactly what is missing.

    This one returns its failure instead of raising, unlike the crawl paths. The pages are
    already fetched and stored by the time this runs, and losing them to a missing key would
    mean re-crawling. `answer` writes the sources out either way.
    """
    if not pages:
        return "[no rendered pages for this query — nothing to synthesise from]"
    try:
        anthropic = importlib.import_module("anthropic")
    except ImportError:
        return (f"[answer synthesis skipped: anthropic is not installed. "
                f"{_INSTALL_HINT['anthropic']}]")
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return "[answer synthesis skipped: set ANTHROPIC_API_KEY in symoneural-discovery.env]"
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=SYNTH_MODEL, max_tokens=1000, system=ANSWER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_answer_prompt(query, pages)}],
    )
    return resp.content[0].text


# ==========================================================================
# Orchestration
# ==========================================================================

def _anthropic_client_or_none():
    """A client if both the package and a key exist, else `None` — never a raise.

    Only ever used for query expansion, which is optional by design.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return importlib.import_module("anthropic").Anthropic()
    except Exception:
        return None


async def discover(query: str, backends: list[SearchBackend], n: int, expand: int,
                   store: Store, cache_ttl: float, retry: RetryConfig,
                   cfg: CrawlConfig) -> None:
    queries = expand_query(query, expand, _anthropic_client_or_none() if expand > 1 else None)
    log.info("Query variants: %s", queries)

    hits = (await fan_out_search(backends, queries, n, store, cache_ttl, retry))[:n]
    log.info("Seeding %d URL(s) from search into the crawl queue.", len(hits))
    for hit in hits:
        if not await store.seen(hit.url):
            await store.enqueue(hit.url, 0, snippet=hit.snippet, rank=hit.rank, query=query)

    await run_crawl(store, cfg)


# ==========================================================================
# CLI
# ==========================================================================

def _add_crawl_flags(parser: argparse.ArgumentParser, default_depth: int) -> None:
    """The crawl knobs, added to three subcommands from one place.

    `discover` and `answer` default to depth 0 — search results only, no link following —
    because that is what "look this up" means; `crawl` defaults to 1 because a seed list with
    no following would just be a fetch list.
    """
    parser.add_argument("--depth", type=int, default=default_depth,
                        help="Extra link-following depth past the seed pages.")
    parser.add_argument("--same-domain", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--per-domain-concurrency", type=int, default=2)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument("--ignore-crawl-delay", action="store_true")


def _add_search_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backends", nargs="+", choices=list(BACKEND_NAMES),
                        default=["duckduckgo"])
    parser.add_argument("--n", type=int, default=5, help="Number of search results.")
    parser.add_argument("--expand", type=int, default=1, help="Query phrasings to fan out.")
    parser.add_argument("--cache-ttl", type=float, default=3600)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="symoneural-discovery", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite path.")
    parser.add_argument("--env", default=None,
                        help="Env file to load (default: symoneural-discovery.env beside "
                             "this package, or $SYMONEURAL_DISCOVERY_ENV).")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="Open a visible browser to log in and save the session.")
    login.add_argument("url")

    search_p = sub.add_parser("search", help="Search backends only — no page fetching.")
    search_p.add_argument("query")
    _add_search_flags(search_p)
    search_p.add_argument("--retries", type=int, default=3)
    search_p.add_argument("--out", default=None)

    disc = sub.add_parser("discover", help="Search, then crawl and render each result.")
    disc.add_argument("query")
    _add_search_flags(disc)
    _add_crawl_flags(disc, default_depth=0)

    crawl_p = sub.add_parser("crawl", help="Crawl from --seeds or --sitemap. No search step.")
    seeds = crawl_p.add_mutually_exclusive_group(required=True)
    seeds.add_argument("--seeds", metavar="FILE")
    seeds.add_argument("--sitemap", metavar="URL")
    _add_crawl_flags(crawl_p, default_depth=1)

    answer_p = sub.add_parser("answer", help="Discover, then synthesise a cited answer.")
    answer_p.add_argument("query")
    _add_search_flags(answer_p)
    _add_crawl_flags(answer_p, default_depth=0)
    answer_p.add_argument("--out", default=None)

    export_p = sub.add_parser("export", help="Write the pages table to a JSON file.")
    export_p.add_argument("--out", default="results.json")

    sub.add_parser("stats", help="Counts by status, queue depth, cache size, dependencies.")
    return parser


def _crawl_config(args: argparse.Namespace) -> CrawlConfig:
    return CrawlConfig(
        depth=args.depth, same_domain_only=args.same_domain,
        respect_robots=not args.ignore_robots,
        honor_crawl_delay=not args.ignore_crawl_delay,
        default_delay=args.delay, per_domain_concurrency=args.per_domain_concurrency,
        max_attempts=args.retries, workers=args.workers, headless=not args.headed,
    )


async def async_main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # Before anything reads os.environ. `load` returns key NAMES and never values, so this log
    # line is safe in a transcript, a CI log or a pasted bug report.
    from . import envfile  # noqa: PLC0415 -- relative, and only when run as a package
    loaded = envfile.load(args.env)
    if loaded:
        log.info("Loaded %d name(s) from %s: %s",
                 len(loaded), envfile.resolve_path(args.env), ", ".join(sorted(loaded)))

    if args.command == "login":
        await interactive_login(args.url)
        return 0

    store = Store(Path(args.db))
    try:
        if args.command == "search":
            queries = expand_query(args.query, args.expand,
                                   _anthropic_client_or_none() if args.expand > 1 else None)
            backends = [build_backend(b) for b in args.backends]
            hits = (await fan_out_search(backends, queries, args.n, store, args.cache_ttl,
                                         RetryConfig(args.retries)))[:args.n]
            text = json.dumps([h.__dict__ for h in hits], indent=2, ensure_ascii=False)
            if args.out:
                Path(args.out).write_text(text)
                log.info("%d result(s) -> %s", len(hits), args.out)
            else:
                print(text)
            # Zero results is not success. A shell loop should be able to tell the difference
            # between "nothing matched" and "the backend's markup changed" without parsing logs.
            return 0 if hits else 1

        if args.command == "discover":
            await discover(args.query, [build_backend(b) for b in args.backends], args.n,
                           args.expand, store, args.cache_ttl, RetryConfig(args.retries),
                           _crawl_config(args))
            return 0

        if args.command == "crawl":
            if args.sitemap:
                seeds = await discover_sitemap_urls(args.sitemap)
                log.info("Found %d URL(s) in sitemap.", len(seeds))
            else:
                seeds = [ln.strip() for ln in Path(args.seeds).read_text().splitlines()
                         if ln.strip() and not ln.strip().startswith("#")]
            if not seeds:
                print("No seed URLs found.", file=sys.stderr)
                return 1
            for url in seeds:
                if not await store.seen(url):
                    await store.enqueue(url, 0)
            await run_crawl(store, _crawl_config(args))
            return 0

        if args.command == "answer":
            await discover(args.query, [build_backend(b) for b in args.backends], args.n,
                           args.expand, store, args.cache_ttl, RetryConfig(args.retries),
                           _crawl_config(args))
            pages = store.get_pages_for_query(args.query)
            answer = synthesize_answer(args.query, pages)
            payload = {"query": args.query, "answer": answer, "sources": pages}
            if args.out:
                Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
                log.info("Answer + %d source(s) -> %s", len(pages), args.out)
            else:
                print("\n=== ANSWER ===\n")
                print(answer)
                print("\n=== SOURCES ===")
                for i, page in enumerate(pages, 1):
                    print(f"[{i}] {page.get('title', '')} — {page['url']}")
            return 0

        if args.command == "export":
            count = store.export(Path(args.out))
            log.info("Exported %d record(s) -> %s", count, args.out)
            return 0

        if args.command == "stats":
            print(json.dumps(store.stats(), indent=2))
            return 0
    finally:
        store.close()

    return 2  # unreachable while every subparser is handled; a wrong exit code, not a crash


def main(argv: Optional[list[str]] = None) -> int:
    try:
        return asyncio.run(async_main(argv))
    except MissingDependency as exc:
        # The one exception with a fix in it. Printed as the whole message rather than a
        # traceback, because the useful part is the install command and a traceback buries it.
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    if __package__ in (None, ""):
        # Run as a path (`python3 discovery.py`) rather than `-m`: the relative import of
        # envfile needs a package, so give it one by name instead of failing at the first
        # `from . import`.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        __package__ = "discovery"
        importlib.import_module(__package__)
    raise SystemExit(main())
