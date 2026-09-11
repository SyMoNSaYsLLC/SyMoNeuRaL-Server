# SyMoNeuRaL Guide

A question in, a channel filter out, for the Streamer. **It owns no model weights and it is not
wired into `backend/server.py` yet** — this directory is the module and its tests; the wiring
snippet is at the bottom for whoever owns `api.py`.

Garrett's words, which set the scope:

> *"we need the symoneural chat to have a floating prompt for setting up the guide with
> selected subcategories. I want the agent to streamline a very quick filtering of all the
> channels and categories. We could bring a symoneural guide in as an agent if it should be
> separate of chat or streamer."*

---

## 1. Guide is a rack unit with no weights, on purpose

The card is 15.92 GiB. Chat (~5 GB) and image (~7 GB) already cannot co-reside, which is the
reason `scripts/gpu-governor.sh` exists at all. A Guide with its own model would be a **third
tenant fighting for that card to answer a question about strings**.

So it has none. When it needs a model it asks the chat surface, exactly as `remix()` does:

> *"Remix has no weights of its own — it asks the chat surface, which is what 'one server
> underneath' means in practice, and why it queues behind chat and image."*
> — `backend/server.py`

Concretely, this module never imports the API, never touches the governor, and never opens a
socket. The caller injects `ask_model`, a `str -> str` callable, and owns whatever it does
about the lock. That is what makes the whole thing testable with no card, no network and no
service running — `test_guide.py`'s 46 tests run in 10 ms.

## 2. Local first. The model is the exception, not the path

`.claude/CLAUDE.md`: *"RavenCalc (SymPy, CPU) deliberately never takes the lock. That is what
lets it speculatively pre-compute while the GPU is loading."*

The same argument is stronger here, because **most IPTV filtering is not a language problem**.
"uk sports", "movies", "bbc" are answered by matching strings the visitor's own playlist
already contains: stdlib, pure CPU, and it works while a QLoRA run holds the whole card.

Measured on this box (`python3` 3.13.5, system interpreter, synthetic 20,000-channel playlist,
64 distinct groups — no GPU involved at any point):

| Operation | Time |
|---|---|
| `catalogue()` over 20,000 channels | **0.12 s** |
| `filter_from_question()`, local path, 20,000 `names` supplied | **52 ms** |
| `filter_from_question()` with `clusters=` precomputed and no `names` | **0.2 ms** |
| `apply_filter()` over 20,000 channels | **74 ms** |
| the whole test suite, 46 tests | **0.010 s** |

Those are *measured*, in this repo's sense of the word. The comparison figure is not: one chat
turn on this machine is hundreds of milliseconds to seconds **plus** any queue behind image or
a fine-tune. That is the whole argument for doing the string work locally.

### The escalation rule, stated rather than judged

> The local pass is trusted only when **every content word in the question is accounted for by
> the playlist's own vocabulary** — a whole-token hit on a group name or a channel name, or a
> `difflib` ratio of at least `FUZZY_CUTOFF` (**0.82**) against a normalised group name.
> Anything left over is ambiguous and goes to the model.

So "uk sports" is local (both words are in `UK| SPORTS`), and "premier league football" is not
(no group says "premier"), which is exactly right: the second one needs world knowledge that a
`group-title` string does not carry.

Matching is **whole-token, never substring** — `show` must not select `Showtime`.

## 3. The output format is a flat list, because that is what this 7B can finish

`.claude/HANDOVER.md` §2c-bis, measured rather than theorised. Asked for a **JSON object**, the
model looped:

```
{"match":["premier league","nfl","nba","mlb","f1","nfl","nba",…
```

until the token cap. The object never closed, nothing parsed, and the fallback fired on **every
request while the feature looked fine**.

Two consequences are structural here:

**One prompt, one line, one field.** `kind`, `groups` and `exclude` are derived locally,
deterministically, from the question and the playlist's own vocabulary. They are cheap and
exact, and asking the model for them would mean either a nested object (the failure above) or
three round trips against a contended card. The prompt, verbatim (`PROMPT_TEMPLATE`):

