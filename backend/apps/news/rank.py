"""Which of a few hundred items belong on a ticker, in what order, and only once each.

Garrett's brief for the ticker was specific about subject: "news relevent to the the website.
IE new technology, models, releases, robotics, hardware, betas, integrations etc etc". Two of
the collector's arms cannot honour that on their own -- the Hacker News frontpage is a general
aggregator and a search feed returns whatever the query dragged in -- so relevance is decided
here rather than assumed at the source.

Three jobs, in order:

  TOPIC   Every item is tested against the vocabulary below. A source whose whole feed is on
          topic by construction (a releases.atom is release announcements and nothing else)
          keeps its declared topic and passes without a match. An open source -- HN
          frontpage, any search feed -- must match, or it is dropped. That asymmetry is the
          whole reason the general feeds can be included at all.

  SCORE   source weight x recency x a small bonus per distinct topic word. Recency is an
          exponential decay, not a cutoff, so a major release stays on the bar for a day and
          fades rather than vanishing at a boundary.

  DEDUPE  The same story arrives from Google News, Bing News and HN within an hour. Collapse
          by URL and by title, keeping the highest score, because three chips for one story
          is what makes a ticker look automated.

  SPREAD  Cap per publisher and per topic. This is not a nicety: the first live pass of this
          collector returned 1,829 items and the top twenty were twelve humanoid-robot
          stories, because one query matched a day when robotics was the news everywhere. A
          bar that says "robotics" twelve times is a worse bar than one that says six things,
          even though every one of those twelve scored honestly.
"""
from __future__ import annotations

import math
import re
from urllib.parse import urlsplit

from .parse import Item

# The vocabulary, grouped by the topic a match implies. Lowercase, matched on word
# boundaries, so "beta" does not fire on "betamethasone" and "ai" does not fire on "said".
TOPIC_WORDS: dict[str, tuple[str, ...]] = {
    "models": ("llm", "model", "models", "qwen", "llama", "mistral", "deepseek", "gemma",
               "phi", "flux", "diffusion", "checkpoint", "quantized", "quantization",
               "gguf", "lora", "fine-tune", "finetune", "embedding", "tokenizer",
               "multimodal", "inference", "context window", "moe"),
    # No bare "v1"/"v2"/"v3"/"ga"/"rc"/"stable": they carry almost no signal a real release
    # headline does not already carry through "release", "launch" or "version", and each one
    # is a word that turns up in unrelated prose.
    "releases": ("release", "released", "releases", "launch", "launches", "launched",
                 "ships", "shipping", "version", "update", "rollout",
                 "general availability"),
    "hardware": ("gpu", "gpus", "nvidia", "amd", "intel", "blackwell", "rtx", "cuda",
                 "tensorrt", "vram", "hbm", "asic", "npu", "tpu", "datacenter", "wafer",
                 "silicon", "chip", "chips", "interconnect", "nvlink", "pcie"),
    "robotics": ("robot", "robots", "robotics", "humanoid", "actuator", "teleoperation",
                 "manipulation", "drone", "autonomous", "embodied"),
    "software": ("api", "apis", "sdk", "framework", "runtime", "open source", "open-source",
                 "beta", "preview", "integration", "integrations", "plugin", "plugins",
                 "mcp", "agent", "agents", "self-hosted", "self hosted", "local-first"),
    # No bare "paper": the HN frontpage put "Manabu Kosaka's Handmade Paper Sculptures" on
    # the bar labelled `research`, which is both off topic and a wrong chip. "preprint" and
    # "arxiv" say the same thing without the collision.
    "research": ("benchmark", "benchmarks", "preprint", "arxiv", "state of the art", "sota",
                 "ablation", "training run", "scaling law", "distillation", "rlhf"),
}

# Sources whose declared topic is trusted without a keyword match. These are the feeds where
# every item is on topic by construction; anything not listed has to earn its place.
TRUSTED_TOPICS = frozenset({"releases", "models", "hardware", "research"})

# Half-life of an item's score, in seconds. 18 hours puts a morning release at roughly half
# weight by late evening and a tenth by the next afternoon -- fast enough that the bar turns
# over daily, slow enough that a quiet Sunday still has something on it.
HALF_LIFE_S = 18 * 3600.0

