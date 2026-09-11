"""Compatibility shim.

`pipeline.py` and `app.py` were written when Spotify was the only export and import
`SpotifyClient` and `SpotifyAuthError` from here. Both now live in `connectors.spotify` alongside
YouTube Music, because the owner's requirement is that the DJ is not solely connected to Spotify
and a module named for one service at the top of the import list is the opposite of that.

Two lines rather than editing recovered, working code: the pipeline already takes its client as a
parameter, so it was written for a connector all along -- only the import path moved.

SPDX-License-Identifier: GPL-2.0-or-later
"""
from .connectors.spotify import (OwnershipStore, SpotifyAuthError,  # noqa: F401
                                 SpotifyClient, TokenStore)

__all__ = ["OwnershipStore", "SpotifyAuthError", "SpotifyClient", "TokenStore"]
