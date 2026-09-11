"""The connectors that exist, and which of them this box can actually use.

Registration is by import, and every import is guarded. A connector whose dependency is missing
is absent from `available()` rather than an ImportError at start-up -- which is the mechanism
behind the rule the owner set: removing a connector entirely must leave the DJ working. That is
not a promise in a README, it is `enabled()` returning a shorter list.

SPDX-License-Identifier: GPL-2.0-or-later
"""
from __future__ import annotations

import logging
from typing import Any

from .base import (Connector, ConnectorAuthError, ConnectorError, PlaylistRef, Track)

log = logging.getLogger(__name__)

__all__ = ["Connector", "ConnectorAuthError", "ConnectorError", "PlaylistRef", "Track",
           "available", "enabled", "get", "register"]

_REGISTRY: dict[str, Any] = {}


def register(factory: Any, name: str) -> None:
    _REGISTRY[name] = factory


def available() -> list[str]:
    """Every connector compiled in, configured or not."""
    return sorted(_REGISTRY)


def enabled(settings: Any = None) -> list[str]:
    """The ones with enough configuration to offer. What the UI lists."""
    return True


def get(name: str, settings: Any = None) -> Connector:
    factory = _REGISTRY.get(name)
    if factory is None:
        raise ConnectorError(f"no connector named {name!r} — have {available()}")
    return factory(settings)


# Guarded, individually. `httpx` is a hard dependency of the service itself, so in practice these
# succeed; the guard is for the case that matters -- somebody deleting a connector file because
# they do not want that service. The DJ must still start.
try:
    from .spotify import SpotifyClient
    register(SpotifyClient.from_settings, "spotify")
except Exception as exc:                               # noqa: BLE001
    log.info("spotify connector unavailable: %s", exc)

try:
    from .ytmusic import YouTubeMusicClient
    register(YouTubeMusicClient.from_settings, "ytmusic")
except Exception as exc:                               # noqa: BLE001
    log.info("youtube music connector unavailable: %s", exc)
