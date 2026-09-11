# `backend/studio/plugins/exp/plugins/` — the mounted experience plugins

One module each. The plugin runtime loads them by name from the preset; nothing here is
imported by a router.

## The contract

`backend/studio/plugins/__init__.py` states it: `REQUIRED` names every plugin must export,
`RECOGNISED` the optional ones, and `OPTIONAL_PRESENT` records **which plugin has which**,
pinned rather than computed.

Pinned on purpose: if a plugin gains an export, that map goes red and whoever added it
updates it in the same commit — which is the moment to ask whether the export has become
universal enough to move into `REQUIRED`. Computing it would make that question invisible.

`tests/component/studio/test_plugin_contract.py` is the enforcement.

## Adding one

A module here, plus its row in `OPTIONAL_PRESENT`, plus a preset that mounts it. The runtime
is created on first request and `boot()` mounts the preset there — not at import, so a broken
plugin cannot stop the API starting.
