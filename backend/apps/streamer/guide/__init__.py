"""SyMoNeuRaL Guide -- turns a question into a channel filter for the Streamer.

Garrett's words: *"we need the symoneural chat to have a floating prompt for setting up the
guide with selected subcategories. I want the agent to streamline a very quick filtering of
all the channels and categories."*

## Guide owns no weights, and that is the whole architecture

The card is 15.92 GiB. Chat (~5 GB) and image (~7 GB) already cannot co-reside, which is why
`scripts/gpu-governor.sh` exists. A Guide with its own model would be a third tenant fighting
for the same card to answer a question about *strings*. So it has none. When it needs a model
it asks the chat surface, exactly as `remix()` in `backend/api.py` does -- "Remix has no
weights of its own -- it asks the chat surface, which is what 'one server underneath' means in
practice, and why it queues behind chat and image."

Concretely: this module never imports the API, never touches `scripts/gpu-governor.sh`, and
never opens a socket. The caller injects `ask_model`, a `str -> str` callable, and whatever it
does about the GPU lock is the caller's business. That keeps the module importable and fully
testable with no card, no network and no service running.

## The local fast path comes first -- the RavenCalc precedent

`.claude/CLAUDE.md`: *"RavenCalc (SymPy, CPU) deliberately never takes the lock. That is what
lets it speculatively pre-compute while the GPU is loading."* The same reasoning applies here
and is stronger, because most IPTV filtering is not a language problem at all. "uk sports",
"movies", "bbc" are answered by matching strings the visitor's own playlist already contains:
pure CPU, stdlib only, microseconds, and it works while a fine-tune is holding the card.

So `filter_from_question` runs the local pass FIRST and only escalates to the model when the
local pass cannot account for what the visitor asked -- "premier league football" needs world
knowledge that a `group-title` string does not carry. The escalation rule is stated, not
judged: see `_LOCAL_RULE` and `FUZZY_CUTOFF`.

## The output format is a flat list because that is what this 7B can finish

`.claude/HANDOVER.md` §2c-bis, measured, not theorised: asking this 7B for a **JSON object**
made it loop --

    {"match":["premier league","nfl","nba","mlb","f1","nfl","nba",...

until it hit the token cap, so the object never closed, nothing parsed, and the fallback fired
on **every** request while the feature looked fine. One line of comma-separated keywords it
answers cleanly every time.

Two consequences are built into this module:

1. **One prompt, one line, one field.** The model is asked for search keywords and nothing
   else. `kind`, `groups` and `exclude` are derived locally, deterministically, from the
   question and the playlist's own vocabulary -- they are cheap and exact, and asking the model
   for them would mean either a nested object (the failure above) or three round trips against
   a contended card.
2. **`parse_model_line` rejects that exact string.** It has to, and a naive parser does not:
   split the loop on commas and you get `match":["premier league`, `nfl`, `nba`, `mlb`, `f1`,
   which is a non-empty list of plausible-looking tokens. So there are two independent rules --
   structural punctuation (`{ } [ ] " :`) means the model started emitting JSON, and a repeated
   token means it looped -- and `test_guide.py` asserts both against the literal string.

## The fallback is observable, always

`source` is `local`, `model` or `fallback`, `model_used` is a bool, and `why` says in words
which one produced the filter. There is no path where an unusable model answer quietly becomes
an unfiltered list: when nothing can be derived, `ok` is `False`, `why` says so, and
`apply_filter` returns **no** channels rather than all of them. Handing back the whole playlist
is indistinguishable from a working filter, which is the failure §2c-bis is about.

## Kind vocabulary: `live`, `series`, `vod`

`backend/apps/streamer/m3u.py::_classify()` emits exactly those three. It never emits `movie`, and
a frontend testing for `"movie"` is why "we are completely missing the movie category" was
reported. This module accepts `movie` (and `film`, `films`, `movies`, `cinema`) as an **input**
alias and **never emits it**. `test_guide.py` asserts that.

## Stateless, and holds nothing of the visitor's

No module-level cache, no disk, no logging. Channels arrive as arguments and leave as
arguments. `.claude/HANDOVER.md`: *"Credentials: visitor supplies their own, localStorage only,
never stored on the box."* Nothing here ever reads or returns a channel `url` -- names and
group titles only -- because a playlist URL carries the visitor's credentials in its path.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter, OrderedDict
from typing import Any, Callable, Iterable, Sequence

__all__ = [
    "KINDS", "KIND_ALIASES", "FUZZY_CUTOFF", "MAX_TERMS", "MAX_FUZZY_GROUPS",
    "PROMPT_TEMPLATE", "build_prompt", "parse_model_line", "ModelUnusable",
    "normalise_kind", "kind_from_question", "group_key", "cluster_groups", "catalogue",
    "filter_from_question", "apply_filter", "unit_state",
]

# ---------------------------------------------------------------- vocabulary

#: The only kind strings that exist. `m3u.py::_classify()` emits these three and nothing else.
KINDS = ("live", "series", "vod")

#: Accepted on input, never emitted. `movie` is here because the Streamer's frontend has been
#: testing for it -- taking it as an alias means a caller that still says `movie` gets `vod`
#: instead of silently filtering to nothing.
KIND_ALIASES = {
    "live": "live", "livetv": "live", "tv": "live", "channel": "live", "channels": "live",
    "broadcast": "live", "linear": "live",
    "vod": "vod", "movie": "vod", "movies": "vod", "film": "vod", "films": "vod",
    "cinema": "vod", "ondemand": "vod",
    "series": "series", "serie": "series", "shows": "series", "episode": "series",
    "episodes": "series", "season": "series", "seasons": "series", "boxset": "series",
    "boxsets": "series",
}

#: Multi-word phrases checked before single tokens, because "tv series" contains "tv" and
#: would otherwise resolve to `live`.
_KIND_PHRASES = (
    ("tv series", "series"),
    ("box set", "series"),
    ("live tv", "live"),
    ("on demand", "vod"),
)

#: When a question names more than one kind, the more specific one wins. "movie channels"
#: means VOD; reading it as `live` would filter to exactly the wrong half of the playlist.
_KIND_PRIORITY = ("series", "vod", "live")

#: Words that carry no filtering signal -- UNLESS the playlist's own group titles use them,
#: see `_strip_stopwords`. Deliberately small: over-stripping turns "the office" into nothing.
#: `show` is here (singular) because "show me..." is the most common opener and it
#: substring-matches Showtime; `shows` is a kind alias and is handled before this list.
_STOPWORDS = frozenset("""
a an the and or of for in on at to my me i we us it that this those these is are am be
please can could would want wants wanting need needs looking look find finding get give
show all any some everything something anything list lists watch watching see seeing
only just about with from there here what which who when new
""".split())

#: Words a visitor uses for a category their playlist spells differently. Applied ONLY when the
#: alternative is already in the playlist's own group vocabulary, so this can never invent a
#: category -- it bridges "adult" to the `XXX` and `18+` groups that actually exist.
#:
#: This is the honest fix for "adult live tv seems to be being blocked". **Guide has no content
#: filter and no denylist of any kind**; it blocked nothing. The visitor typed "adult", every
#: group was called `XXX` or `18+`, no string matched, the question escalated to a
#: persona-tuned model that answered with a refusal sentence, and the result was a filter
#: matching nothing. Three separate failures, none of them a policy, all of them fixed here.
_SYNONYMS = {
    "adult": ("xxx", "18", "adults", "porn", "erotic"),
    "adults": ("xxx", "18", "adult"),
    "xxx": ("adult", "adults", "18"),
    "porn": ("xxx", "adult", "18"),
    "kids": ("children", "kid", "cartoon", "cartoons"),
    "kid": ("kids", "children", "cartoon", "cartoons"),
    "children": ("kids", "cartoon", "cartoons"),
    "cartoons": ("kids", "children", "cartoon"),
    "documentaries": ("documentary", "docs", "doc"),
    "documentary": ("documentaries", "docs"),
    "docs": ("documentary", "documentaries"),
}

#: Group-title words that name a kind. `m3u.py::_classify()` guesses from the URL shape and
#: says so: *"honestly wrong-by-default (`live`) otherwise"*. A plain M3U whose movie URLs end
#: `.mp4` with no `/movie/` segment therefore classifies every film as `live` -- which is the
#: other half of "still missing movies", and it is upstream of this module. So a channel whose
#: kind is the DEFAULT `live` may be upgraded by what its own group title says. An explicit
#: `vod` or `series` from the URL is never overridden, and no channel object is ever mutated.
_GROUP_KIND_HINTS = {
    "movie": "vod", "movies": "vod", "film": "vod", "films": "vod", "cinema": "vod",
    "vod": "vod", "peliculas": "vod", "filmes": "vod",
    "series": "series", "serie": "series", "season": "series", "seasons": "series",
    "boxset": "series", "boxsets": "series", "tvshows": "series",
}

#: A clause after one of these words is an exclusion. Split before stopword removal, because
#: "not" and "no" would otherwise be stripped and the exclusion lost.
_NEGATORS = frozenset({"not", "no", "without", "except", "excluding", "exclude", "minus"})

#: Clause separators. `but` is here because "sports but not cricket" is one sentence with two
#: clauses and the negation must not leak backwards over the whole thing.
_CLAUSE_SPLIT = re.compile(r"[,;/]| but | however ", re.IGNORECASE)

# ---------------------------------------------------------------- tuning constants

#: `difflib.SequenceMatcher` ratio above which two normalised group keys are treated as the
#: same group, and above which a question token is treated as naming a group. Named so the
#: README can quote it and so "ambiguous" is a threshold rather than a judgement.
FUZZY_CUTOFF = 0.82

#: Most keywords a filter will carry. The model is asked for 8; a few more can arrive from the
#: question itself, and beyond this the filter matches everything and means nothing.
MAX_TERMS = 12

#: Fuzzy clustering is O(groups x clusters). A provider list can carry thousands of groups, and
#: this runs in the serving process, so above this many distinct groups the fuzzy merge is
#: skipped and `catalogue()["fuzzy"]` reports `False` -- exact normalisation only. Saying so is
#: the point: silently degrading a documented behaviour is the same class of bug as a fallback
#: that does not announce itself.
MAX_FUZZY_GROUPS = 1200

#: Shortest token that may drive a match. Two-letter tokens ("uk", "tv") are kept only when
#: they hit the playlist's own vocabulary exactly; free-text terms shorter than this match
#: half a playlist.
_MIN_TERM = 3

#: The escalation rule, stated once so the README and the tests can quote the same sentence.
_LOCAL_RULE = ("the local pass is trusted only when every content word in the question is "
               "accounted for by the playlist's own vocabulary -- a whole-token hit on a "
               f"group name or a channel name, or a difflib ratio of at least {FUZZY_CUTOFF} "
               "against a normalised group name. Anything left over is ambiguous and goes to "
               "the model.")


class ModelUnusable(Exception):
    """The model's answer cannot be turned into a filter, with the reason in `str(exc)`.

    Raised rather than returned so a caller cannot accidentally treat an empty keyword list as
    a successful empty filter -- which is exactly how a looping model produced a feature that
    appeared to work.
    """


# ---------------------------------------------------------------- text helpers

def _fold(s: str) -> str:
    """Lowercase, strip diacritics, reduce every run of non-alphanumerics to one space.

    Digits are kept as characters and as tokens. Dropping them would collapse `SPORTS 1` and
    `SPORTS 2` into one group, which is a data drop dressed up as tidying.
    """
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _tokens(s: str) -> list[str]:
    return [t for t in _fold(s).split() if t]


def _numbers(tokens: Sequence[str]) -> frozenset[str]:
    return frozenset(t for t in tokens if t.isdigit())


def kind_of(ch: Any, *, use_group_hint: bool = True) -> str:
    """The kind of one channel, upgrading `m3u.py`'s honest default from its group title.

    `_classify()` reads the URL shape: `/movie/` and `/vod/` give `vod`, `/series/` gives
    `series`, and **everything else defaults to `live`** -- its own docstring calls that
    "honestly wrong-by-default". A plain M3U export whose films are `…/12345.mp4` under
    `group-title="VOD | Movies"` therefore arrives with every film marked `live`, and the
    Movies category is empty however the frontend spells it.

    So: an explicit `vod` or `series` is authoritative and never touched. Only the `live`
    default is reconsidered, and only against the group title the provider wrote. It stays a
    hint -- `use_group_hint=False` turns it off -- and nothing is written back to the channel.

    The known cost, stated rather than hidden: a genuinely linear "24/7 Movies" channel is
    counted as `vod` under this rule. That is the wrong half of a trade whose other half is a
    Movies category that is empty on most real playlists.
    """
    kind = normalise_kind(_get(ch, "kind")) or "live"
    if kind != "live" or not use_group_hint:
        return kind
    for tok in _tokens(_get(ch, "group")):
        hinted = _GROUP_KIND_HINTS.get(tok)
        if hinted:
            return hinted
    return "live"


def _get(ch: Any, field: str, default: str = "") -> str:
    """Read a field from a `Channel` dataclass or a plain dict.

    Duck-typed on purpose: this module does not import `apps.streamer.m3u`, so it works against a
    parsed playlist, against JSON that came back from the API, and against a test fixture,
    without any of them having to agree on a class.
    """
    v = ch.get(field, default) if isinstance(ch, dict) else getattr(ch, field, default)
    return v if isinstance(v, str) else (default if v is None else str(v))


# ---------------------------------------------------------------- kinds

def normalise_kind(value: Any) -> str | None:
    """Canonical kind, or `None` if the value names no kind.

    Accepts `movie`/`movies`/`film` and returns `vod`. Never returns `movie`.
    """
    tok = _fold(value).replace(" ", "")
    if tok in KINDS:
        return tok
    return KIND_ALIASES.get(tok)


def kind_from_question(question: str) -> tuple[str | None, set[str]]:
    """(kind, the tokens that named it). Phrases first, then single tokens, most specific wins.

    The consumed tokens come back so the caller can drop them from the search terms -- "movies
    with tom hanks" should search for `tom hanks`, not for `movies`.
    """
    folded = _fold(question)
    hits: dict[str, set[str]] = {}
    for phrase, kind in _KIND_PHRASES:
        if phrase in folded:
            hits.setdefault(kind, set()).update(phrase.split())
    for tok in folded.split():
        k = KIND_ALIASES.get(tok)
        if k:
            hits.setdefault(k, set()).add(tok)
    for kind in _KIND_PRIORITY:
        if kind in hits:
            return kind, hits[kind]
    return None, set()


def _normalise_kinds(kinds: Iterable[Any] | None) -> list[str]:
    """The kind vocabulary actually present in the visitor's playlist, canonicalised."""
    out: list[str] = []
    for k in kinds or ():
        c = normalise_kind(k)
        if c and c not in out:
            out.append(c)
    return out