# What an item with no date is worth. Equivalent to about 2.4 half-lives, so a dateless item
# can still appear when it is strongly on topic but never leads the bar.
UNDATED_RECENCY = 0.19

# How many items the ticker carries. Long enough that the loop is not obviously short,
# bounded so the JSON stays small and the marquee's duration stays sane.
LIMIT = 36

# Spread. Two per publisher keeps a release-heavy repo -- llama.cpp shipped four builds in
# the six hours before this was written -- from taking a sixth of the bar, and eight per topic
# keeps one loud news day from taking all of it.
PER_SOURCE = 2
PER_TOPIC = 8

# The floor. Filling to LIMIT regardless of score put items 161 and 189 hours old on the bar
# at scores of 0.003 and 0.001 -- a week-old story presented beside one from twenty minutes
# ago. 0.05 is about 4.3 half-lives, so roughly three days, after which an item leaves rather
# than padding. A quiet week therefore yields a shorter bar, which is the correct outcome:
# the bar's length is a reading, not a target.
MIN_SCORE = 0.05

# Titles that are a git ref rather than a headline. `github.com/pytorch/pytorch/releases.atom`
# published ten of these and no releases, which is why that source was dropped from feeds.py
# outright -- a filter cannot rescue a feed with no news in it. This stays as the guard for
# the next project that tags its CI into the same file, so one bad feed costs its own items
# instead of the bar's credibility.
_CI_REF = re.compile(
    # A slash, not an underscore: `[/_]` here made "main_st/robotics is great" a CI ref.
    r"^(?:trunk|viable|main|master|nightly|ciflow|refs|dev|staging)/"
    r"|^[a-z][a-z_-]*/[a-z][a-z_-]*/\d{6,}"
    r"|\b[0-9a-f]{40}\b", re.IGNORECASE)

_WORD = re.compile(r"[a-z0-9][a-z0-9+.#-]*")
_TITLE_KEY = re.compile(r"[^a-z0-9 ]+")


def topics_of(title: str) -> tuple[str, ...]:
    """Every topic whose vocabulary this title matches, in TOPIC_WORDS order."""
    words = set(_WORD.findall(title.lower()))
    low = " " + title.lower() + " "
    hits = []
    for topic, vocab in TOPIC_WORDS.items():
        for term in vocab:
            if (" " in term or "-" in term) and term in low:
                hits.append(topic)
                break
            if term in words:
                hits.append(topic)
                break
    return tuple(hits)


def _url_key(url: str) -> str:
    """Host + path, lowercased, query and fragment dropped.

    The query goes because news links carry per-referrer tracking parameters -- the same
    Verge article arrives from Google News and from Bing with different `?utm_*`, and keying
    on the full URL would call them two stories.
    """
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{p.path.rstrip('/').lower()}"


def _title_key(title: str) -> str:
    """A title reduced to its first eight words, punctuation removed.

    Eight rather than all of them because syndicated copies differ in the tail -- one outlet
    appends the section, another the date -- while the opening clause is what two accounts of
    one story share.
    """
    words = _TITLE_KEY.sub(" ", title.lower()).split()
    return " ".join(words[:8])


# A title short enough that a prefix match means nothing: "New GPU" is a prefix of half the
# hardware news ever written. Five words is where a shared opening starts being evidence.
_PREFIX_MIN_WORDS = 5


def _is_restatement(title: str, kept: list[str]) -> bool:
    """True when `title` is one of `kept` with a word or two added or removed.

    The eight-word key alone misses this, and the miss is not hypothetical: "New humanoid
    robot walks on gravel" and "New humanoid robot walks on gravel today" are six and seven
    words, so they never reach the eighth word where the keys would have converged, and both
    went on the bar. Comparing whole-word prefixes in both directions catches the pair without
    merging two stories that merely start alike, because the shorter one has to be a complete
    prefix of the longer.
    """
    mine = _TITLE_KEY.sub(" ", title.lower()).split()
    if len(mine) < _PREFIX_MIN_WORDS:
        return False
    for other in kept:
        theirs = other.split()
        if len(theirs) < _PREFIX_MIN_WORDS:
            continue
        short, long = (mine, theirs) if len(mine) <= len(theirs) else (theirs, mine)
        if long[:len(short)] == short:
            return True
    return False


