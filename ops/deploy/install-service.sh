#!/usr/bin/env bash
# Install the systemd units in this directory.
#
# The units are TEMPLATES: they carry `@@ROOT@@` where an absolute path has to go, because
# systemd has no notion of a relative path and the repo can be cloned anywhere. This script is
# the substitution step. `ops/units/symoneural-api.service` has referenced this file in a comment
# since it was written and it had never existed, which is the kind of gap that only shows up
# when somebody tries to follow the instruction.
#
# Two classes of unit live here and they install differently:
#
#   SYSTEM units (symoneural-api, symoneural-gateway) go in /etc/systemd/system and need
#   root. This script does NOT write there. It prints the exact commands instead, so the
#   operator runs them deliberately and can read what they do first.
#
#   USER units (symoneural-progress) go in ~/.config/systemd/user and need nothing. Those are
#   installed for real, because there is no privilege to escalate and nothing shared to break.
#
# Usage:
#   ops/deploy/install-service.sh                 # install user units, print the system ones
#   ops/deploy/install-service.sh --list          # say what would happen, change nothing
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPS="$ROOT/ops"
USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

# Which units are user units. Everything else here is a system unit.
USER_UNITS=(symoneural-progress.service symoneural-progress.timer)

# Timers are enabled; the .service they drive is not (the timer starts it). A service with no
# timer is enabled directly.
ENABLE=(symoneural-progress.timer)

LIST_ONLY=0
[[ "${1:-}" == "--list" ]] && LIST_ONLY=1

is_user_unit() {
    local want="$1" u
    for u in "${USER_UNITS[@]}"; do [[ "$u" == "$want" ]] && return 0; done
    return 1
}

should_enable() {
    local want="$1" u
    for u in "${ENABLE[@]}"; do [[ "$u" == "$want" ]] && return 0; done
    return 1
}

# Render one template to stdout. Fails loudly on a leftover placeholder rather than installing
# a unit that systemd will accept and then not run -- an unsubstituted @@ROOT@@ is a path that
# does not exist, and the failure surfaces later as an empty page rather than an install error.
render() {
    local src="$1"
    sed "s|@@ROOT@@|$ROOT|g" "$src" | {
        local out; out="$(cat)"
        if grep -q '@@[A-Z_]*@@' <<<"$out"; then
            echo "ops/deploy/install-service.sh: unsubstituted placeholder in $(basename "$src"):" >&2
            grep -o '@@[A-Z_]*@@' <<<"$out" | sort -u >&2
            return 1
        fi
        printf '%s\n' "$out"
    }
}

system_units=()
installed=()

for src in "$OPS"/*.service "$OPS"/*.timer; do
    [[ -e "$src" ]] || continue
    unit="$(basename "$src")"

    if ! is_user_unit "$unit"; then
        system_units+=("$unit")
        continue
    fi

    if (( LIST_ONLY )); then
        echo "would install user unit: $unit -> $USER_DIR/$unit"
        continue
    fi

    mkdir -p "$USER_DIR"
    render "$src" > "$USER_DIR/$unit"
    installed+=("$unit")
    echo "installed user unit: $USER_DIR/$unit"
done

if (( ! LIST_ONLY )) && (( ${#installed[@]} )); then
    systemctl --user daemon-reload
    for unit in "${ENABLE[@]}"; do
        # --now so it is both enabled for next boot and running right this second. Enabling
        # without starting is how a timer gets installed and then does nothing until reboot,
        # which reads exactly like the timer being broken.
        systemctl --user enable --now "$unit"
        echo "enabled + started: $unit"
    done
    echo
    echo "next tick:"
    systemctl --user list-timers --all 'symoneural-*' --no-pager || true
fi

if (( ${#system_units[@]} )); then
    echo
    echo "System units are NOT installed by this script -- they need root. To install them,"
    echo "read them first, then run:"
    echo
    for unit in "${system_units[@]}"; do
        echo "  sed 's|@@ROOT@@|$ROOT|g' $OPS/$unit | sudo tee /etc/systemd/system/$unit >/dev/null"
    done
    echo "  sudo systemctl daemon-reload"
    for unit in "${system_units[@]}"; do
        [[ "$unit" == *.timer ]] && echo "  sudo systemctl enable --now $unit"
    done
    echo "  sudo systemctl enable --now symoneural-api.service"
fi