# ---------------------------------------------------------------- groups

def group_key(name: str) -> str:
    """Canonical key for a group title. Not a display string -- see `cluster_groups`.

    `UK| SPORTS`, `UK - Sports` and `Sports UK` all key to `sports uk`: fold, then sort the
    tokens, because providers write the same category with the country on either end and with
    any separator they feel like. Numbers survive as tokens, so `SPORTS 1` keys to `1 sports`
    and stays distinct from `SPORTS 2`.
    """
    return " ".join(sorted(_tokens(name)))


#: Tokens that describe the *feed*, not the category. A group differing only by one of these
#: is the same category twice, so folding them is the point of the exercise -- and every
#: original spelling survives in the cluster either way.
_NOISE_TOKENS = frozenset({"hd", "sd", "fhd", "uhd", "4k", "hq", "hevc", "h264", "h265",
                           "1080p", "720p", "raw"})

#: Below this length a differing token is never fuzz-matched. Measured on a synthetic 20,000
#: channel playlist: `sports uk` and `sports us` score **0.889** character-wise, comfortably
#: over `FUZZY_CUTOFF`, so a plain ratio merged UK Sports and US Sports into one category and
#: "uk sports" returned 535 American channels. Two-letter country codes differ by one
#: character and mean entirely different things.
_MIN_FUZZ_LEN = 4


