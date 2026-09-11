"""Tests for the news collector. Offline, stdlib only, no network.

Offline is a requirement, not a convenience. `pytest apps/` runs on every commit and a suite
that fetched thirteen third-party feeds would fail on a train, hammer publishers who owe us
nothing, and turn a red run into a question about somebody else's CDN. Every fixture below is
a trimmed real response -- the Bing item is the shape that made the Bing arm return zero items
on the first live pass, the PyTorch entries are the CI tags that got that source removed.

The one test here that is about security rather than correctness is
`test_no_environment_variable_can_change_the_host_fetched`. It is the reason `check_host` is a
module-level function instead of an inline check.
"""
from __future__ import annotations

import itertools
import pathlib
import re
import time

import pytest

from .apps import collect
from .apps import feeds
from .lib import fetch
from .apps import rank
from .apps.parse import Item, clean, parse_feed

HERE = pathlib.Path(__file__).resolve().parent


# --------------------------------------------------------------------------- fixtures

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>&lt;b&gt;Qwen3&lt;/b&gt; model release</title>
      <link>https://example.com/a</link>
      <pubDate>Tue, 19 Aug 2026 10:00:00 +0000</pubDate></item>
<item><title>Undated GPU launch</title><link>https://example.com/b</link></item>
<item><title>Plaintext link, unknown host</title><link>http://example.com/c</link></item>
<item><title>Dated by dublin core, model release</title>
      <link>https://example.com/d</link><dc:date>2026-08-18T09:30:00Z</dc:date></item>
<item><link>https://example.com/e</link><pubDate>Tue, 19 Aug 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>b10524</title>
       <link rel="alternate" href="https://github.com/ggml-org/llama.cpp/releases/tag/b10524"/>
       <updated>2026-08-20T01:02:03Z</updated></entry>
<entry><title>viable/strict/1787216473</title>
       <link rel="alternate" href="https://github.com/pytorch/pytorch/releases/tag/x"/>
       <updated>2026-08-20T01:02:03Z</updated></entry>
</feed>"""

# The shape that broke the Bing arm: an http:// click-tracker on a host we fetched over TLS,
# and the publisher in a namespaced element whose namespace URI is the request URL itself.
BING = """<?xml version="1.0" encoding="utf-8" ?>
<rss version="2.0" xmlns:News="https://www.bing.com/news/search?q=x&amp;format=RSS"><channel>
<item><title>Humanoid robots reach the factory floor - Bing</title>
      <link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=6a8</link>
      <pubDate>Thu, 20 Aug 2026 01:21:59 GMT</pubDate>
      <News:Source>CNBC on MSN</News:Source></item>
</channel></rss>"""

GOOGLE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Nvidia ships new GPU - Tom&apos;s Hardware</title>
      <link>https://news.google.com/rss/articles/xyz</link>
      <pubDate>Wed, 20 Aug 2026 04:00:00 GMT</pubDate></item>
<item><title>The model is fast - and that is the whole problem here</title>
      <link>https://www.theverge.com/p</link>
      <pubDate>Wed, 20 Aug 2026 04:00:00 GMT</pubDate></item>
</channel></rss>"""


def _item(title, url="https://example.com/x", source="Test", topic="search",
          at=None, weight=1.0):
    return Item(title, url, source, topic, time.time() if at is None else at, weight)


# ------------------------------------------------------------------ the security property

def test_no_environment_variable_can_change_the_host_fetched(monkeypatch):
    """The operator may set queries. The operator may not set a host.

    This box has a public IP and the collector makes unauthenticated outbound requests, so an
    env-settable URL would be a request-forgery primitive. Each query below is a real attempt
    at one.
    """
    attacks = [
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/",
        "x&q=http://127.0.0.1:8800/api/status",
        "x#@evil.example.com/",
        "../../../../etc/passwd",
        "x' onload='fetch(\"http://127.0.0.1:8188/prompt\")",
        "http://[::1]:22/",
        "\n\rHost: evil.example.com",
    ]
    monkeypatch.setenv(collect.ENV_QUERIES, ",".join(attacks))
    got = collect.queries()
    assert got, "the sanitiser must not silently empty the query list"
    for query in got:
        for engine in feeds.SEARCHES:
            url = collect.search_url(engine.template, query)
            # search_url calls check_host itself, so reaching here is already the assertion.
            # Naming the expected host as well is what makes a future template edit that
            # points somewhere else fail here rather than at runtime.
            assert fetch.check_host(url) in feeds.HOSTS


