"""The GNOME half: org.gnome.Shell.SearchProvider2.

This box runs KDE, so nothing here answers today. It is written anyway because
the interface is twenty lines over the same `rack.py` the KRunner half uses, and
because a search provider that only exists for one desktop is the kind of thing
that gets discovered missing at the worst moment. `install.sh` refuses to install
the GNOME half unless GNOME Shell is actually present, so an absent gnome-shell
costs nothing but this file.
"""

from __future__ import annotations

from gi.repository import GLib

import rack

IFACE = "org.gnome.Shell.SearchProvider2"
ICON = "symoneural"

XML = f"""
<node>
  <interface name="{IFACE}">
    <method name="GetInitialResultSet">
      <arg name="terms" type="as" direction="in"/>
      <arg name="results" type="as" direction="out"/>
    </method>
    <method name="GetSubsearchResultSet">
      <arg name="previous_results" type="as" direction="in"/>
      <arg name="terms" type="as" direction="in"/>
      <arg name="results" type="as" direction="out"/>
    </method>
    <method name="GetResultMetas">
      <arg name="identifiers" type="as" direction="in"/>
      <arg name="metas" type="aa{{sv}}" direction="out"/>
    </method>
    <method name="ActivateResult">
      <arg name="identifier" type="s" direction="in"/>
      <arg name="terms" type="as" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="LaunchSearch">
      <arg name="terms" type="as" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
  </interface>
</node>
"""


class Provider:
    """Answers GNOME Shell. `open_url` is injected, as in the KRunner half."""

    def __init__(self, open_url, on_call=lambda: None):
        self._open = open_url
        self._on_call = on_call

    def GetInitialResultSet(self, terms):
        self._on_call()
        return GLib.Variant("(as)", ([s.id for s in rack.search(" ".join(terms))],))

    def GetSubsearchResultSet(self, _previous, terms):
        return self.GetInitialResultSet(terms)

    def GetResultMetas(self, identifiers):
        self._on_call()
        # GNOME Shell requires exactly one meta per requested id, in order, so
        # an id that no longer resolves still gets a row rather than a gap.
        known = {s.id: s for s in rack.surfaces()}
        metas = []
        for ident in identifiers:
            surface = known.get(ident)
            metas.append({
                "id": GLib.Variant("s", ident),
                "name": GLib.Variant("s", surface.label if surface else ident),
                "description": GLib.Variant(
                    "s", f"{surface.bus} · {surface.href}" if surface else ""),
                "gicon": GLib.Variant("s", ICON),
            })
        return GLib.Variant("(aa{sv})", (metas,))

    def ActivateResult(self, identifier, _terms, _timestamp):
        self._on_call()
        for surface in rack.surfaces():
            if surface.id == identifier:
                self._open(surface.url)
                return

    def LaunchSearch(self, terms, _timestamp):
        """Overview "show all". Opens the rack, which is the list of everything."""
        self._on_call()
        by_service = rack.ports()
        self._open(f"http://127.0.0.1:{by_service[rack.MONOLITH]}/")
