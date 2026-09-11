"""The KRunner half: org.kde.krunner1, which is what this box actually runs.

Plasma 6.3.6 is the session here, so this is the interface that answers when
Garrett hits Alt+Space and types a surface name. The GNOME interface in
`gnomeshell.py` exports the same results for a GNOME session; neither knows
about the other, and both read `rack.py`.

KRunner calls `Match` on every keystroke. Nothing here blocks: the roster and
the port table are small files and are re-read per query on purpose, so adding a
surface shows up without restarting the service.
"""

from __future__ import annotations

from gi.repository import GLib

import rack

IFACE = "org.kde.krunner1"
ICON = "symoneural"

# Plasma::QueryMatch::Type. ExactMatch puts a surface whose id is exactly what
# was typed at the top of the list, above anything a plugin merely guessed at.
EXACT_MATCH = 100
POSSIBLE_MATCH = 30

XML = f"""
<node>
  <interface name="{IFACE}">
    <method name="Actions">
      <arg name="matches" type="a(sss)" direction="out"/>
    </method>
    <method name="Match">
      <arg name="query" type="s" direction="in"/>
      <arg name="matches" type="a(sssida{{sv}})" direction="out"/>
    </method>
    <method name="Run">
      <arg name="matchId" type="s" direction="in"/>
      <arg name="actionId" type="s" direction="in"/>
    </method>
    <method name="Teardown"/>
  </interface>
</node>
"""


class Runner:
    """Answers KRunner. `open_url` is injected so the tests need no browser."""

    def __init__(self, open_url, on_call=lambda: None):
        self._open = open_url
        self._on_call = on_call

    # -- org.kde.krunner1 ----------------------------------------------------

    def Actions(self):
        """No per-result actions. Returning none is legal and keeps rows clean."""
        self._on_call()
        return GLib.Variant("(a(sss))", ([],))

    def Match(self, query: str):
        self._on_call()
        matches = []
        for surface in rack.search(query):
            exact = surface.id == query.strip().lower()
            matches.append((
                surface.id,                                   # id, echoed to Run
                surface.label,                                # what the row reads
                ICON,
                EXACT_MATCH if exact else POSSIBLE_MATCH,
                1.0 if exact else 0.7,                        # relevance
                {
                    # Shown under the label: which bus the surface costs, so a
                    # GPU surface is recognisable as one before it is opened.
                    "subtext": GLib.Variant("s", f"{surface.bus} · {surface.href}"),
                },
            ))
        return GLib.Variant("(a(sssida{sv}))", (matches,))

    def Run(self, match_id: str, _action_id: str):
        self._on_call()
        # Resolve through the roster again rather than trusting the id back:
        # the row could have been edited between Match and Run, and an id that
        # no longer exists must open nothing at all.
        for surface in rack.surfaces():
            if surface.id == match_id:
                self._open(surface.url)
                return
    def Teardown(self):
        """KRunner is done with us. Nothing to release; the idle timer exits."""
        self._on_call()
