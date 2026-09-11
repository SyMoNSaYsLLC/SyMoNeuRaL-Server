"""Fuzzy artist accept/reject — the gate between symon's suggestions and
real Spotify URIs."""
from symoneural_dj.matching import artist_matches, normalize, pick_track

from conftest import track_item


def test_normalize_strips_accents_case_punct_and_feat():
    assert normalize("Beyoncé") == "beyonce"
    assert normalize("KAYTRANADA feat. Anderson .Paak") == "kaytranada"
    assert normalize("A$AP Rocky") == "a ap rocky"


def test_exact_and_accented_match():
    assert artist_matches("Beyonce", ["Beyoncé"])
    assert artist_matches("beyoncé", ["Beyonce"])


def test_containment_accepts_credited_ensembles():
    assert artist_matches("Nick Cave", ["Nick Cave & The Bad Seeds"])


def test_small_typo_accepted_different_artist_rejected():
    assert artist_matches("Radiohead", ["Radioheed"])
    assert not artist_matches("Radiohead", ["Coldplay"])


def test_reject_is_actually_a_reject():
    assert not artist_matches("Taylor Swift", ["Slayer"])
    assert not artist_matches("Anything", [])
    assert not artist_matches("", ["Anyone"])


def test_pick_track_takes_first_matching_result():
    items = [
        track_item("spotify:track:cover", "Karaoke Legends"),
        track_item("spotify:track:real", "Artist A"),
        track_item("spotify:track:later", "Artist A"),
    ]
    assert pick_track("Artist A", items)["uri"] == "spotify:track:real"


def test_pick_track_none_when_nothing_matches():
    items = [track_item("spotify:track:x", "Somebody Else")]
    assert pick_track("Artist A", items) is None
    assert pick_track("Artist A", []) is None
