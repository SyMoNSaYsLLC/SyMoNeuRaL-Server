"""The DJ is not a Spotify client, and these are the tests that keep it that way.

The owner's constraint, in their words: "make sure symoneural dj is not connected solely to
spotify i dont want legal stuff with them; i want to be able to add playlist to spotify but we
are our own playlist generator that can add connectors to youtube music and spotify."

That is a product requirement with a legal reason behind it, which makes it exactly the kind of
thing that erodes quietly during a refactor. So it is asserted rather than documented.
"""
from __future__ import annotations

import pytest

from symoneural_dj import connectors
from symoneural_dj.connectors.base import Connector
from symoneural_dj.symon_client import PlaylistGenerationError, parse_tracklist


def test_more_than_one_service_is_compiled_in():
    """One connector is a dependency. Two is a choice."""
    assert set(connectors.available()) >= {"spotify", "ytmusic"}


def test_no_connector_is_privileged():
    """Both are registered the same way and implement the same protocol, so neither is the
    default and removing either leaves a working registry."""
    for name in ("spotify", "ytmusic"):
        client = connectors.get(name)
        assert isinstance(client, Connector)
        assert client.name == name and client.label


def test_removing_every_connector_leaves_the_registry_usable(monkeypatch):
    """The test behind the requirement. With nothing registered the DJ must still import, still
    answer "what can I export to", and only fail at the point of actually exporting."""
    monkeypatch.setattr(connectors, "_REGISTRY", {})
    assert connectors.available() == []
    assert connectors.enabled() == []
    with pytest.raises(connectors.ConnectorError):
        connectors.get("spotify")


def test_generation_does_not_import_a_streaming_service():
    """The load-bearing one. `symon_client` is the generator, and if it reached for a connector
    then "our own playlist generator" would be untrue at the import line."""
    import symoneural_dj.symon_client as generator
    source = open(generator.__file__).read()
    for forbidden in ("spotify", "Spotify", "ytmusic", "youtube", "connectors"):
        assert forbidden not in source, f"the generator references {forbidden!r}"


def test_an_unconfigured_connector_is_not_offered():
    """`enabled()` is what the UI lists. A connector with no client id must not appear as an
    option that fails when clicked."""
    assert connectors.enabled() == [] or all(
        connectors.get(name).configured() for name in connectors.enabled())


# ---- the generator itself ---------------------------------------------------------------


def test_a_fenced_reply_is_accepted():
    rows = parse_tracklist('```json\n[{"artist":"A","track":"B"}]\n```')
    assert [(r.artist, r.track) for r in rows] == [("A", "B")]


def test_a_greeting_before_the_json_is_not_a_failure():
    """A model that says "Here is your playlist:" first should not fail the job over a
    pleasantry."""
    rows = parse_tracklist('Here is your playlist:\n[{"artist":"A","track":"B"}]')
    assert len(rows) == 1


def test_a_wrapped_object_is_unwrapped():
    rows = parse_tracklist('{"tracks":[{"artist":"A","track":"B"}]}')
    assert len(rows) == 1


def test_duplicates_differing_only_in_case_collapse():
    rows = parse_tracklist('[{"artist":"Nina Simone","track":"Sinnerman"},'
                           ' {"artist":"nina simone","track":"sinnerman"}]')
    assert len(rows) == 1


def test_unusable_rows_are_dropped_not_fatal():
    """Nineteen good tracks and one malformed row is nineteen tracks, not a failed job."""
    rows = parse_tracklist('[{"artist":"A","track":"B"}, {"nope":1}, "string", null]')
    assert len(rows) == 1


def test_nothing_usable_is_an_error():
    with pytest.raises(PlaylistGenerationError):
        parse_tracklist("[]")
    with pytest.raises(PlaylistGenerationError):
        parse_tracklist("not json at all")
    with pytest.raises(PlaylistGenerationError):
        parse_tracklist("")
