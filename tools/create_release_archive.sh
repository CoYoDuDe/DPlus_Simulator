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

# Sicherstellen, dass alle relevanten Skripte ausführbar sind
if [[ -f "$ROOT_DIR/setup" ]]; then
  chmod +x "$ROOT_DIR/setup"
fi

if [[ -d "$ROOT_DIR/services" ]]; then
  find "$ROOT_DIR/services" -type f -name run -exec chmod +x {} +
fi

cd "$ROOT_DIR"

if [[ -z "${GIT_DIR:-}" ]]; then
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "Dieses Skript muss innerhalb eines Git-Repositorys ausgeführt werden." >&2
    exit 1
  fi
fi

STATUS="$(git status --porcelain --untracked-files=normal)"
if [[ -n "$STATUS" ]]; then
  echo "Arbeitsverzeichnis enthält unversionierte oder nicht eingecheckte Änderungen:" >&2
  echo "$STATUS" >&2
  echo "Bitte committen, stashen oder bereinigen Sie die Änderungen, bevor Sie das Release-Archiv erstellen." >&2
  exit 1
fi

mkdir -p "$ARCHIVE_DIR"

tar --owner=0 --group=0 --numeric-owner \
    --exclude='.git' \
    --exclude='*.tgz' \
    -czf "$ARCHIVE_PATH" .

echo "SetupHelper-Archiv erstellt: $ARCHIVE_PATH"
