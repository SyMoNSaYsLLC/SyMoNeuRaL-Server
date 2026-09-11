"""Where the news comes from. Every URL in this file is a literal, and that is a security property.

Garrett asked for an ESPN-style ticker carrying "new technology, models, releases, robotics,
hardware, betas, integrations etc etc", and said "I believe we will need a symoneural
webscraping agent and web search agent to accomplish this".

Two arms, one parser:

  SOURCES  -- publisher feeds. A fixed list of RSS/Atom endpoints that publish the things
              this site is about. This is the "scraping" arm, except that it is not
              scraping: these are documents the publishers built for exactly this purpose,
              which is why they are stable enough to put in a tuple.

  SEARCHES -- query templates. A query string goes out and ranked results come back, from
              public search feeds that need no key: Google News' RSS search, Bing News' RSS
              output, and hnrss' search. That is what "web search agent" means here --
              query -> public search feed -> parse. It is NOT a headless browser and it does
              not read a search engine's HTML results page. Saying so plainly is the point;
              this repo does not describe a capability as more than it is.

## Why the URLs are literals and the operator cannot add one

This box has a public IP and the collector makes unauthenticated outbound requests. If a
source list were env-settable, `SYMONEURAL_NEWS_SOURCES=http://169.254.169.254/...` would
turn a news ticker into a request-forgery primitive pointed at anything the box can reach.
So:

  * source URLs are literals here and there is no code path that reads a URL from anywhere
    else. `SYMONEURAL_NEWS_OFF` can switch a source OFF by name; nothing can switch a new
    one on.
  * queries ARE operator-settable, because a query is not a URL. They are percent-encoded
    and interpolated into the templates below, and `fetch.py` re-checks the resolved host
    against `HOSTS` before it connects, so a query that tries to escape its template fails
    a host check rather than reaching a host of its choosing.

`apps/news/test_news.py::test_no_environment_variable_can_change_the_host_fetched`
is the regression test for that, and it is the one test in this package that is about
security rather than about correctness.

## Why some of these are pinned to a redirect target

`github.com/comfyanonymous/ComfyUI/releases.atom` answers 301 to
`github.com/Comfy-Org/ComfyUI/releases.atom` -- the project moved organisations. The
redirect target is what is written down, so the host that gets validated is the host that
gets talked to. `fetch.py` still installs a host-checking redirect handler for the next time
a project moves without telling us.

`pytorch.org/blog/feed.xml` is the canonical path: `pytorch.org/feed.xml` and
`pytorch.org/rss.xml` both answer 404 with a 148 KB HTML body, which parses as nothing and
would have been a permanently-erroring source. `blog.pytorch.org` does not resolve at all and
must not be listed.

Every URL here answered 200 from this box on 2026-08-20, with the body sizes noted. Those
are single readings, not a promise: a feed that has gone away is a source that drops out of
a pass, which is why `refresh_once` treats a dead source as one missing source rather than
as a failed refresh.
"""
from __future__ import annotations

from typing import NamedTuple


class Source(NamedTuple):
    name: str          # shown on the ticker chip, so it has to be short and honest
    url: str
    topic: str         # one of TOPICS; drives the label, not the ranking
    weight: float      # a multiplier on the item score, see rank.py


# The publisher arm. `weight` is a judgement about signal density, not about quality: a
# releases.atom is almost entirely release announcements, so nearly every item is on topic,
# while a general aggregator carries one relevant story in ten.
SOURCES: tuple[Source, ...] = (
    # 69 KB. Release notes for the inference engine this box actually runs.
    Source("llama.cpp", "https://github.com/ggml-org/llama.cpp/releases.atom",
           "releases", 1.35),
    # 151 KB. NOT `github.com/pytorch/pytorch/releases.atom`, which was in this list until a
    # live pass showed what it actually publishes: ten CI branch tags -- `viable/strict/
    # 1787216473`, `trunk/557649f7...` -- and no releases at all. A feed whose every item is
    # a robot's bookmark is not a news source, and no keyword filter fixes that; the source
    # was wrong. The blog is what PyTorch writes for readers.
    Source("PyTorch", "https://pytorch.org/blog/feed.xml", "software", 1.15),
    # 15 KB. Ollama is the other local-inference runtime this stack's Studio backend speaks.
    Source("Ollama", "https://github.com/ollama/ollama/releases.atom", "releases", 1.1),
    # 973 KB -- the second largest here, and the reason fetch.MAX_BYTES has headroom rather
    # than being set just above the largest feed measured.
    Source("Transformers", "https://github.com/huggingface/transformers/releases.atom",
           "releases", 1.15),
    # Pinned past the 301 from comfyanonymous/ComfyUI. This is the image surface's engine.
    Source("ComfyUI", "https://github.com/Comfy-Org/ComfyUI/releases.atom",
           "releases", 1.3),
    Source("vLLM", "https://github.com/vllm-project/vllm/releases.atom",
           "releases", 1.15),
    # 249 KB. Model and dataset releases, which is the single most on-topic feed here.
    Source("Hugging Face", "https://huggingface.co/blog/feed.xml", "models", 1.3),
    # 739 KB -- the largest feed in the list and the reason fetch.py caps the read.
    Source("NVIDIA", "https://developer.nvidia.com/blog/feed", "hardware", 1.1),
    # 498 KB. Papers, so the least newsy and the most likely to be filtered out by rank.py's
    # topic test rather than by weight.
    Source("arXiv cs.LG", "https://export.arxiv.org/rss/cs.LG", "research", 0.8),
    # 20 KB. A general aggregator: low weight, high volume, and rank.py's topic filter is
    # what makes it useful rather than noise.
    Source("Hacker News", "https://hnrss.org/frontpage", "technology", 0.7),
)


class Search(NamedTuple):
    name: str
    template: str      # exactly one `{q}`, which is filled with a percent-encoded query
    topic: str
    weight: float


# The search arm. One `{q}` each, and `fetch.py` validates the host of the formatted result.
SEARCHES: tuple[Search, ...] = (
    Search("Google News", "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
           "search", 1.0),
    Search("Bing News", "https://www.bing.com/news/search?q={q}&format=RSS", "search", 0.95),
    Search("Hacker News", "https://hnrss.org/newest?q={q}&count=20", "search", 0.85),
)


# The default queries. Garrett's list, turned into search strings: "new technology, models,
# releases, robotics, hardware, betas, integrations etc etc". Overridable by
# SYMONEURAL_NEWS_QUERIES; the templates above are not.
DEFAULT_QUERIES: tuple[str, ...] = (
    "open source LLM release",
    "AI model release",
    "humanoid robotics",
    "GPU hardware launch",
    "AI developer beta",
    "model integration API",
)


# Every host this package is ever allowed to connect to. Derived from the tuples above
# rather than written out again, so a source added there cannot be reachable-but-unlisted or
# listed-but-unreachable. `fetch.py` checks against this set before connecting AND on every
# redirect.
def _hosts() -> frozenset[str]:
    from urllib.parse import urlsplit
    seen = {urlsplit(s.url).hostname for s in SOURCES}
    # The templates are formatted with an empty query only to read their host; the value of
    # `q` cannot change a URL's host, and the test asserts that.
    seen |= {urlsplit(s.template.format(q="")).hostname for s in SEARCHES}
    return frozenset(h for h in seen if h)


HOSTS = _hosts()

# The topics a chip can carry. `search` results get their topic from rank.py's keyword
# match instead of from the source, because "what did this query find" is not a topic.
TOPICS = ("releases", "models", "hardware", "robotics", "software", "research",
          "technology", "search")