```
List the words to search for in a TV channel list to find: {question}

Rules: reply with ONE line, at most 8 lowercase keywords, comma separated. No sentences, no repeats, no quotes, no brackets, no JSON, no explanation.

Keywords:
```

The playlist is **not** in that prompt. One call to the card per question, not one per channel,
and there is nothing of the visitor's to leak.

**`parse_model_line` rejects that exact string, and a naive parser does not.** Split the loop on
commas and you get `match":["premier league`, `nfl`, `nba`, `mlb`, `f1` — a non-empty list of
plausible-looking tokens that passes any "did we get keywords?" test. So there are two
independent rules:

1. **structural punctuation** — any of `{ } [ ] " :` means the model started emitting an object
   it will not finish, and the whole answer goes;
2. **repeats** — a duplicate token is the signature of the loop.

One exception, and it is the mirror-image trap: **the prompt ends in `Keywords:` and this 7B
routinely echoes the label.** `Keywords: sports, football` is a perfect answer that contains a
colon, so testing for structure before stripping the label rejected healthy output and fired
the fallback on *every* request with a reason that was false — §3.0d's "verification step that
fails on healthy input", which is how a check gets switched off and then protects nothing. The
label is stripped first; the structural test is unchanged. Both directions are asserted.

`test_guide.py::test_the_documented_loop_is_rejected` runs the literal string from the handover
through both, and asserts that the naive parser would have accepted it. That last assertion is
what stops the test being vacuous.

## 4. The fallback is observable. There is no silent happy path

Every result carries its own provenance and `why` is written to be shown to the visitor:

```python
{"match": ["tom hanks"],     # search terms, lowercase
 "exclude": ["news"],        # terms that disqualify a channel
 "kind": "vod",              # live | series | vod | None  -- never "movie"
 "groups": ["UK| SPORTS"],   # ORIGINAL strings from the playlist
 "why": "...",               # shown to the user; names its own provenance
 "source": "local",          # local | model | fallback
 "model_used": False,        # two-value discriminator, see below
 "ok": True}                 # False = no filter could be derived. NOT "match everything".
```

**`ok=False` is a positive signal, not an absence.** `apply_filter` returns **no** channels for
it. Handing back the unfiltered playlist would render identically to a filter that worked,
which is the failure §2c-bis is about.

**A local result must actually restrict something, and that is guarded rather than reasoned
about.** It failed once: `bt` is BT Sport and is two characters, so it entered the local branch
on a channel-name hit and was then dropped by the minimum-term floor — leaving
`match=[] groups=[] kind=None ok=True`, and `apply_filter` handed back **every channel** under
a `why` claiming a local category match. The floor no longer applies to a token the playlist's
own names contain, and both `filter_from_question` and `apply_filter` now refuse to return
anything when nothing restricts. `test_no_local_result_is_ever_a_match_everything` walks
fourteen questions and asserts neither.

### One decision for the owner: `source` has three values, not two

The brief specified `source: "model"|"fallback"`, and also required a local-first fast path.
Those cannot both be honest — a local CPU match is neither the model nor a fallback from it, and
labelling it either way misreports where the answer came from on the majority of requests.

So `source` is **`local` | `model` | `fallback`**, and there is also **`model_used: bool`** as
an unambiguous two-value discriminator for any frontend that wants one. `model_used` is `True`
if and only if `source == "model"`, asserted in `test_every_result_declares_its_provenance`.

Say so or change it — but a two-value field cannot carry three provenances.

## 5. Kind vocabulary: `live`, `series`, `vod`

`backend/apps/streamer/m3u.py::_classify()` emits exactly those three and **never** `movie`. A
frontend testing for `"movie"` is why "we are completely missing the movie category" was
reported.

This module **accepts** `movie`, `movies`, `film`, `films`, `cinema`, `ondemand` as input
aliases — on the question text *and* on the `kinds` vocabulary argument — and **never emits**
`movie`. `test_movie_is_never_emitted` asserts it across ten phrasings.

When a question names two kinds the more specific wins (`series` > `vod` > `live`), so "movie
channels" is `vod`. Reading it as `live` would filter to exactly the wrong half of a playlist.

