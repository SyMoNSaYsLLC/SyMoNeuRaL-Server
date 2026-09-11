#!/usr/bin/env bash
# Install the rack search provider for whichever desktop is actually present.
#
# Everything goes under $HOME. Nothing here needs root, and nothing is written
# into /usr, so an uninstall is three rm commands and a re-login.
#
#   ./install.sh            # install for the detected desktop(s)
#   ./install.sh --remove   # take it all back out
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SEARCH_PY="$HERE/search.py"

DBUS_DIR="$HOME/.local/share/dbus-1/services"
KRUNNER_DIR="$HOME/.local/share/krunner/dbusplugins"
APPS_DIR="$HOME/.local/share/applications"
GNOME_DIR="$HOME/.local/share/gnome-shell/search-providers"

DBUS_FILE="$DBUS_DIR/com.symoneural.SearchProvider.service"
KRUNNER_FILE="$KRUNNER_DIR/symoneural-search.desktop"
APPS_FILE="$APPS_DIR/symoneural-search.desktop"
GNOME_FILE="$GNOME_DIR/com.symoneural.SearchProvider.ini"

if [[ "${1:-}" == "--remove" ]]; then
  rm -fv "$DBUS_FILE" "$KRUNNER_FILE" "$APPS_FILE" "$GNOME_FILE"
  echo "Removed. Log out and back in, or restart plasmashell, to clear it."
  exit 0
fi

[[ -x "$SEARCH_PY" ]] || { echo "install.sh: $SEARCH_PY is not executable" >&2; exit 1; }

# The service must start before either desktop can ask it anything.
mkdir -p "$DBUS_DIR"
sed "s|@SEARCH_PY@|$SEARCH_PY|" "$HERE/com.symoneural.SearchProvider.service" \
  > "$DBUS_FILE"
echo "installed $DBUS_FILE"

installed_any=0

# KRunner. Checked for rather than assumed: installing a Plasma runner on a box
# with no Plasma leaves a file that never runs and never errors.
if command -v krunner >/dev/null 2>&1; then
  mkdir -p "$KRUNNER_DIR" "$APPS_DIR"
  cp -v "$HERE/symoneural-search.desktop" "$KRUNNER_FILE"
  cp -v "$HERE/symoneural-search.desktop" "$APPS_FILE"
  installed_any=1
fi

# GNOME Shell. Same check, same reason.
if command -v gnome-shell >/dev/null 2>&1; then
  mkdir -p "$GNOME_DIR" "$APPS_DIR"
  cp -v "$HERE/com.symoneural.SearchProvider.ini" "$GNOME_FILE"
  cp -v "$HERE/symoneural-search.desktop" "$APPS_FILE"
  installed_any=1
fi

if [[ "$installed_any" == 0 ]]; then
  echo "install.sh: neither krunner nor gnome-shell found." >&2
  echo "  The D-Bus service is installed and \`search.py --once <query>\` works," >&2
  echo "  but no desktop will call it. This is a report, not a failure." >&2
  exit 0
fi

cat <<'DONE'

Installed. To pick it up now rather than at next login:
  KDE:   kquitapp6 krunner    (it restarts on next Alt+Space)
  GNOME: log out and back in  (Wayland cannot restart the shell in place)

Then press Alt+Space and type a surface name: chat, studio, miner, gpu.
DONE