def _mergeable(a: str, b: str) -> bool:
    """May two canonical keys be treated as the same group? Compared by TOKENS, not characters.

    Three ways to be the same group, and nothing else counts:

    1. identical keys;
    2. differing only by feed-quality tokens -- `SPORTS 1` and `SPORTS 1 HD`;
    3. exactly one differing token on each side, both at least `_MIN_FUZZ_LEN` long and
       `FUZZY_CUTOFF`-close -- `sport`/`sports`, `movie`/`movies`.

    Numbers must match exactly before any of that. `1 sports` and `2 sports` score 0.875
    character-wise and are two real categories; so are `sports uk` and `sports us`, which is
    what rule 3's length floor is for.
    """
    ta, tb = set(a.split()), set(b.split())
    if _numbers(ta) != _numbers(tb):
        return False
    if ta == tb:
        return True
    d1, d2 = ta - tb, tb - ta
    if not (d1 - _NOISE_TOKENS) and not (d2 - _NOISE_TOKENS):
        return True
    if len(d1) != 1 or len(d2) != 1:
        return False
    x, y = d1.pop(), d2.pop()
    if len(x) < _MIN_FUZZ_LEN or len(y) < _MIN_FUZZ_LEN:
        return False
    return difflib.SequenceMatcher(None, x, y).ratio() >= FUZZY_CUTOFF