def test_no_url_anywhere_in_this_package_comes_from_the_environment():
    """Every http(s) literal lives in feeds.py, and nothing reads a URL from os.environ.

    The test above proves the templates are safe. This one proves there is no second path --
    a later `os.environ.get("SYMONEURAL_NEWS_EXTRA_FEED")` would pass every other test in this
    file while reopening exactly the hole they exist to close.
    """
    allowed_env = {collect.ENV_OFF, collect.ENV_QUERIES,
                   "SYMONEURAL_NEWS_ENABLED", "SYMONEURAL_NEWS_INTERVAL_S"}
    seen_env: set[str] = set()
    for path in sorted(HERE.glob("*.py")):
        if path.name == "test_news.py":
            # This file names SYMONEURAL_NEWS_EXTRA_FEED in a docstring as the example of what
            # must never appear, and scanning itself reported that mention as the offence.
            continue
        src = path.read_text()
        seen_env |= set(re.findall(r"environ(?:\.get)?\(\s*['\"]([A-Z_]+)['\"]", src))
        seen_env |= set(re.findall(r"ENV_\w+\s*=\s*['\"]([A-Z_]+)['\"]", src))
        if path.name == "feeds.py":
            continue
        for hit in re.findall(r"['\"]https?://[^'\"]+['\"]", src):
            pytest.fail(f"{path.name} carries a URL literal {hit}; feeds.py owns those")
    unexpected = seen_env - allowed_env
    assert not unexpected, f"unrecognised env var(s) read by this package: {unexpected}"


def test_search_url_refuses_a_template_that_points_somewhere_else():
    """`search_url` validates the URL it built, not just the query it was given.

    The check is redundant with the one inside `fetch.get`, and a mutation that deleted it
    passed every other test in this file for exactly that reason. It is kept because it is
    what makes an edit to SEARCHES fail at the point of the edit, and pinned here because
    "redundant" and "untested" are not the same word.
    """
    with pytest.raises(fetch.HostNotAllowed):
        collect.search_url("https://evil.example.com/?q={q}", "robotics")
    with pytest.raises(fetch.HostNotAllowed):
        collect.search_url("http://news.google.com/rss/search?q={q}", "robotics")


def test_every_feed_url_is_https_and_its_host_is_named():
    for src in feeds.SOURCES:
        assert fetch.check_host(src.url) in feeds.HOSTS
        assert src.topic in feeds.TOPICS
    for eng in feeds.SEARCHES:
        assert eng.template.count("{q}") == 1, f"{eng.name} must interpolate exactly one query"
        assert fetch.check_host(eng.template.format(q="probe")) in feeds.HOSTS


def test_a_host_that_is_not_named_is_refused():
    for url in ["https://evil.example.com/x",
                "https://github.com.evil.example/x",   # suffix confusion
                "http://github.com/x",                 # correct host, plaintext
                "https://raw.githubusercontent.com/x", # a GitHub host, still not ours
                "file:///etc/passwd"]:
        with pytest.raises(fetch.HostNotAllowed):
            fetch.check_host(url)


def test_redirects_are_host_checked_rather_than_followed_blindly():
    """The opener must carry the checking handler.

    GitHub already 301s one of our sources to a different org path; the next project to move
    will not warn us either. Without this handler the validated host and the answering host
    are different things.
    """
    assert any(isinstance(h, fetch._HostCheckedRedirect) for h in fetch._opener.handlers)
    handler = fetch._HostCheckedRedirect()
    with pytest.raises(fetch.HostNotAllowed):
        handler.redirect_request(None, None, 301, "Moved", {},
                                 "https://evil.example.com/steal")


