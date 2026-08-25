#!/usr/bin/env bash
# Install user-level systemd timer with your install path substituted.
set -euo pipefail

ROOT="${1:-}"
if [[ -z "$ROOT" ]]; then
  echo "Usage: $0 /absolute/path/to/ornith-loop" >&2
  exit 1
fi
ROOT="$(cd "$ROOT" && pwd)"

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

sed "s|__ORNITH_LOOP_ROOT__|$ROOT|g" \
  "$ROOT/systemd/ornith-loop.service" > "$UNIT_DIR/ornith-loop.service"
cp "$ROOT/systemd/ornith-loop.timer" "$UNIT_DIR/ornith-loop.timer"

systemctl --user daemon-reload
echo "Installed units in $UNIT_DIR"
echo "Enable with: systemctl --user enable --now ornith-loop.timer"
echo "Disable with: systemctl --user disable --now ornith-loop.timer"