When the question asks for a kind the loaded playlist does not contain, the result is
`ok=False` with *"this playlist has no vod entries, so there is nothing to filter to"* — not a
silently widened filter.

## 5b. "Adult live TV seems to be being blocked" — it was not blocked

Reported by Garrett, 2026-08-17. **Nothing in this repo blocks it.** There is no denylist in
this module (asserted by `test_this_module_carries_no_denylist`), and `denied()` in
`backend/server.py` guards `/api/image` only, on the single narrow intersection that is illegal to
produce — it is not on `/api/chat` and not on the Streamer at all.

What looked like blocking was three ordinary bugs stacked, each now fixed and tested:

1. **The visitor's word is not the playlist's word.** They type "adult"; every group is called
   `XXX`, `18+` or `FOR ADULTS`; no string matched. `_SYNONYMS` bridges the two — **but only
   when the alternative is already in that playlist's group vocabulary**, so nothing is ever
   invented, and `why` names the bridge out loud ("read adult as your playlist's *XXX*"). All
   matching alternatives are taken, not the first: a playlist carries `XXX`, `18+` and
   `FOR ADULTS` as three separate groups and returning one of them is a data drop.
2. **A refusal was being laundered into a filter — this is the one that reads as censorship.**
   The chat model carries a trained persona and trained refusals, so `"I'm sorry, but I can't
   help with that."` comma-split to `["i'm sorry"]`: a filter matching zero channels, reported
   as `source: "model"`. A visitor cannot tell that apart from the category being censored.
   `parse_model_line` now rejects refusals and prose explicitly, and the fallback says
   *"the model refused the question rather than answering it"*.
3. **Nothing needs the model for this anyway.** With the bridge in place "adult live tv" is
   answered by the local CPU pass in under a millisecond, so the refusal path is never reached
   and the question never leaves the box.

## 5c. "Still missing movies" — the frontend chip is only half of it

The known half: the Streamer's frontend tests for `"movie"`, which `_classify()` never emits.
Another agent owns that fix, and this module speaks the backend's vocabulary (§5).

**The other half is upstream and nobody has filed it.** `m3u.py::_classify()` guesses kind from
the URL shape and says so in its own docstring — *"honestly wrong-by-default (`live`)
otherwise"*. Xtream panels build `/movie/<u>/<p>/<id>.mp4` and classify correctly; a plain M3U
export whose films are `.../12345.mp4` under `group-title="VOD | Movies"` has **no `/movie/`
segment**, so every film arrives marked `live` and the Movies category is empty however the
frontend spells it.

`kind_of(channel)` reconsiders the `live` **default only**, against the group title the
provider wrote (`_GROUP_KIND_HINTS`). An explicit `vod` or `series` from the URL is
authoritative and never overridden, nothing is written back to the channel object, and
`catalogue(channels, use_group_hint=False)` turns it off.

The cost, stated rather than hidden: a genuinely linear "24/7 Movies" channel counts as `vod`
under this rule. That is the wrong half of a trade whose other half is a Movies category that
is empty on most real playlists.

Related: asking for "movies" on a playlist whose `kind` field says `live` everywhere no longer
answers *"this playlist has no vod entries"*. It looks at the group titles first and selects
`VOD | Movies` instead — telling somebody staring at a Movies category that they have no movies
is the most confusing possible way to be right.

**This is a real bug in `backend/apps/streamer/m3u.py`, not just a Guide concern.** Guide works
around it for anything routed through Guide; the Streamer's own kind chips are still counted from
the raw field and will still under-report movies until `_classify()` consults `group-title`.
Whoever owns that file should decide — one line in `_classify()`, or leave it and let the
group hint live here.

## 6. Category / subcategory grouping

`catalogue(channels)` derives everything a category picker needs from what the visitor actually
loaded, never from a fixed list:

```python
{"total": 6,
 "kinds": {"live": 4, "series": 1, "vod": 1},   # always all three keys, zeros included
 "groups": [cluster, ...],                      # each with a per-kind breakdown
 "ungrouped": 0,
 "fuzzy": True}
```