def test_the_read_is_capped_well_above_the_largest_real_feed():
    # Not a network test. The largest feed measured on 2026-08-20 was
    # huggingface/transformers' releases.atom at 973 KB; the cap has to leave a feed room to
    # grow without leaving the box room to be exhausted.
    assert 2 * 1024 * 1024 <= fetch.MAX_BYTES <= 16 * 1024 * 1024
    assert 5.0 <= fetch.TIMEOUT_S <= 30.0
    assert "symoneural.com" in fetch.USER_AGENT, "a fetcher must be identifiable"


# ------------------------------------------------------------------------------- parsing

def test_rss_is_parsed_with_entities_resolved_and_tags_removed():
    got = parse_feed(RSS, "Test", "releases", 1.0)
    titles = [i.title for i in got]
    assert "Qwen3 model release" in titles, "markup must not reach the bar"
    assert all("<" not in t for t in titles)


def test_an_item_with_no_usable_date_is_dated_zero_not_now():
    """A dateless item must not float to the top of a live ticker."""
    got = {i.title: i for i in parse_feed(RSS, "Test", "releases", 1.0)}
    assert got["Undated GPU launch"].at == 0.0
    assert got["Qwen3 model release"].at > 0.0


def test_a_plaintext_link_on_an_unknown_host_is_dropped_not_guessed():
    titles = [i.title for i in parse_feed(RSS, "Test", "releases", 1.0)]
    assert "Plaintext link, unknown host" not in titles


def test_a_plaintext_link_is_upgraded_only_for_a_host_we_fetched_over_tls():
    got = parse_feed(BING, "Bing News", "search", 0.95, credit_from_title=True)
    assert len(got) == 1, "the Bing arm returned zero items until this upgrade existed"
    assert got[0].url.startswith("https://www.bing.com/")


def test_dublin_core_dates_and_missing_titles_are_both_handled():
    got = parse_feed(RSS, "Test", "releases", 1.0)
    dated = [i for i in got if i.title.startswith("Dated by dublin core")]
    assert dated and dated[0].at > 0.0
    assert all(i.title for i in got), "an item with no title must be dropped, not blank"


def test_atom_entries_read_their_link_from_the_href_attribute():
    got = parse_feed(ATOM, "llama.cpp", "releases", 1.35)
    assert got[0].url.endswith("/releases/tag/b10524")
    assert got[0].at > 0.0


def test_a_declared_publisher_beats_one_inferred_from_the_title():
    got = parse_feed(BING, "Bing News", "search", 0.95, credit_from_title=True)
    assert got[0].source == "CNBC on MSN"
    assert got[0].title.endswith("factory floor"), "the ' - Bing' tail is not part of the news"


def test_a_publisher_is_split_off_a_google_title_but_a_clause_is_not():
    got = {i.url: i for i in parse_feed(GOOGLE, "Google News", "search", 1.0,
                                        credit_from_title=True)}
    ships = got["https://news.google.com/rss/articles/xyz"]
    assert ships.source == "Tom's Hardware" and ships.title == "Nvidia ships new GPU"
    clause = got["https://www.theverge.com/p"]
    assert clause.title.endswith("the whole problem here"), "a clause is not a masthead"


def test_markdown_escapes_in_titles_are_unescaped_but_paths_survive():
    assert clean(r"LFM2.5 Q4\_0 Checkpoints") == "LFM2.5 Q4_0 Checkpoints"
    assert clean(r"Use C:\path\to\thing") == r"Use C:\path\to\thing"


# ------------------------------------------------------------------------------ ranking

def test_an_open_source_item_with_nothing_on_topic_is_dropped():
    now = time.time()
    assert rank.score(_item("My cat has a blog", topic="technology"), now) == 0.0
    assert rank.score(_item("New humanoid robot walks on gravel"), now) > 0.0


