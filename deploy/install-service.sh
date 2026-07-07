#!/usr/bin/env bash
# Install StarAgent as a systemd USER service that starts at boot.
#
# Usage: ./deploy/install-service.sh
#
# What it does:
#   1. Renders deploy/staragent.service with this repo's path
#   2. Installs it to ~/.config/systemd/user/
#   3. Enables it and turns on lingering (so it starts at boot, no login needed)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="$REPO_DIR/deploy/staragent.service"
UNIT_DIR="$HOME/.config/systemd/user"
DOCKER_BIN="$(command -v docker || true)"

if [ -z "$DOCKER_BIN" ]; then
    echo "ERROR: docker not found in PATH" >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: 'docker compose' (v2 plugin) not available" >&2
    exit 1
fi
if [ ! -f "$REPO_DIR/.env" ]; then
    echo "WARNING: $REPO_DIR/.env not found — the bot will not start without it" >&2
fi

mkdir -p "$UNIT_DIR"
sed -e "s|__REPO_DIR__|$REPO_DIR|g" -e "s|__DOCKER__|$DOCKER_BIN|g" \
    "$UNIT_SRC" > "$UNIT_DIR/staragent.service"
echo "Installed $UNIT_DIR/staragent.service (WorkingDirectory=$REPO_DIR)"

systemctl --user daemon-reload
systemctl --user enable staragent.service
echo "Service enabled."

# Lingering lets user services start at boot without an interactive login.
if loginctl enable-linger "$USER" 2>/dev/null; then
    echo "Lingering enabled for $USER (service starts at boot)."
else
    echo "NOTE: could not enable lingering — run: sudo loginctl enable-linger $USER" >&2
fi

read -r -p "Start the service now? [Y/n] " answer
case "${answer:-Y}" in
    [Yy]*) systemctl --user start staragent.service && systemctl --user --no-pager status staragent.service ;;
    *) echo "Start later with: systemctl --user start staragent" ;;
esac