A cluster collapses near-duplicate spellings **without losing a single original**:

```python
{"key": "sports uk",                                       # canonical, for matching only
 "display": "UK| SPORTS",                                  # ONE OF THE ORIGINALS
 "originals": ["Sports UK", "UK - Sports", "UK| SPORTS"],  # every spelling, all of them
 "count": 3,
 "kinds": {"live": 3, "series": 0, "vod": 0}}
```

**`groups` in a filter result is always original strings.** Returning the canonical key would
match zero channels *and* drop data at the same time — `.claude/CLAUDE.md`'s "layout changes
must not drop data", one layer below the layout.

Merging is by **tokens, not characters**, and this is not a stylistic preference:

- `UK| SPORTS`, `UK - Sports`, `Sports UK` → one cluster (identical token sets, sorted).
- `SPORTS 1` vs `SPORTS 2` → **never** merged. They score 0.875 character-wise, above the
  cutoff. Numeric tokens must match exactly first.
- `sports uk` vs `sports us` → **never** merged. Measured at **0.889** character-wise, so a
  plain `difflib` ratio merged UK and US Sports and "uk sports" returned **535 American
  channels while honestly reporting `source: local`**. A confident wrong answer is the worst
  kind, and it was found by running a synthetic playlist rather than by reading the code. A
  differing token must be at least 4 characters before it is fuzz-matched at all.
- `UK| SPORTS` vs `UK| SPORTS HD` → merged; `hd`/`sd`/`4k` describe the feed, not the category.
- `UK| SPORT` vs `UK| SPORTS` → merged (one differing token, ≥4 chars, ratio 0.91).

Above `MAX_FUZZY_GROUPS` (**1200**) distinct groups the fuzzy pass is skipped for cost and
`catalogue()["fuzzy"]` reports `False`. It is reported rather than assumed: a UI that says
"near-duplicate groups merged" needs to know when that did not happen.

### The stopword list is decided by the playlist, not by English

`us` is a pronoun and the United States. With `us` stripped as a stopword, "us sports" filtered
to **every** sports group in the 20,000-channel playlist — 2,473 channels, reported as a
confident local match. Same collision for `it` (Italy), `in` (India), `at` (Austria), `be`,
`is`, `me`, `no`.

Rather than curate exceptions that will be wrong for the next playlist: **a stopword that
appears in a group title is a category name here and is kept.** Group titles only — channel
*names* contain `the` and `and` constantly, and rescuing from those would strip nothing.

## 7. It stores nothing

No module-level cache, no disk, no logging, no globals. Channels arrive as arguments and leave
as arguments; two identical calls either side of a different playlist return identical results
(`test_the_module_holds_nothing_between_calls`).

Nothing here ever reads or returns a channel `url` — names and group titles only — because a
playlist URL carries the visitor's credentials in its path.
`.claude/HANDOVER.md`: *"Credentials: visitor supplies their own, localStorage only, never
stored on the box."* `test_nothing_returned_ever_carries_a_url` asserts it against fixtures
that do have URLs.

Every fixture in the tests is synthetic and was written here. No playlist from `references/` is
read, quoted or shipped — the same rule `m3u.py` states for itself, for the same reason.

## 8. The rack unit: `ready`, and why that is honest

```python
unit_state() -> ("ready", "CPU/stdlib matching — no weights of its own, never takes the GPU "
                          "lock; the optional model pass borrows the chat surface")
```

Guide has no hardware to be disconnected from, no weights to fail to load and no configuration
to be missing, so `ready` is not a convenient answer — it is the true one. It answers while the
card is loading, while chat holds the lock, and while a fine-tune has the whole GPU. That is
the same claim RavenCalc makes and it is the reason the local pass exists.

**The word matters.** `site/console.js:47` is `u.state === 'offline' ? 'led' : 'led on'` — any
state that is not exactly `offline` lights the green LED. Inventing a new state word here would
light an LED that means nothing, which is the decorative indicator this site argues against.
`ready` is the existing vocabulary.

