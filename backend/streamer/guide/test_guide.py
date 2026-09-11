#!/usr/bin/env python3
"""Tests for SyMoNeuRaL Guide. System interpreter, stdlib only, no network, no GPU, no card.

    python3 backend/streamer/guide/test_guide.py

Every fixture in this file is synthetic and was written here. No playlist from `external/`
is read, quoted or shipped -- those files carry real provider credentials in their URLs, which
is the same rule `backend/streamer/m3u.py` states for itself. The fixtures carry no `url`
field at all, and one test asserts that nothing this module returns ever contains one.

The tests that matter most are the ones about the model, and they exist because of a measured
failure rather than a theoretical one (`.claude/HANDOVER.md` §2c-bis): a 7B asked for a JSON
object looped until the token cap, so nothing parsed and the fallback fired on every request
while the feature appeared to work. `test_the_documented_loop_is_rejected` runs the literal
prefix from that report through the parser.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

from streamer import guide  # noqa: E402


# A small synthetic playlist. Three spellings of one sports group on purpose, a numbered pair
# on purpose, and the three kinds `m3u.py::_classify()` actually emits.
CHANNELS = [
    {"name": "Sky Sports Main Event", "group": "UK| SPORTS", "kind": "live"},
    {"name": "BT Sport 1", "group": "UK - Sports", "kind": "live"},
    {"name": "Premier Sports Extra", "group": "Sports UK", "kind": "live"},
    {"name": "BBC News", "group": "UK| NEWS", "kind": "live"},
    {"name": "The Matrix", "group": "VOD | Movies", "kind": "vod"},
    {"name": "Breaking Bad S01E01", "group": "Series | Drama", "kind": "series"},
]
GROUPS = [c["group"] for c in CHANNELS]
KINDS = ["live", "vod", "series"]
NAMES = [c["name"] for c in CHANNELS]

#: The literal prefix recorded in HANDOVER §2c-bis. Truncated exactly as the model left it --
#: the object never closed, which is the whole problem.
LOOP = '{"match":["premier league","nfl","nba","mlb","f1","nfl","nba","mlb","f1","nfl"'


class Recorder:
    """An `ask_model` that records whether it was called. The local-path test asserts the
    callable was never invoked, not merely that `source` came back as something else."""

    def __init__(self, reply: str = "") -> None:
        self.reply = reply
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.reply


# ------------------------------------------------------------------ the local fast path

class LocalFastPath(unittest.TestCase):

    def test_group_question_is_answered_without_the_model(self):
        model = Recorder("should never be reached")
        r = guide.filter_from_question("uk sports", KINDS, GROUPS,
                                       ask_model=model, names=NAMES)
        self.assertEqual(model.calls, [], "the local pass must not call the card")
        self.assertEqual(r["source"], "local")
        self.assertFalse(r["model_used"])
        self.assertTrue(r["ok"])
        # Every spelling of the group comes back, as ORIGINAL strings -- a canonical key
        # would match zero channels.
        self.assertEqual(set(r["groups"]), {"UK| SPORTS", "UK - Sports", "Sports UK"})
        self.assertNotIn("UK| NEWS", r["groups"])
        kept = guide.apply_filter(CHANNELS, r)
        self.assertEqual([c["name"] for c in kept],
                         ["Sky Sports Main Event", "BT Sport 1", "Premier Sports Extra"])

    def test_a_channel_name_is_enough_on_its_own(self):
        model = Recorder()
        r = guide.filter_from_question("bbc", KINDS, GROUPS, ask_model=model, names=NAMES)
        self.assertEqual(model.calls, [])
        self.assertEqual(r["source"], "local")
        self.assertEqual([c["name"] for c in guide.apply_filter(CHANNELS, r)], ["BBC News"])

    def test_a_fuzzy_group_still_resolves_locally(self):
        r = guide.filter_from_question("uk sport", KINDS, GROUPS, names=NAMES)
        self.assertEqual(r["source"], "local")
        self.assertEqual(len(guide.apply_filter(CHANNELS, r)), 3)

    def test_exclusions_are_read_per_clause(self):
        r = guide.filter_from_question("uk channels but not sports", KINDS, GROUPS,
                                       names=NAMES)
        self.assertIn("sports", r["exclude"])
        names = [c["name"] for c in guide.apply_filter(CHANNELS, r)]
        self.assertIn("BBC News", names)
        self.assertNotIn("Sky Sports Main Event", names)

    def test_a_two_letter_channel_name_still_filters(self):
        # `bt` is BT Sport and is two characters. The minimum-term floor dropped it AFTER the
        # local branch had already been entered on the strength of it, so the result was
        # match=[], groups=[], kind=None, ok=True -- and `apply_filter` handed back EVERY
        # channel under a `why` claiming a local category match. The floor does not apply to a
        # token the playlist's own channel names contain.
        r = guide.filter_from_question("bt", ["live"], GROUPS, names=NAMES)
        self.assertEqual(r["match"], ["bt"])
        self.assertEqual([c["name"] for c in guide.apply_filter(CHANNELS, r)], ["BT Sport 1"])

    def test_no_local_result_is_ever_a_match_everything(self):
        questions = ["bt", "e4", "uk", "uk sports", "movies", "series", "bbc", "uk news",
                     "sports", "show me everything", "the", "a", "4", "xyzzy"]
        for q in questions:
            r = guide.filter_from_question(q, KINDS, GROUPS, names=NAMES)
            if r["ok"]:
                self.assertTrue(r["match"] or r["groups"] or r["kind"],
                                f"{q!r} claims a filter and carries none: {r}")
            kept = guide.apply_filter(CHANNELS, r)
            self.assertLess(len(kept), len(CHANNELS),
                            f"{q!r} returned the whole playlist: {r}")

    def test_the_escalation_rule_and_the_cutoff_cannot_drift_apart(self):
        # `_LOCAL_RULE` is the sentence the README quotes for what "ambiguous" means. Two
        # copies of a number in two files is how the 1301px breakpoint went wrong; this ties
        # the prose to the constant.
        self.assertIn(str(guide.FUZZY_CUTOFF), guide._LOCAL_RULE)

    def test_the_why_names_its_own_provenance(self):
        r = guide.filter_from_question("uk sports", KINDS, GROUPS, names=NAMES)
        self.assertIn("no model", r["why"])
        self.assertIn("CPU", r["why"])


# ------------------------------------------------------------------ kind vocabulary

class KindVocabulary(unittest.TestCase):

    def test_movie_is_accepted_on_input_and_mapped_to_vod(self):
        self.assertEqual(guide.normalise_kind("movie"), "vod")
        self.assertEqual(guide.normalise_kind("Movies"), "vod")
        self.assertEqual(guide.normalise_kind("film"), "vod")
        # And as a vocabulary argument: a caller still saying "movie" must not filter to
        # nothing, which is the live bug in the Streamer's frontend.
        r = guide.filter_from_question("movies", ["live", "movie", "series"], GROUPS,
                                       names=NAMES)
        self.assertEqual(r["kind"], "vod")
        self.assertEqual([c["name"] for c in guide.apply_filter(CHANNELS, r)], ["The Matrix"])

    def test_movie_is_never_emitted(self):
        asked = ["movies", "movie night", "films", "a film about sport", "live tv",
                 "tv series", "box set", "on demand", "vod", "series"]
        for q in asked:
            r = guide.filter_from_question(q, KINDS, GROUPS, names=NAMES)
            self.assertIn(r["kind"], (None, "live", "series", "vod"), q)
            self.assertNotEqual(r["kind"], "movie", q)
            self.assertNotIn("movie", json.dumps({k: r[k] for k in ("kind", "groups")}), q)

    def test_the_more_specific_kind_wins(self):
        self.assertEqual(guide.kind_from_question("movie channels")[0], "vod")
        self.assertEqual(guide.kind_from_question("tv series")[0], "series")
        self.assertEqual(guide.kind_from_question("live tv")[0], "live")

    def test_a_kind_the_playlist_does_not_have_is_said_out_loud(self):
        # A playlist of live channels only -- no group hints a film either.
        r = guide.filter_from_question("movies", ["live"], ["UK| SPORTS", "UK| NEWS"])
        self.assertFalse(r["ok"])
        self.assertIn("no vod", r["why"])
        self.assertEqual(guide.apply_filter(CHANNELS, r), [])

    def test_movies_the_url_could_not_classify_are_still_movies(self):
        # THE OTHER HALF OF "still missing movies", and it is upstream of this module:
        # `m3u.py::_classify()` reads the URL shape, so a plain M3U whose films are
        # `.../12345.mp4` with no `/movie/` segment arrives with every film marked `live`.
        # The group title says otherwise and is believed for the `live` DEFAULT only.
        pl = [{"name": "The Matrix (1999)", "group": "VOD | Movies", "kind": "live"},
              {"name": "Breaking Bad S01E01", "group": "Series | Drama", "kind": "live"},
              {"name": "Sky Sports Main Event", "group": "UK| SPORTS", "kind": "live"}]
        self.assertEqual(guide.catalogue(pl)["kinds"], {"live": 1, "series": 1, "vod": 1})
        self.assertEqual(guide.kind_of(pl[0]), "vod")
        self.assertEqual(guide.kind_of(pl[2]), "live")
        # Off by request, for a caller that wants the raw classification.
        self.assertEqual(guide.catalogue(pl, use_group_hint=False)["kinds"],
                         {"live": 3, "series": 0, "vod": 0})
        # And the question works whichever vocabulary the caller passes.
        for kinds in (["live"], ["live", "vod", "series"]):
            r = guide.filter_from_question("movies", kinds, [c["group"] for c in pl])
            self.assertTrue(r["ok"], kinds)
            self.assertEqual([c["name"] for c in guide.apply_filter(pl, r)],
                             ["The Matrix (1999)"], kinds)

    def test_an_explicit_classification_is_never_overridden(self):
        # A 24/7 linear channel sitting in a Movies group is the known cost of the hint. An
        # explicit vod/series from the URL is authoritative and must survive.
        self.assertEqual(guide.kind_of({"group": "VOD | Movies", "kind": "series"}), "series")
        self.assertEqual(guide.kind_of({"group": "UK| SPORTS", "kind": "vod"}), "vod")


# ------------------------------------------------------------------ group normalisation

class GroupNormalisation(unittest.TestCase):

    def test_three_spellings_collapse_and_every_original_survives(self):
        clusters = guide.cluster_groups(GROUPS)
        sports = [c for c in clusters if "sports" in c["key"] or "sport" in c["key"]]
        self.assertEqual(len(sports), 1, [c["key"] for c in clusters])
        c = sports[0]
        self.assertEqual(c["key"], "sports uk")
        self.assertEqual(c["originals"], ["Sports UK", "UK - Sports", "UK| SPORTS"])
        self.assertIn(c["display"], c["originals"],
                      "display must be a real string from the playlist, not a synthesised one")
        self.assertEqual(c["count"], 3)

    def test_news_is_not_swallowed_by_sports(self):
        keys = {c["key"] for c in guide.cluster_groups(GROUPS)}
        self.assertIn("news uk", keys)

    def test_numbered_groups_are_never_merged(self):
        clusters = guide.cluster_groups(["SPORTS 1", "SPORTS 2", "SPORTS 1 HD"])
        keys = sorted(c["key"] for c in clusters)
        self.assertEqual(keys, ["1 sports", "2 sports"],
                         "SPORTS 1 and SPORTS 2 are different categories")
        one = [c for c in clusters if c["key"] == "1 sports"][0]
        self.assertEqual(one["originals"], ["SPORTS 1", "SPORTS 1 HD"])

    def test_two_countries_are_not_one_category(self):
        # Found by running a synthetic 20,000-channel playlist through this module rather than
        # by reading the code: `sports uk` and `sports us` score 0.889 character-wise, so a
        # plain difflib ratio merged them and "uk sports" returned 535 American channels while
        # honestly reporting `source: local`. A confident wrong answer is the worst kind.
        clusters = guide.cluster_groups(["UK| SPORTS", "US| SPORTS", "DE| SPORTS"])
        self.assertEqual(len(clusters), 3, [c["originals"] for c in clusters])
        r = guide.filter_from_question("uk sports", ["live"],
                                       ["UK| SPORTS", "US| SPORTS", "DE| SPORTS"])
        self.assertEqual(r["groups"], ["UK| SPORTS"])

    def test_a_quality_suffix_is_the_same_category(self):
        clusters = guide.cluster_groups(["UK| SPORTS", "UK| SPORTS HD", "UK Sports 4K"])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["originals"],
                         ["UK Sports 4K", "UK| SPORTS", "UK| SPORTS HD"])

    def test_singular_and_plural_are_the_same_category(self):
        clusters = guide.cluster_groups(["UK| SPORT", "UK| SPORTS"])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["count"], 2)

    def test_a_country_code_that_is_also_a_stopword_still_filters(self):
        # `us` is an English pronoun and the United States. Stripped as a stopword it made
        # "us sports" select every sports group in a 20,000-channel playlist -- 2,473 channels,
        # reported as a confident local match. The playlist's own group titles now win.
        groups = ["US| SPORTS", "UK| SPORTS", "IT| SPORTS", "ES| SPORTS"]
        r = guide.filter_from_question("us sports", ["live"], groups)
        self.assertEqual(r["source"], "local")
        self.assertEqual(r["groups"], ["US| SPORTS"])
        # `it` is Italy here for the same reason.
        self.assertEqual(guide.filter_from_question("it sports", ["live"], groups)["groups"],
                         ["IT| SPORTS"])
        # And a stopword the playlist does NOT use is still a stopword.
        r = guide.filter_from_question("show me the sports", ["live"], groups)
        self.assertEqual(len(r["groups"]), 4, "every sports group, none of them named 'the'")

    def test_a_precomputed_catalogue_gives_the_same_answer(self):
        cat = guide.catalogue(CHANNELS)
        a = guide.filter_from_question("uk sports", KINDS, GROUPS, names=NAMES)
        b = guide.filter_from_question("uk sports", KINDS, [], names=NAMES,
                                       clusters=cat["groups"])
        self.assertEqual(a, b)

    def test_catalogue_counts_what_was_loaded(self):
        cat = guide.catalogue(CHANNELS)
        self.assertEqual(cat["total"], 6)
        self.assertEqual(cat["kinds"], {"live": 4, "series": 1, "vod": 1})
        self.assertEqual(cat["ungrouped"], 0)
        self.assertTrue(cat["fuzzy"])
        sports = [c for c in cat["groups"] if c["key"] == "sports uk"][0]
        self.assertEqual(sports["count"], 3)
        self.assertEqual(sports["kinds"], {"live": 3, "series": 0, "vod": 0})
        self.assertEqual(cat["groups"][0]["key"], "sports uk", "biggest category first")

    def test_an_ungrouped_channel_is_counted_not_invented_into_a_group(self):
        cat = guide.catalogue([{"name": "Loose", "group": "", "kind": "live"}])
        self.assertEqual(cat["ungrouped"], 1)
        self.assertEqual(cat["groups"], [])


# ------------------------------------------------------------------ the model half

class ModelHalf(unittest.TestCase):

    def test_the_prompt_is_one_flat_line_and_holds_no_playlist(self):
        p = guide.build_prompt("premier league football")
        self.assertIn("ONE line", p)
        self.assertIn("comma separated", p)
        self.assertNotIn("{", p.replace("{question}", ""))
        for name in NAMES:
            self.assertNotIn(name, p)

    def test_a_clean_answer_is_used_and_says_so(self):
        model = Recorder("premier league, epl, football, sky sports, bt sport")
        r = guide.filter_from_question("premier league football", KINDS, GROUPS,
                                       ask_model=model, names=NAMES)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(r["source"], "model")
        self.assertTrue(r["model_used"])
        self.assertTrue(r["ok"])
        self.assertIn("premier league", r["match"])
        names = [c["name"] for c in guide.apply_filter(CHANNELS, r)]
        self.assertIn("Sky Sports Main Event", names)
        self.assertNotIn("The Matrix", names)

    def test_the_prompts_own_label_is_not_mistaken_for_json(self):
        # The prompt ends in `Keywords:` and this 7B routinely echoes the label. Testing for
        # structural punctuation before stripping it rejected a perfect answer and fired the
        # fallback on every request with a reason that was false -- a verification step failing
        # on healthy input, `.claude/HANDOVER.md` §3.0d. Both halves are asserted: the good
        # answer parses, and the loop still does not.
        self.assertEqual(guide.parse_model_line("Keywords: sports, football"),
                         ["sports", "football"])
        self.assertEqual(guide.parse_model_line("keyword: sports"), ["sports"])
        with self.assertRaises(guide.ModelUnusable):
            guide.parse_model_line(LOOP)
        model = Recorder("Keywords: premier league, epl, football")
        r = guide.filter_from_question("premier league football", KINDS, GROUPS,
                                       ask_model=model, names=NAMES)
        self.assertEqual(r["source"], "model")
        self.assertEqual(r["match"], ["premier league", "epl", "football"])

    def test_the_documented_loop_is_rejected(self):
        # Both rules, checked separately, because either one alone lets it through.
        with self.assertRaises(guide.ModelUnusable) as ctx:
            guide.parse_model_line(LOOP)
        self.assertIn("JSON", str(ctx.exception))
        # Strip the structural punctuation and the repeats alone must still reject it.
        bare = LOOP.replace('{"match":[', "").replace('"', "")
        with self.assertRaises(guide.ModelUnusable) as ctx:
            guide.parse_model_line(bare)
        self.assertIn("repeated", str(ctx.exception))
        # And the naive parser really would have accepted it -- this is the assertion that
        # proves the test is not vacuous.
        naive = [t.strip() for t in LOOP.split(",") if t.strip()]
        self.assertGreater(len(naive), 1)

    def test_a_looping_model_falls_back_observably(self):
        model = Recorder(LOOP)
        r = guide.filter_from_question("premier league football", KINDS, GROUPS,
                                       ask_model=model, names=NAMES)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(r["source"], "fallback")
        self.assertFalse(r["model_used"])
        self.assertIn("JSON", r["why"])
        # It fell back to the visitor's own words rather than to an unfiltered list.
        self.assertEqual(r["match"], ["premier", "league", "football"])
        self.assertLess(len(guide.apply_filter(CHANNELS, r)), len(CHANNELS))

    def test_garbage_and_silence_both_fall_back_observably(self):
        for reply, expect in [("", "returned nothing"),
                              ("I think you should look at, ,, !", "no usable keywords"),
                              ("Sure! Here is a JSON object: {\"match\": [", "JSON")]:
            r = guide.filter_from_question("premier league football", KINDS, GROUPS,
                                           ask_model=Recorder(reply), names=NAMES)
            self.assertEqual(r["source"], "fallback", reply)
            self.assertFalse(r["model_used"], reply)
            self.assertIn(expect, r["why"], reply)

    def test_a_raising_model_is_named_not_swallowed(self):
        def boom(_prompt: str) -> str:
            raise TimeoutError("chat surface did not answer in 30s")

        r = guide.filter_from_question("premier league football", KINDS, GROUPS,
                                       ask_model=boom, names=NAMES)
        self.assertEqual(r["source"], "fallback")
        self.assertIn("TimeoutError", r["why"])
        self.assertTrue(r["ok"], "the visitor's own words are still a filter")

    def test_no_model_available_is_stated(self):
        r = guide.filter_from_question("premier league football", KINDS, GROUPS, names=NAMES)
        self.assertEqual(r["source"], "fallback")
        self.assertIn("no model was available", r["why"])


# ------------------------------------------------------------------ honesty

class NothingIsBlocked(unittest.TestCase):
    """"adult live tv seems to be being blocked" — reported by Garrett, 2026-08-17.

    Nothing in this module blocks anything: there is no denylist here, and `denied()` in
    `backend/server.py` guards `/api/image` only, on the one narrow intersection that is illegal
    to produce. What looked like blocking was three ordinary bugs stacked on each other, and
    each one has a test below.
    """

    ADULT = ["XXX", "18+", "FOR ADULTS", "UK| SPORTS"]

    def test_the_visitors_word_reaches_the_playlists_word(self):
        # Bug 1: the visitor types "adult"; every group is called XXX or 18+; nothing matched.
        model = Recorder("should never be reached")
        r = guide.filter_from_question("adult", ["live"], self.ADULT, ask_model=model)
        self.assertEqual(model.calls, [], "this must not need the card")
        self.assertEqual(r["source"], "local")
        self.assertEqual(set(r["groups"]), {"XXX", "18+", "FOR ADULTS"},
                         "every adult group, not just the first one that matched")
        self.assertNotIn("UK| SPORTS", r["groups"])
        self.assertIn("your playlist", r["why"])

    def test_adult_live_tv_the_exact_phrase(self):
        r = guide.filter_from_question("adult live tv", ["live"], self.ADULT)
        self.assertTrue(r["ok"])
        self.assertEqual(r["kind"], "live")
        self.assertEqual(set(r["groups"]), {"XXX", "18+", "FOR ADULTS"})

    def test_a_refusal_is_not_laundered_into_a_filter(self):
        # Bug 2, and the one that actually reads as "blocked": the chat model carries trained
        # refusals, and `"I'm sorry, but I can't help with that."` comma-split to `["i'm
        # sorry"]` -- a filter matching zero channels, labelled `source: model`. A visitor
        # cannot tell that apart from the category being censored.
        for reply in ["I'm sorry, but I can't help with that.",
                      "I cannot provide keywords for that request.",
                      "Unfortunately I am not able to assist with this."]:
            r = guide.filter_from_question("adult channels", ["live"], ["UK| SPORTS"],
                                           ask_model=Recorder(reply))
            self.assertEqual(r["source"], "fallback", reply)
            self.assertFalse(r["model_used"], reply)
            self.assertIn("refused", r["why"], reply)
            self.assertNotIn("sorry", r["match"], reply)

    def test_prose_is_not_a_keyword_list(self):
        r = guide.filter_from_question("premier league", KINDS, GROUPS,
                                       ask_model=Recorder("I will search for football now"))
        self.assertEqual(r["source"], "fallback")
        self.assertIn("prose", r["why"])

    def test_every_synonym_row_reaches_the_playlists_groups(self):
        """Each route into GROUP_SYNONYMS resolves to the visitor's own lineup, not just one.

        `filter_from_question` expands the visitor's word through `GROUP_SYNONYMS`
        (`__init__.py:147`) before matching group names, and those rows are independent data:
        `"adult" -> (xxx, 18, adults, porn, erotic)` is a different row from
        `"porn" -> (xxx, adult, 18)`, and `"xxx"` matches a group name directly with no
        expansion at all. `test_the_visitors_word_reaches_the_playlists_word` covers the first
        of those three paths; this covers all three, so a dropped or mistyped row shows up as
        a query that quietly returns nothing instead of the channels the visitor pays for.

        Rewritten 2026-08-20. This was `test_this_module_carries_no_denylist` and its second
        half grepped `guide.py` for the strings BLOCKLIST / DENYLIST / BANNED -- an
        absence-of-mechanism assertion, which forbids ever adding a content control rather
        than testing anything the module does. It had already been patched with
        `.replace("NO DENYLIST", "")` to stop it failing on this module's own documentation,
        which was the signal it was testing prose. The exact-set assertions below are strictly
        stronger than the `assertTrue(r["groups"])` it used to make.

        If a denylist is added here later this test fails, and that failure is the honest
        kind: it says a group in the visitor's own playlist stopped being reachable by name.
        That is a product decision to take deliberately, not a mechanism to forbid.

        **`"porn"` is asserted as reaching two of the three groups, not all three, because
        that is what it does today -- and that is a live defect, not a design.** `_SYNONYMS`
        is hand-maintained and asymmetric: the `adult`, `adults` and `xxx` rows all carry the
        token `adults`, which is what reaches the group literally named `FOR ADULTS`, and the
        `porn` row (`__init__.py:150`) carries `adult` singular instead. Matching is
        token-equality, not substring, so `adult` does not reach `FOR ADULTS` and a visitor
        who types "porn" silently gets a smaller lineup than one who types "adult" for the
        same intent -- the Bug-1 class this whole class exists to catch. Related, from the
        same probe: `erotic` appears as a value in the `adult` row but has no row of its own,
        so `filter_from_question("erotic", ...)` returns `ok: True` with **zero** groups -- a
        legitimate query dropped while reporting success.
        Both are recorded rather than fixed here on purpose: Garrett's 2026-08-20 instruction
        with R-98 held was "NO runtime behavior changes anywhere", and widening a synonym row
        changes what real queries return. Pinned as-is so the asymmetry cannot drift further
        unnoticed; awaiting his call on the table.
        """
        reaches = {"adult": {"XXX", "18+", "FOR ADULTS"},
                   "xxx": {"XXX", "18+", "FOR ADULTS"},
                   "porn": {"XXX", "18+"}}          # see the docstring: missing FOR ADULTS
        for q, expected in reaches.items():
            r = guide.filter_from_question(q, ["live"], self.ADULT)
            self.assertTrue(r["ok"], f"{q!r} produced no filter at all")
            self.assertEqual(set(r["groups"]), expected,
                             f"{q!r} no longer reaches exactly the groups it used to")
            self.assertNotIn("UK| SPORTS", r["groups"], f"{q!r} over-matched the lineup")

    def test_a_synonym_value_with_no_row_of_its_own_returns_ok_with_nothing(self):
        """`erotic` is a value in the `adult` row and not a key, so it matches nothing.

        Pinned as the defect it is, with the same reasoning as above: asserted rather than
        fixed because the fix is a runtime behaviour change and those are held. When the
        synonym table is repaired this test should start failing, and the repair should
        replace it with the positive assertion.
        """
        r = guide.filter_from_question("erotic", ["live"], self.ADULT)
        self.assertTrue(r["ok"])
        self.assertEqual(r["groups"], [],
                         "`erotic` now reaches groups -- the synonym table was repaired; "
                         "assert the groups it reaches and delete this test")


class Honesty(unittest.TestCase):

    def test_a_question_matching_nothing_says_so_and_does_not_match_everything(self):
        r = guide.filter_from_question("xyzzy plugh", KINDS, GROUPS, names=NAMES)
        self.assertEqual(r["source"], "fallback")
        self.assertFalse(r["model_used"])
        self.assertTrue(r["ok"])
        self.assertEqual(guide.apply_filter(CHANNELS, r), [],
                         "a filter nothing satisfies returns nothing, not everything")

    def test_a_question_with_no_signal_is_not_a_match_everything_filter(self):
        r = guide.filter_from_question("show me everything please", KINDS, GROUPS, names=NAMES)
        self.assertFalse(r["ok"])
        self.assertIn("not a match-everything result", r["why"])
        self.assertEqual(guide.apply_filter(CHANNELS, r), [])

    def test_an_underived_filter_matches_nothing(self):
        self.assertEqual(guide.apply_filter(CHANNELS, {"ok": False, "match": []}), [])
        self.assertEqual(guide.apply_filter(CHANNELS, {}), [])

    def test_every_result_declares_its_provenance(self):
        cases = [
            guide.filter_from_question("uk sports", KINDS, GROUPS, names=NAMES),
            guide.filter_from_question("premier league", KINDS, GROUPS,
                                       ask_model=Recorder("premier league, epl"), names=NAMES),
            guide.filter_from_question("premier league", KINDS, GROUPS,
                                       ask_model=Recorder(LOOP), names=NAMES),
            guide.filter_from_question("show me everything", KINDS, GROUPS, names=NAMES),
        ]
        for r in cases:
            self.assertIn(r["source"], ("local", "model", "fallback"), r)
            self.assertEqual(r["model_used"], r["source"] == "model", r)
            self.assertTrue(r["why"].strip(), r)
            self.assertEqual(set(r), {"match", "exclude", "kind", "groups", "why", "source",
                                      "model_used", "ok"})

    def test_nothing_returned_ever_carries_a_url(self):
        # The fixtures below are the only place a URL appears, and it must not come back out:
        # a playlist URL carries the visitor's credentials in its path.
        with_urls = [dict(c, url=f"http://panel.example/live/user/pass/{i}.ts")
                     for i, c in enumerate(CHANNELS)]
        r = guide.filter_from_question("uk sports", KINDS, [c["group"] for c in with_urls],
                                       ask_model=Recorder("sports"),
                                       names=[c["name"] for c in with_urls])
        blob = json.dumps(r)
        self.assertNotIn("http", blob)
        self.assertNotIn("pass", blob)
        cat = json.dumps(guide.catalogue(with_urls))
        self.assertNotIn("http", cat)

    def test_the_module_holds_nothing_between_calls(self):
        a = guide.filter_from_question("uk sports", KINDS, GROUPS, names=NAMES)
        guide.filter_from_question("movies", KINDS, GROUPS, names=NAMES)
        b = guide.filter_from_question("uk sports", KINDS, GROUPS, names=NAMES)
        self.assertEqual(a, b)
        # And a call with a completely different playlist leaves no trace of the first.
        other = guide.filter_from_question("uk sports", ["live"], ["DE| SPORT"], names=[])
        self.assertNotIn("UK| SPORTS", other["groups"])


# ------------------------------------------------------------------ the rack unit

class RackUnit(unittest.TestCase):

    def test_ready_because_it_can_actually_do_its_job(self):
        state, detail = guide.unit_state()
        self.assertEqual(state, "ready")
        self.assertTrue(detail.strip())

    def test_the_state_word_is_one_console_js_already_understands(self):
        # site/console.js:47 -- `u.state === 'offline' ? 'led' : 'led on'`. Any state that is
        # not exactly `offline` lights the green LED, so inventing a word here would light an
        # LED that means nothing. Guide's state must be one of the words already in use.
        self.assertIn(guide.unit_state()[0], {"ready", "busy", "loading", "offline"})

    def test_the_detail_says_what_it_does_not_depend_on(self):
        detail = guide.unit_state()[1].lower()
        self.assertIn("no weights", detail)
        self.assertIn("lock", detail)


class EveryAdultGroupNotJustTheFirst(unittest.TestCase):
    """A playlist routinely carries adult channels under two or three different titles.

    `_bridged_hits` used to skip a token that the direct pass had already covered, which
    meant "adult" matched `XXX ADULT` by exact token and never bridged to `18+ FOR ADULTS`
    beside it. The visitor got one of the two categories they have, which from the outside
    is indistinguishable from being filtered -- and there is no filter here at all.
    """

    PLAYLIST = [
        {"name": "BBC One HD", "group": "UK | ENTERTAINMENT", "kind": "live",
         "url": "http://x/live/1.ts"},
        {"name": "Private XXX 1", "group": "XXX ADULT", "kind": "live",
         "url": "http://x/10.mp4"},
        {"name": "Hot 18+ Channel", "group": "18+ FOR ADULTS", "kind": "live",
         "url": "http://x/11.mp4"},
    ]

    def _filter(self, question):
        cat = guide.catalogue(self.PLAYLIST)
        return guide.filter_from_question(
            question,
            kinds=list(cat["kinds"].keys()),
            groups=[c["group"] for c in self.PLAYLIST],
            names=[c["name"] for c in self.PLAYLIST],
            clusters=cat["groups"])

    def test_adult_finds_both_adult_groups(self):
        filt = self._filter("adult")
        self.assertEqual(len(filt["groups"]), 2, filt["groups"])
        self.assertEqual(len(guide.apply_filter(self.PLAYLIST, filt)), 2)

    def test_xxx_finds_both_too(self):
        filt = self._filter("xxx")
        self.assertEqual(len(guide.apply_filter(self.PLAYLIST, filt)), 2)

    def test_a_word_with_no_synonyms_is_unaffected(self):
        # The fix removed a skip. Confirm it did not widen an ordinary question: nothing
        # bridges "entertainment", so it still matches exactly its own group.
        filt = self._filter("entertainment")
        self.assertEqual(filt["groups"], ["UK | ENTERTAINMENT"])
        self.assertEqual(len(guide.apply_filter(self.PLAYLIST, filt)), 1)

    def test_nothing_is_invented_when_the_vocabulary_is_absent(self):
        # No adult group in this playlist at all: the bridge must find nothing rather
        # than conjure a category the provider does not carry.
        plain = [self.PLAYLIST[0]]
        cat = guide.catalogue(plain)
        filt = guide.filter_from_question(
            "adult", kinds=list(cat["kinds"].keys()),
            groups=[c["group"] for c in plain], names=[c["name"] for c in plain],
            clusters=cat["groups"])
        self.assertEqual(filt["groups"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