def score(item: Item, now: float) -> float:
    if _CI_REF.search(item.title):
        return 0.0                      # a build robot's bookmark, not news
    hits = topics_of(item.title)
    if not hits and item.topic not in TRUSTED_TOPICS:
        return 0.0                      # an open source with nothing on topic
    if item.at <= 0.0:
        recency = UNDATED_RECENCY
    else:
        age = max(0.0, now - item.at)
        recency = math.pow(0.5, age / HALF_LIFE_S)
        # A timestamp in the future is a publisher's clock problem, not news from tomorrow.
        # `max(0.0, ...)` above already floors the age, so a future date reads as brand new,
        # which is the least-wrong reading available and does not need its own branch.
    return item.weight * recency * (1.0 + 0.12 * len(hits))


def label(item: Item) -> str:
    """The topic chip for an item: its source's topic, or the first thing it matched."""
    if item.topic in TRUSTED_TOPICS:
        return item.topic
    hits = topics_of(item.title)
    return hits[0] if hits else item.topic


def _interleave(kept: list[tuple[float, Item]]) -> list[tuple[float, Item]]:
    """Reorder so adjacent items rarely share a topic, without changing which items are in.

    Selection is by score; this is presentation. The first live pass with the caps in place
    still opened with eight consecutive robotics stories, because they all scored highest --
    every one of them legitimately, and the bar still read like a robotics newsletter for the
    first eight seconds a visitor watched it.

    The method is a round-robin over topic queues, each queue still in descending score, so
    the strongest item overall is still first and the bar still degrades gracefully when only
    one topic has anything in it.
    """
    queues: dict[str, list[tuple[float, Item]]] = {}
    for pair in kept:
        queues.setdefault(label(pair[1]), []).append(pair)
    # Strongest topic first, so the highest-scoring item of all is still item one.
    order = sorted(queues, key=lambda topic: queues[topic][0][0], reverse=True)
    out: list[tuple[float, Item]] = []
    while any(queues[topic] for topic in order):
        for topic in order:
            if queues[topic]:
                out.append(queues[topic].pop(0))
    return out


def rank(items: list[Item], now: float, limit: int = LIMIT) -> list[dict]:
    """Score, drop, dedupe and order. Returns the ticker's payload, newest-and-best first.

    The returned dicts are what `routes.py` serves and what `ui.js` reads, so the key names
    here are a wire format: changing one breaks the bar without breaking a test unless the
    test asserts the keys. `test_news.py` asserts them.
    """
    scored = []
    for it in items:
        s = score(it, now)
        if s >= MIN_SCORE:
            scored.append((s, it))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    seen: set[str] = set()
    kept_titles: list[str] = []
    per_source: dict[str, int] = {}
    per_topic: dict[str, int] = {}
    kept: list[tuple[float, Item]] = []
    for s, it in scored:
        # Two keys, one set: whichever collides first wins, and since the list is already in
        # descending score order the survivor is always the highest-scoring copy.
        keys = (f"u:{_url_key(it.url)}", f"t:{_title_key(it.title)}")
        if any(k in seen for k in keys) or _is_restatement(it.title, kept_titles):
            continue
        chip = label(it)
        src = it.source.lower()
        # The caps are applied after dedupe, so a story that arrives three times consumes one
        # slot rather than three -- checking them first would let duplicates spend a
        # publisher's whole allowance on one headline.
        if per_source.get(src, 0) >= PER_SOURCE or per_topic.get(chip, 0) >= PER_TOPIC:
            continue
        seen.update(keys)
        kept_titles.append(" ".join(_TITLE_KEY.sub(" ", it.title.lower()).split()))
        per_source[src] = per_source.get(src, 0) + 1
        per_topic[chip] = per_topic.get(chip, 0) + 1
        kept.append((s, it))
        if len(kept) >= limit:
            break

    out = []
    for s, it in _interleave(kept):
        out.append({
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "topic": label(it),
            "at": round(it.at, 3),
            "score": round(s, 4),
        })
    return out