The detail line says outright what it does *not* depend on, because a unit claiming `ready` on
a one-GPU box owes the reader that.

## 9. Tests

```bash
python3 backend/apps/streamer/guide/test_guide.py     # 46 tests, 0.010s, no GPU, no network
```

Stdlib `unittest` on the system interpreter. **No new Python packages** — `difflib`,
`unicodedata`, `re` and `collections` are all that is used, and the serving path has no
virtualenv by design.

## 10. Wiring — NOT applied, for whoever owns `api.py`

Guide is a library. It is deliberately not wired in: `backend/server.py`, `backend/apps/streamer/`,
`tools/build/build_pages.py` and `site/` all belong to other agents in this session.

The two-export contract mirrors `apps/streamer/__init__.py`:

```python
from apps.streamer import guide

# 1. the rack unit
state, detail = guide.unit_state()          # -> ("ready", "...")

# 2. a route. `ask_model` is the caller's own route to the chat surface -- this is the
#    ONLY place the GPU is involved, and it is the caller that holds the lock, exactly as
#    remix() does.
@app.post("/api/streamer/guide/filter", tags=["streamer-guide"])
async def guide_filter(body: GuideRequest) -> dict:
    async def ask(prompt: str) -> str: ...   # async: see the note below
    return guide.filter_from_question(
        body.question, body.kinds, body.groups,
        names=body.names, ask_model=ask_sync)
```

Four notes for that wiring, each one a real trap:

1. **`ask_model` is a synchronous `str -> str` callable.** `filter_from_question` is a plain
   function, so an async chat call needs `asyncio.run_coroutine_threadsafe` from a worker
   thread, or the route should run the whole thing under `asyncio.to_thread` as
   `/api/ravencalc` already does. Do not make this module `async` to avoid that — it would drag
   an event loop into something that is ~50 ms of string work.
2. **Take the GPU lock in the route, not here.** `async with gpu.hold("chat")` around the model
   call only, and only when the local pass has already declined. Holding it around the local
   pass would put a CPU string match behind the image surface.
3. **The `groups` and `kinds` arguments are the vocabulary from the visitor's *loaded*
   playlist**, not a fixed list. Pass `catalogue()["groups"]` through `clusters=` for a big
   playlist and skip the ~120 ms re-cluster per keystroke.
4. **Rate-limit it as a chat client**, the way `remix` is bucketed in `api.py`'s limits table —
   a filter request that escalates costs exactly one chat turn.

## 11. Open, for Garrett to decide

1. **Three-valued `source`** — §4. The brief said two; three is what can be told honestly.
1b. **`_classify()` in `backend/apps/streamer/m3u.py` under-reports movies** — §5c. Guide works
   around it; the Streamer's own kind chips do not. One line in a file this agent does not own.
2. **Is Guide its own rack unit, or a capability of the Streamer?** Built as its own module so it
   can be either. As a ninth unit it is honest (`ready`, no weights) but it is the first unit
   on the rack that owns no hardware *and* no weights, and the rack's whole argument is that
   each unit is a real thing on a real machine. As a Streamer capability it disappears from the
   rack and the floating prompt is just part of the Streamer page. **Recommend: a capability of
   the Streamer**, listed on the Streamer's own page rather than as a ninth chassis line — but this
   is a product call, not an engineering one.
3. **Should the model pass be allowed to run at all when chat is busy?** It queues behind chat
   and image like Remix does. For a filter box the visitor is typing into, a 20-second queue is
   worse than "the local pass could not work this one out". A timeout on `ask_model` in the
   route, reported through `why` (the fallback already names the exception class), is probably
   the right answer.
4. **`names` is optional and costs ~50 ms per call for 20,000 channels.** Sending 20,000
   channel names to the API on every keystroke is the wrong shape; the browser holds the
   playlist already. Consider running the local pass **in the browser** and only calling the
   API when it declines — this module's logic is small enough to mirror, but two copies of a
   matching rule in two languages is exactly the drift `.claude/HANDOVER.md` warns about with
   the 1301px breakpoint. Decide deliberately.
