"""Fuzzy artist matching for Spotify search results.

stdlib only — difflib is plenty at 5 candidates per track. URIs are only ever
read out of Spotify's own responses; nothing here constructs one.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Below this ratio two normalized artist names are different artists. 0.8
# passes accent/punctuation drift ("Beyoncé" vs "Beyonce") and fails covers
# credited to someone else entirely.
ARTIST_RATIO = 0.8

_FEAT_TAIL = re.compile(r"\b(feat|ft|featuring)\b.*$")
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = _FEAT_TAIL.sub("", s)
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def artist_matches(expected: str, candidates: list[str]) -> bool:
    want = normalize(expected)
    if not want:
        return False
    for candidate in candidates:
        got = normalize(candidate)
        if not got:
            continue
        # Containment covers "Artist" credited as "Artist & Friends".
        if want in got or got in want:
            return True
        if SequenceMatcher(None, want, got).ratio() >= ARTIST_RATIO:
            return True
    return False


def pick_track(expected_artist: str, items: list[dict]) -> dict | None:
    """First search result (Spotify's relevance order) whose credited artists
    fuzzy-match the artist the model asked for. None means drop the track."""
    for item in items:
        names = [a.get("name", "") for a in item.get("artists", []) if isinstance(a, dict)]
        if artist_matches(expected_artist, names):
            return item
    return None