def test_a_release_feed_is_trusted_without_a_keyword_match():
    """`b10524` matches no vocabulary and is still the most newsworthy item on the bar."""
    now = time.time()
    assert rank.score(_item("b10524", topic="releases", at=now), now) > 0.0


def test_a_ci_branch_tag_is_not_news():
    now = time.time()
    for title in ["viable/strict/1787216473",
                  "trunk/557649f7767c6e7bcbbf2bc9f7c89b6aae199e30: Fix grammar",
                  "nightly/2026-08-20"]:
        assert rank.score(_item(title, topic="releases"), now) == 0.0, title
    # And the guard must not eat an ordinary headline that happens to contain a slash.
    assert rank.score(_item("main_st/robotics is great", topic="releases"), now) > 0.0


def test_recency_decays_rather_than_cutting_off():
    now = time.time()
    fresh = rank.score(_item("model release", topic="releases", at=now), now)
    old = rank.score(_item("model release", topic="releases",
                           at=now - rank.HALF_LIFE_S), now)
    assert fresh / 2 == pytest.approx(old, rel=0.02)


def test_an_undated_item_can_appear_but_never_leads():
    now = time.time()
    undated = rank.score(_item("GPU launch", topic="hardware", at=0.0), now)
    fresh = rank.score(_item("GPU launch", topic="hardware", at=now), now)
    assert 0.0 < undated < fresh / 2


def test_the_same_story_from_three_engines_takes_one_slot():
    now = time.time()
    rows = rank.rank([
        _item("New humanoid robot walks on gravel", "https://x.example/r", "Reuters", at=now),
        _item("New humanoid robot walks on gravel", "https://x.example/r?utm_source=bing",
              "Bing", at=now),
        _item("New humanoid robot walks on gravel today", "https://other.example/r2",
              "Yahoo", at=now),
    ], now)
    assert len(rows) == 1, [r["source"] for r in rows]


def test_no_publisher_and_no_topic_can_take_over_the_bar():
    now = time.time()
    flood = [_item(f"humanoid robot story {n}", f"https://x.example/{n}", "digitimes",
                   at=now - n) for n in range(30)]
    flood += [_item(f"new humanoid robot number {n}", f"https://y.example/{n}", f"pub{n}",
                    at=now - n) for n in range(30)]
    rows = rank.rank(flood, now)
    # Literal numbers, not rank.PER_SOURCE / rank.PER_TOPIC. Asserting against the constants
    # made this test pass when the constants were mutated to 999 -- the assertion moved with
    # the thing it was supposed to pin. If these numbers are deliberately changed, this test
    # is supposed to be the thing that makes you say so.
    assert sum(1 for r in rows if r["source"] == "digitimes") <= 2
    assert sum(1 for r in rows if r["topic"] == "robotics") <= 8
    assert rank.PER_SOURCE == 2 and rank.PER_TOPIC == 8


def test_a_week_old_story_is_dropped_rather_than_padding_the_bar():
    now = time.time()
    week = now - 7 * 86400
    rows = rank.rank([_item("model release", f"https://x.example/{n}", f"pub{n}", at=week)
                      for n in range(10)], now)
    assert rows == []


def test_the_bar_does_not_read_as_one_topic_repeated():
    """Selection is by score; order is interleaved. Eight consecutive robotics chips is what
    the first live pass produced, and it is why _interleave exists."""
    now = time.time()
    items = [_item(f"humanoid robot {n}", f"https://r.example/{n}", f"rpub{n}", at=now - n)
             for n in range(6)]
    items += [_item(f"model release {n}", f"https://m.example/{n}", f"mpub{n}",
                    topic="releases", at=now - 3600 - n) for n in range(6)]
    rows = rank.rank(items, now)
    longest = max(len(list(g)) for _, g in itertools.groupby(r["topic"] for r in rows))
    assert longest == 1, [r["topic"] for r in rows]
    # Not "robotics is first": `model release N` matches two vocabularies where `humanoid
    # robot N` matches one, so the releases items legitimately outscore the robotics ones and
    # the first assertion of this test was simply wrong about which. What has to hold is that
    # interleaving reorders without demoting the best item.
    assert rows[0]["score"] == max(r["score"] for r in rows)


