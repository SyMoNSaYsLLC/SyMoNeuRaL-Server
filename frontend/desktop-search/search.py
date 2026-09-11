#!/usr/bin/env python3
"""Desktop search for the SyMoNeuRaL rack: type a surface name, open the surface.

One process, one bus name, two interfaces. KRunner (`org.kde.krunner1`) is the
one that answers on this box -- the session is Plasma 6.3.6. GNOME Shell
(`org.gnome.Shell.SearchProvider2`) is exported from the same object path so a
GNOME session gets identical results with no second service to keep in step.

Both read `rack.py`, which reads `backend/registry/ROSTER.md` and
`ops/PORTS.tsv`. There is no third copy of the surface list.

It is D-Bus activated: the desktop asks for the bus name, systemd or dbus starts
this, and it exits after two idle minutes. Nothing runs at boot for a feature
nobody has searched with yet.

    search.py                 # run in the foreground, for debugging
    search.py --once chat     # print what a query would return, and exit
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402  (must follow require_version)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gnomeshell  # noqa: E402
import krunner  # noqa: E402
import rack  # noqa: E402

BUS_NAME = "com.symoneural.SearchProvider"
OBJECT_PATH = "/com/symoneural/SearchProvider"
IDLE_EXIT_SECONDS = 120


def open_url(url: str) -> None:
    """Hand a rack URL to the desktop.

    xdg-open rather than a named browser: which browser is the user's choice,
    and hardcoding one is how a launcher ends up opening the wrong thing. The
    URL is always loopback and always built from the roster, never from input.
    """
    opener = shutil.which("xdg-open")
    if opener is None:
        print("symoneural-search: xdg-open is not installed; cannot open", url,
              file=sys.stderr)
        return
    subprocess.Popen([opener, url], start_new_session=True)


class Service:
    """Owns the bus name, exports both interfaces, exits when idle."""

    def __init__(self) -> None:
        self._loop = GLib.MainLoop()
        self._idle_source = 0
        self._runner = krunner.Runner(open_url, self._touch)
        self._provider = gnomeshell.Provider(open_url, self._touch)
        self._registered: list[int] = []

    def _touch(self) -> None:
        """Reset the idle timer. Every exported method calls this."""
        if self._idle_source:
            GLib.source_remove(self._idle_source)
        self._idle_source = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, IDLE_EXIT_SECONDS, self._quit)

    def _quit(self) -> bool:
        self._loop.quit()
        return GLib.SOURCE_REMOVE

    def _dispatch(self, handler):
        """Turn a D-Bus call into a method call on `handler`.

        A method that raises returns a D-Bus error rather than killing the main
        loop: one malformed roster row must not take the whole service down for
        every later query.
        """
        def invoked(_conn, _sender, _path, _iface, method, params, invocation):
            try:
                result = getattr(handler, method)(*params)
            except Exception as exc:                      # noqa: BLE001
                invocation.return_dbus_error(
                    "com.symoneural.SearchProvider.Error", f"{method}: {exc}")
                return
            invocation.return_value(result)
        return invoked

    def _export(self, conn, module, handler) -> None:
        node = Gio.DBusNodeInfo.new_for_xml(module.XML)
        self._registered.append(conn.register_object(
            OBJECT_PATH, node.interfaces[0], self._dispatch(handler), None, None))

    def _acquired(self, conn, _name) -> None:
        self._export(conn, krunner, self._runner)
        self._export(conn, gnomeshell, self._provider)

    def run(self) -> int:
        Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME,
                         Gio.BusNameOwnerFlags.NONE,
                         self._acquired, None, lambda *_: self._quit())
        self._touch()
        self._loop.run()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", metavar="QUERY",
                        help="print what this query would return, then exit")
    args = parser.parse_args(argv)

    if args.once is not None:
        hits = rack.search(args.once)
        if not hits:
            print(f"no surface matches {args.once!r}")
            return 1
        for surface in hits:
            print(f"{surface.id:12} {surface.bus:4} {surface.url}")
        return 0

    return Service().run()


if __name__ == "__main__":
    sys.exit(main())