def cluster_groups(groups: Iterable[str], *, fuzzy: bool = True) -> list[dict]:
    """Collapse near-duplicate group titles WITHOUT losing any original string.

    Each cluster is::

        {"key": "sports uk",            # canonical, for matching
         "display": "UK - Sports",      # ONE OF THE ORIGINALS, never a synthesised string
         "originals": ["UK| SPORTS", "UK - Sports", "Sports UK"],
         "count": 3}                    # how many inputs landed here

    `display` is an original and `originals` carries every spelling, because a caller filters
    by the string the playlist actually contains. Returning the canonical key would match zero
    channels and drop data at the same time -- `.claude/CLAUDE.md`: *layout changes must not
    drop data*, and this is the same rule one layer down.

    Accepts either a unique vocabulary or one entry per channel; `count` reflects what it was
    given.
    """
    tally: "OrderedDict[str, Counter]" = OrderedDict()
    for g in groups:
        g = (g or "").strip()
        if not g:
            continue                        # ungrouped is counted by `catalogue`, not here
        tally.setdefault(group_key(g), Counter())[g] += 1
    if not tally:
        return []

    # Biggest first, so the dominant spelling names the cluster rather than whichever
    # spelling happened to be parsed first. Ties break to the SHORTEST key: given
    # `SPORTS 1` and `SPORTS 1 HD` one apiece, the cluster should be the plain one with the
    # HD spelling folded into it, not the other way round.
    order = sorted(tally, key=lambda k: (-sum(tally[k].values()), len(k), k))
    do_fuzzy = fuzzy and len(order) <= MAX_FUZZY_GROUPS

    merged: "OrderedDict[str, Counter]" = OrderedDict()
    for key in order:
        target = None
        if do_fuzzy:
            for existing in merged:
                if _mergeable(existing, key):
                    target = existing
                    break
        if target is None:
            merged[key] = Counter(tally[key])
        else:
            merged[target].update(tally[key])

    out = []
    for key, spellings in merged.items():
        # Most common spelling wins; ties break to the shortest, then alphabetically, so the
        # result is stable across runs rather than dependent on dict ordering.
        display = sorted(spellings.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
        out.append({
            "key": key,
            "display": display,
            "originals": sorted(spellings),
            "count": sum(spellings.values()),
        })
    out.sort(key=lambda c: (-c["count"], c["display"]))
    return out


def catalogue(channels: Iterable[Any], *, use_group_hint: bool = True) -> dict:
    """Kind counts and group counts for a loaded playlist. Pure CPU, no model, no lock.

    This is the "streamline a very quick filtering of all the channels and categories" half:
    the categories a visitor is offered are counted from what they actually loaded, never from
    a fixed list. Returns::

        {"total": 5,
         "kinds": {"live": 3, "series": 1, "vod": 1},   # always all three keys
         "groups": [cluster, ...],                      # each with a per-kind breakdown
         "ungrouped": 0,
         "fuzzy": True}                                 # False if the merge was skipped

    `fuzzy` is reported rather than assumed: above `MAX_FUZZY_GROUPS` distinct groups the merge
    is skipped for cost, and a caller that shows "near-duplicate groups merged" needs to know
    when that did not happen.
    """
    pairs: list[tuple[str, str]] = []
    kinds: Counter = Counter()
    ungrouped = 0
    total = 0
    for ch in channels:
        total += 1
        kind = kind_of(ch, use_group_hint=use_group_hint)
        kinds[kind] += 1
        group = _get(ch, "group").strip()
        if group:
            pairs.append((group, kind))
        else:
            ungrouped += 1

    fuzzy = len({group_key(g) for g, _ in pairs}) <= MAX_FUZZY_GROUPS
    clusters = cluster_groups([g for g, _ in pairs], fuzzy=fuzzy)
    by_key = {}
    for c in clusters:
        c["kinds"] = {k: 0 for k in KINDS}
        for original in c["originals"]:
            by_key[original] = c
    for group, kind in pairs:
        c = by_key.get(group)
        if c is not None:
            c["kinds"][kind] += 1

    return {
        "total": total,
        "kinds": {k: kinds.get(k, 0) for k in KINDS},
        "groups": clusters,
        "ungrouped": ungrouped,
        "fuzzy": fuzzy,
    }


# ---------------------------------------------------------------- the model half

#: The exact prompt. ONE line, ONE field, a flat list -- the format §2c-bis measured this 7B
#: completing every time. Do not "improve" this into JSON; that is the documented failure.
PROMPT_TEMPLATE = (
    "List the words to search for in a TV channel list to find: {question}\n"
    "\n"
    "Rules: reply with ONE line, at most 8 lowercase keywords, comma separated. "
    "No sentences, no repeats, no quotes, no brackets, no JSON, no explanation.\n"
    "\n"
    "Keywords:"
)


def build_prompt(question: str) -> str:
    """The one prompt this module ever sends. The playlist is NOT in it.

    One call to the card per question, not one per channel, and the model never sees the
    visitor's channel list -- it is answering a general question about words, so there is
    nothing to send and nothing to leak.
    """
    return PROMPT_TEMPLATE.format(question=" ".join(str(question or "").split())[:300])


_STRUCTURAL = re.compile(r'[{}\[\]":]')

#: A refusal or an apology, not a keyword line. The chat model carries a trained persona and
#: trained refusals (`.claude/CLAUDE.md`), so some questions come back as a sentence -- and a
#: sentence survives comma-splitting: `"I'm sorry, but I can't help with that."` parsed to
#: `["i'm sorry"]`, which is a filter that matches nothing while `source` said `model`. To a
#: visitor that is indistinguishable from the category being blocked, and **nothing in this
#: repo blocks it** -- there is no denylist here and `denied()` in `backend/api.py` guards the
#: image endpoint only, on one narrow intersection.
#:
#: `cant` is deliberately absent: Cantonese. `can't`, `cannot` and `can not` only.
_REFUSAL = re.compile(r"\b(sorry|apologi[sz]\w*|cannot|can ?not|can'?t|won'?t|unable|"
                      r"as an ai|inappropriate|not appropriate|against my|"
                      r"i'?m not|unfortunately|i must decline)\b", re.I)


def parse_model_line(text: str) -> list[str]:
    """The model's answer -> keywords, or `ModelUnusable` with the reason.

    Three rejections, and the first two exist because of a measured failure rather than a
    theoretical one (`.claude/HANDOVER.md` §2c-bis):

    1. **Structural punctuation.** `{"match":["premier league","nfl",...` split on commas
       yields `match":["premier league`, `nfl`, `nba`, `mlb` -- a non-empty list of
       plausible tokens that passes any "did we get keywords?" test. So any of `{ } [ ] " :`
       means the model started emitting an object it will not finish, and the whole answer
       goes.
    2. **Repeats.** The loop repeats itself (`nfl`, `nba`, `nfl`, `nba`). A duplicate token is
       the signature and is treated as one.
    3. **Nothing usable left.** An empty list is never returned as success.
    """
    first = ""
    for line in str(text or "").splitlines():
        if line.strip():
            first = line.strip()
            break
    if not first:
        raise ModelUnusable("the model returned nothing")
    # The prompt ends in `Keywords:`, and a 7B continuing it very often echoes the label.
    # `Keywords: sports, football` is a perfect answer that contains a colon, so testing for
    # structure before stripping the label rejected healthy output and fired the fallback on
    # every request with a reason that was false -- `.claude/HANDOVER.md` §3.0d, a verification
    # step that fails on good input. Strip the label, then keep the structural test exactly as
    # strict as it was.
    first = re.sub(r"^\s*key\s*words?\s*:\s*", "", first, flags=re.IGNORECASE)
    if _STRUCTURAL.search(first):
        raise ModelUnusable("the model started emitting JSON instead of a keyword line")
    if _REFUSAL.search(first):
        raise ModelUnusable("the model refused the question rather than answering it")
    # No comma at all means at most one keyword, and a keyword phrase is short -- "sky sports
    # main event" is four words and is the longest shape worth allowing. Beyond that it is a
    # sentence, and a sentence that survives the checks above becomes a 30-character "term"
    # that matches nothing.
    if "," not in first and len(first.split()) > 4:
        raise ModelUnusable("the model answered in prose instead of a keyword line")

    terms: list[str] = []
    for raw in first.split(","):
        t = re.sub(r"^[^a-z0-9]+|[^a-z0-9 ]+$", "", raw.strip().lower())
        t = " ".join(t.split())
        if 1 < len(t) < 24:
            terms.append(t)
    if not terms:
        raise ModelUnusable("the model's answer held no usable keywords")
    if len(set(terms)) < len(terms):
        raise ModelUnusable("the model repeated itself, which is how it loops")
    return terms[:MAX_TERMS]


# ---------------------------------------------------------------- the filter

def _clauses(question: str) -> list[tuple[bool, list[str]]]:
    """Split into (is_exclusion, tokens). Negation is per clause, not per sentence."""
    out = []
    for clause in _CLAUSE_SPLIT.split(str(question or "")):
        toks = _tokens(clause)
        if not toks:
            continue
        neg = False
        kept: list[str] = []
        for t in toks:
            if t in _NEGATORS:
                neg = True
                continue
            kept.append(t)
        if kept:
            out.append((neg, kept))
    return out


def _group_hits(tokens: Sequence[str], clusters: Sequence[dict]) -> tuple[list[str], set[str]]:
    """(matching original group titles, the tokens that earned them).

    Whole-token matching, never substring: `show` must not select `Showtime`.

    A cluster matches on one of three tests, and the containment is deliberately strict rather
    than "any token in common". Loose overlap makes "uk sports" select `UK| NEWS` as well,
    because both keys contain `uk` -- which is a filter that quietly does not filter:

    * every question token is in the key  -- "sports" selects `UK| SPORTS`;
    * every key token is in the question  -- "uk sports" selects `UK| SPORTS`;
    * the question is `FUZZY_CUTOFF`-close to the whole key -- "uk sport" selects it too.
    """
    if not clusters or not tokens:
        return [], set()
    want = set(tokens)
    joined = " ".join(sorted(want))
    originals: list[str] = []
    used: set[str] = set()
    for c in clusters:
        key_tokens = set(c["key"].split())
        if want <= key_tokens or key_tokens <= want:
            originals.extend(c["originals"])
            used |= want & key_tokens
        elif _mergeable(c["key"], joined):
            originals.extend(c["originals"])
            used |= want
    # Preserve every spelling, deduplicated, order stable.
    return list(dict.fromkeys(originals)), used


def _strip_stopwords(tokens: Sequence[str], group_vocab: set[str]) -> list[str]:
    """Drop stopwords, but never a word the visitor's own group titles use.

    Found by running a synthetic playlist rather than by reading the list: **`us` is both an
    English pronoun and the United States.** With `us` stripped, "us sports" filtered to every
    sports group on the planet -- 2,473 channels, reported as a confident local match. The same
    collision hits `it` (Italy), `in` (India), `at` (Austria), `be`, `is`, `me`, `no`.

    Rather than curate a list of exceptions that will be wrong for the next playlist, the
    playlist decides: a stopword that appears in a **group title** is a category name here and
    is kept. Group titles only -- channel *names* contain `the`, `and` and `is` constantly, and
    rescuing from those would strip nothing at all.
    """
    return [t for t in tokens if t not in _STOPWORDS or t in group_vocab]


def _bridged_hits(tokens: Sequence[str], clusters: Sequence[dict],
                  group_vocab: set[str]) -> tuple[list[str], set[str], list[tuple[str, str]]]:
    """`_group_hits`, retried through `_SYNONYMS` when the visitor's word is not the
    playlist's word.

    Returns (original group titles, covered ORIGINAL tokens, the bridges actually used).

    A substitution is attempted only when the alternative is already in this playlist's group
    vocabulary, so nothing is ever invented: with no `XXX` group, "adult" bridges to nothing
    and the question escalates exactly as before. The bridges are returned so `why` can say
    *which* word of the visitor's was translated into which word of theirs — a filter that
    quietly searched for something the visitor did not type would be the dishonest version of
    this feature.
    """
    hits, covered = _group_hits(tokens, clusters)
    bridges: list[tuple[str, str]] = []
    for i, tok in enumerate(tokens):
        # NOT `if tok in covered: continue`. That guard looked like a cheap skip and was a
        # silent data loss: a playlist carrying `XXX ADULT` and `18+ FOR ADULTS` covers
        # "adult" on the first group by an exact token match, so the bridge never ran and
        # the second group was never found. The visitor asked for adult channels and got
        # one of the two categories they have -- which is indistinguishable from being
        # filtered, and it is the shape of the complaint that started this work.
        #
        # Running the bridge anyway cannot invent anything: a substitution is only ever
        # attempted against a word that is already in THIS playlist's group vocabulary,
        # and `_group_hits` still has to match it. The cost is a few extra passes over a
        # list that is tens of entries long.
        if tok in covered and tok not in _SYNONYMS:
            continue
        # EVERY alternative that lands, not the first: a playlist routinely carries `XXX`,
        # `18+` and `FOR ADULTS` as three separate groups, and stopping at the first one
        # would silently hide two of them. Dropping data is the thing this repo does not do.
        for alt in _SYNONYMS.get(tok, ()):
            if alt not in group_vocab:
                continue
            variant = list(tokens)
            variant[i] = alt
            alt_hits, alt_covered = _group_hits(variant, clusters)
            if alt in alt_covered:
                hits.extend(h for h in alt_hits if h not in hits)
                covered |= {tok} | (alt_covered - {alt})
                if (tok, alt) not in bridges:
                    bridges.append((tok, alt))
    return hits, covered, bridges


def _name_tokens(names: Iterable[str] | None) -> set[str]:
    if not names:
        return set()
    out: set[str] = set()
    for n in names:
        out.update(_tokens(n))
    return out


def filter_from_question(question: str,
                         kinds: Iterable[Any] | None = None,
                         groups: Iterable[str] | None = None,
                         *,
                         ask_model: Callable[[str], str] | None = None,
                         names: Iterable[str] | None = None,
                         clusters: Sequence[dict] | None = None) -> dict:
    """A visitor's question -> a channel filter, local first, model only if needed.

    `kinds` and `groups` are the vocabulary **actually present in the loaded playlist** --
    pass `catalogue()["kinds"]` keys and the raw `group` strings. `names` is optional channel
    names; supplying them lets the local pass confirm a term like "bbc" without the card.
    `ask_model` is a `str -> str` callable (the caller's own route to the chat surface); with
    no callable the module is local-only and says so.

    Returns::

        {"match":   ["tom hanks"],       # search terms, lowercase
         "exclude": ["news"],            # terms that disqualify a channel
         "kind":    "vod",               # live | series | vod | None -- never "movie"
         "groups":  ["UK| SPORTS"],      # ORIGINAL strings from the playlist
         "why":     "...",               # shown to the visitor; names its own provenance
         "source":  "local",             # local | model | fallback
         "model_used": False,            # the two-value discriminator, see README
         "ok":      True}                # False = no filter could be derived. Not "match all".

    `ok=False` is a positive signal, not an absence: `apply_filter` returns no channels for it.
    Handing back the unfiltered playlist would look exactly like a filter that worked.
    """
    q = str(question or "").strip()
    # Clustering 20,000 group strings measures ~120 ms on this box, which is nothing next to a
    # GPU turn but is wasted on every keystroke of a live filter box. A caller that already
    # holds `catalogue()["groups"]` passes it in; `groups` remains the documented argument.
    clusters = list(clusters) if clusters is not None else cluster_groups(groups or [])
    vocab_kinds = _normalise_kinds(kinds)
    name_vocab = _name_tokens(names)

    kind, kind_tokens = kind_from_question(q)
    if kind and vocab_kinds and kind not in vocab_kinds:
        # The visitor asked for a kind their playlist's `kind` field does not carry. Before
        # saying so, look at the group titles: `m3u.py::_classify()` defaults to `live` when a
        # URL has no `/movie/` segment, so a playlist can be full of films that are labelled
        # `live` and grouped `VOD | Movies`. Answering "you have no movies" to someone looking
        # at a Movies category would be the most confusing possible way to be wrong.
        hinted = [c for c in clusters
                  if any(_GROUP_KIND_HINTS.get(t) == kind for t in c["key"].split())]
        if hinted:
            groups_out = [g for c in hinted for g in c["originals"]]
            shown = ", ".join(sorted({c["display"] for c in hinted}))
            return {"match": [], "exclude": [], "kind": None, "groups": groups_out,
                    "why": (f"your playlist labels these by group rather than by type, so "
                            f"{kind} came from the group {shown} — matched on this machine's "
                            "CPU, no model"),
                    "source": "local", "model_used": False, "ok": True}
        # Genuinely absent. Say so; do not quietly widen the filter to everything.
        return {"match": [], "exclude": [], "kind": None, "groups": [],
                "why": f"this playlist has no {kind} entries, so there is nothing to filter to",
                "source": "local", "model_used": False, "ok": False}

    # The playlist's group titles decide which stopwords are really stopwords -- `us` is a
    # pronoun and a country, and only this playlist knows which one the visitor means.
    group_vocab = {t for c in clusters for t in c["key"].split()}

    include_tokens: list[str] = []
    exclude_tokens: list[str] = []
    for is_exclusion, toks in _clauses(q):
        for t in _strip_stopwords([t for t in toks if t not in kind_tokens], group_vocab):
            (exclude_tokens if is_exclusion else include_tokens).append(t)
    include_tokens = list(dict.fromkeys(include_tokens))
    exclude_tokens = list(dict.fromkeys(exclude_tokens))

    hit_groups, by_group, bridges = _bridged_hits(include_tokens, clusters, group_vocab)
    by_name = {t for t in include_tokens if t in name_vocab}
    covered = by_group | by_name
    uncovered = [t for t in include_tokens if t not in covered and len(t) >= _MIN_TERM]

    # ---- 1. the local fast path. No model, no lock, no network.
    if (hit_groups or kind or by_name) and not uncovered:
        # A token that produced a group selection is already expressed AS that selection.
        # Leaving it in `match` as well would re-admit every other group whose title happens
        # to contain the word -- "uk sports" would drag `UK| NEWS` back in through `uk`.
        #
        # `_MIN_TERM` does NOT apply to a token the playlist's own channel names contain.
        # Dropping it did: "bt" is two characters and is BT Sport, so the local branch returned
        # match=[], groups=[], kind=None, ok=True -- and `apply_filter`'s kind-only tail then
        # handed back EVERY channel under a `why` claiming a local category match. A confident
        # match-everything is the exact dishonesty this module exists to avoid.
        terms = [t for t in include_tokens
                 if t not in by_group and (len(t) >= _MIN_TERM or t in by_name)]
        # The invariant, guarded rather than reasoned about: a local result must actually
        # restrict something. If it does not, this is not a local answer -- fall through.
        if terms or hit_groups or kind:
            parts = []
            if kind:
                parts.append(f"kind {kind}")
            if hit_groups:
                shown = ", ".join(sorted({c["display"] for c in clusters
                                          if set(c["originals"]) & set(hit_groups)}))
                parts.append(f"group {shown}")
            if terms:
                parts.append("words " + ", ".join(terms))
            if bridges:
                parts.append("read " + ", ".join(f"{a} as your playlist's “{b}”"
                                                 for a, b in bridges))
            return {"match": terms[:MAX_TERMS], "exclude": exclude_tokens[:MAX_TERMS],
                    "kind": kind, "groups": hit_groups,
                    "why": ("matched your playlist's own categories on this machine's CPU — "
                            + "; ".join(parts) + " — no model, no wait for the GPU"),
                    "source": "local", "model_used": False, "ok": True}

    # ---- 2. ambiguous. Ask the model, if the caller gave us a way to.
    if ask_model is not None and q:
        try:
            terms = parse_model_line(ask_model(build_prompt(q)))
        except ModelUnusable as exc:
            reason = str(exc)
        except Exception as exc:                        # noqa: BLE001 -- reported, not hidden
            reason = f"{exc.__class__.__name__}: {exc}"
        else:
            # Per keyword, not over the union of every keyword's tokens: "sky sports" and
            # "epl" are separate claims, and pooling their tokens invents a phrase the model
            # never said.
            model_groups: list[str] = []
            for term in terms:
                hits, _ = _group_hits(term.split(), clusters)
                model_groups.extend(hits)
            model_groups = list(dict.fromkeys(model_groups))
            return {"match": terms, "exclude": exclude_tokens[:MAX_TERMS],
                    "kind": kind, "groups": model_groups,
                    "why": ("the model read your question and searched for: "
                            + ", ".join(terms)),
                    "source": "model", "model_used": True, "ok": True}
    else:
        reason = ("no model was available" if q else "there was no question to work from")

    # ---- 3. fallback, and it says so out loud.
    terms = [t for t in include_tokens
             if t not in by_group and (len(t) >= _MIN_TERM or t in by_name)][:MAX_TERMS]
    if not terms and not kind and not hit_groups:
        return {"match": [], "exclude": exclude_tokens[:MAX_TERMS], "kind": None, "groups": [],
                "why": (f"no filter could be derived from that question ({reason}) — nothing "
                        "has been filtered, and this is not a match-everything result"),
                "source": "fallback", "model_used": False, "ok": False}
    return {"match": terms, "exclude": exclude_tokens[:MAX_TERMS], "kind": kind,
            "groups": hit_groups,
            "why": (f"{reason}, so this matched your own words directly: "
                    + (", ".join(terms) if terms else f"kind {kind}")),
            "source": "fallback", "model_used": False, "ok": True}


def apply_filter(channels: Iterable[Any], filt: dict) -> list[Any]:
    """Apply a filter to a channel list. Pure CPU; never sees a URL.

    A channel is kept when its kind matches (if one was asked for), no exclusion term appears
    in its name or group, and either it sits in one of the selected groups or one of the search
    terms appears in its name or group.

    **An underived filter (`ok` False) matches nothing, deliberately.** Returning the whole
    list would render identically to a filter that worked, which is the exact dishonesty
    `.claude/HANDOVER.md` §2c-bis warns about.
    """
    if not filt or not filt.get("ok"):
        return []
    kind = normalise_kind(filt.get("kind"))
    groups = {g for g in (filt.get("groups") or []) if g}
    match = [t for t in (filt.get("match") or []) if t]
    exclude = [t for t in (filt.get("exclude") or []) if t]
    if not (match or groups or kind):
        # `ok` says a filter was derived and the fields say it was not. Believe the fields:
        # the tail of this function admits everything when there is nothing to restrict on,
        # and "every channel" must never be reachable from a result labelled as a filter.
        return []

    kept = []
    for ch in channels:
        # `kind_of`, not the raw field: a film the URL could not classify is still a film, and
        # filtering on the raw field is what leaves the Movies category empty.
        if kind and kind_of(ch) != kind:
            continue
        hay = _fold(_get(ch, "name") + " " + _get(ch, "group"))
        if any(_fold(t) in hay for t in exclude):
            continue
        if groups and _get(ch, "group") in groups:
            kept.append(ch)
            continue
        if match:
            if any(_fold(t) in hay for t in match):
                kept.append(ch)
            continue
        if not groups:
            kept.append(ch)          # kind-only filter, e.g. "movies"
    return kept


# ---------------------------------------------------------------- the rack

def unit_state() -> tuple[str, str]:
    """(state, detail) for the rack, mirroring `apps/asicminer.unit_state`.

    **`ready`, always, and that is the honest answer rather than a convenient one.** Guide's
    job is turning a question into a filter over strings the visitor supplies. It owns no
    hardware to be disconnected from, no weights to fail to load, and no configuration to be
    missing -- `.claude/CLAUDE.md`'s stdlib-only serving path is all it needs. It answers while
    the card is loading, while chat holds the lock, and while a QLoRA run has the whole GPU,
    which is precisely why the local pass exists and is the same claim RavenCalc makes.

    The word matters: `site/console.js` lights the green LED for any state that is not exactly
    `offline` (`console.js:47`), so a new state word here would be an unlit-looking unit or an
    LED whose colour means nothing. `ready` is the existing vocabulary and it is true.

    The detail says outright that the model half is borrowed, because a unit claiming `ready`
    on a contended box must say what it does *not* depend on.
    """
    return "ready", ("CPU/stdlib matching — no weights of its own, never takes the GPU lock; "
                     "the optional model pass borrows the chat surface")