def test_the_payload_keys_are_the_wire_format():
    """ui.js reads these names. Renaming one breaks the bar and nothing else notices."""
    now = time.time()
    rows = rank.rank([_item("new humanoid robot", at=now)], now)
    assert set(rows[0]) == {"title", "url", "source", "topic", "at", "score"}
    assert rows[0]["topic"] in feeds.TOPICS


def test_the_chip_says_what_the_item_matched_when_the_source_is_open():
    now = time.time()
    rows = rank.rank([_item("Geolocating an island with CUDA", source="Hacker News",
                            topic="technology", at=now)], now)
    assert rows[0]["topic"] == "hardware", "an open source's chip must describe the item"


# -------------------------------------------------------------------- operator controls

def test_queries_default_when_unset_and_are_capped_when_set(monkeypatch):
    monkeypatch.delenv(collect.ENV_QUERIES, raising=False)
    assert collect.queries() == feeds.DEFAULT_QUERIES
    monkeypatch.setenv(collect.ENV_QUERIES, ",".join(f"query {n}" for n in range(50)))
    assert len(collect.queries()) == collect.MAX_QUERIES
    monkeypatch.setenv(collect.ENV_QUERIES, "x" * 5000)
    assert len(collect.queries()[0]) == collect.MAX_QUERY_LEN
    monkeypatch.setenv(collect.ENV_QUERIES, "  ,  ,  ")
    assert collect.queries() == feeds.DEFAULT_QUERIES, "an empty list falls back, not silent"


def test_a_source_can_be_switched_off_by_name_but_not_added(monkeypatch):
    monkeypatch.setenv(collect.ENV_OFF, "arXiv cs.LG, Hacker News")
    off = collect.disabled()
    assert "arxiv cs.lg" in off and "hacker news" in off
    # There is no ENV that adds one. This asserts the absence, which is the point.
    assert not any("ADD" in name or "EXTRA" in name or "URL" in name
                   for name in vars(collect) if name.startswith("ENV_"))


def test_the_interval_is_clamped_in_both_directions(monkeypatch):
    from . import interval_s
    monkeypatch.setenv("SYMONEURAL_NEWS_INTERVAL_S", "1")
    assert interval_s() == pytest.approx(300.0)
    monkeypatch.setenv("SYMONEURAL_NEWS_INTERVAL_S", "999999")
    assert interval_s() == pytest.approx(21600.0)
    monkeypatch.setenv("SYMONEURAL_NEWS_INTERVAL_S", "banana")
    assert interval_s() == pytest.approx(900.0)


def test_the_surface_is_off_unless_the_switch_is_set(monkeypatch):
    from . import enabled
    monkeypatch.delenv("SYMONEURAL_NEWS_ENABLED", raising=False)
    assert enabled() is False
    monkeypatch.setenv("SYMONEURAL_NEWS_ENABLED", "true")
    assert enabled() is False, "only '1' counts, as everywhere else in this repo"
    monkeypatch.setenv("SYMONEURAL_NEWS_ENABLED", "1")
    assert enabled() is True


# ---------------------------------------------------------------------------- the cache

def test_an_empty_cache_reports_itself_stale_and_carries_no_items():
    from . import NewsCache
    got = NewsCache().get(now=1000.0)
    assert got["items"] == [] and got["count"] == 0
    assert got["stale"] is True and got["age_s"] is None


def test_a_failed_pass_keeps_the_last_good_items_and_says_so():
    """Every source failing must not blank the bar, and must not pretend to be current."""
    from . import NewsCache
    cache = NewsCache()
    cache.put([{"title": "t", "url": "u", "source": "s", "topic": "releases",
                "at": 900.0, "score": 1.0}], [{"source": "s", "state": "ok"}], now=1000.0)
    cache.fail([{"source": "s", "state": "error"}], "all thirteen down", now=1100.0)
    got = cache.get(now=1100.0)
    assert got["count"] == 1, "old news is better than no news, if it is labelled"
    assert got["error"] == "all thirteen down"
    assert got["sources"][0]["state"] == "error"


