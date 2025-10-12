#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_ARCHIVE_NAME="DPlus_Simulator-$(date +%Y%m%d).tgz"
TARGET_INPUT="${1:-$DEFAULT_ARCHIVE_NAME}"

resolve_path() {
  local path="$1"
  if [[ "$path" = /* ]]; then
    printf '%s' "$path"
  else
    printf '%s/%s' "$ROOT_DIR" "$path"
  fi
}

ARCHIVE_PATH="$(resolve_path "$TARGET_INPUT")"
ARCHIVE_DIR="$(dirname "$ARCHIVE_PATH")"
mkdir -p "$ARCHIVE_DIR"

# Sicherstellen, dass alle relevanten Skripte ausführbar sind
if [[ -f "$ROOT_DIR/setup" ]]; then
  chmod +x "$ROOT_DIR/setup"
fi

if [[ -d "$ROOT_DIR/services" ]]; then
  find "$ROOT_DIR/services" -type f -name run -exec chmod +x {} +
fi

cd "$ROOT_DIR"

tar --owner=0 --group=0 --numeric-owner \
    --exclude='.git' \
    --exclude='*.tgz' \
    -czf "$ARCHIVE_PATH" .

echo "SetupHelper-Archiv erstellt: $ARCHIVE_PATH"