def test_a_stale_cache_labels_itself(monkeypatch):
    from . import NewsCache
    monkeypatch.setenv("SYMONEURAL_NEWS_INTERVAL_S", "900")
    cache = NewsCache()
    cache.put([{"title": "t", "url": "u", "source": "s", "topic": "releases",
                "at": 1000.0, "score": 1.0}], [], now=1000.0)
    assert cache.get(now=1000.0 + 900)["stale"] is False, "one late refresh is not stale"
    fresh_enough = cache.get(now=1000.0 + 1300)
    assert fresh_enough["stale"] is False
    missed = cache.get(now=1000.0 + 1400)
    assert missed["stale"] is True, "a refresh missed entirely has to show"
    assert missed["age_s"] == pytest.approx(1400.0)
    # And the age of the newest item is served too, because that -- not the fetch time -- is
    # what makes the word "live" on the bar true or false.
    assert missed["newest_age_s"] == pytest.approx(1400.0)


def test_the_request_budget_in_the_comments_matches_the_source_list():
    """The two politeness figures are recomputed here, not trusted where they are written.

    `__init__.py` states a per-pass request count and an hourly rate, and `collect.py` states
    the ceiling `MAX_QUERIES` imposes. Both were written when `SOURCES` held eight publishers
    and both were wrong -- 32 fetches over seven hosts -- from the moment it held ten. A figure
    in a comment that nothing checks is a claim, and this file's whole argument is that the
    numbers in this repo are checkable, so the comment is now pinned to the tuples that produce
    it. If a source or a default query is added, this fails and names the new arithmetic.
    """
    from . import DEFAULT_INTERVAL_S

    per_pass = len(feeds.SOURCES) + len(feeds.SEARCHES) * len(feeds.DEFAULT_QUERIES)
    ceiling = len(feeds.SOURCES) + len(feeds.SEARCHES) * collect.MAX_QUERIES
    hourly = round(per_pass * 3600 / DEFAULT_INTERVAL_S)
    hosts = len(feeds._hosts())

    init = (HERE / "__init__.py").read_text(encoding="utf-8")
    coll = (HERE / "collect.py").read_text(encoding="utf-8")
    assert f"a default pass is {per_pass} fetches" in init, \
        f"__init__.py's per-pass figure is not {per_pass}"
    assert f"~{hourly} requests an hour" in init, f"__init__.py's hourly figure is not {hourly}"
    # The prose spells the host count as a word, so the word is what is checked. Eight is not
    # a coincidence of ten sources: github.com carries five of them.
    words = {7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
    assert f"{words[hosts]} hosts" in init, f"__init__.py does not say {words[hosts]} hosts"
    assert f"The ceiling is {ceiling} a pass" in init, \
        f"__init__.py's ceiling figure is not {ceiling}"
    assert f"= {ceiling} fetches" in coll, f"collect.py's bound is not {ceiling}"

    # The first version of this test checked only that the right figures were PRESENT, and
    # `__init__.py` went on carrying two more stale ones underneath it: the module docstring
    # said the package talks to seven hosts, and `refresh_once` said 32 sequential fetches.
    # Presence is not enough when a file states the same quantity in three places, so the
    # remaining two are pinned by name and every wrong host word is forbidden outright.
    # Whitespace is collapsed first because both figures sit in wrapped prose -- the host
    # count was split across a line break as `talks to seven\n    hosts`, so a raw substring
    # search for "seven hosts" would not have found the sentence that was wrong.
    flat = " ".join(init.split())
    assert f"{per_pass} sequential fetches" in flat, \
        f"refresh_once's to_thread rationale is not {per_pass} fetches"
    for n, word in words.items():
        if n == hosts:
            continue
        assert f"{word} hosts" not in flat, \
            f"__init__.py still says {word} hosts somewhere; the count is {hosts}"
