"""Tests für die JSON-Erzeugung in register_dbus_settings."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_register_dbus_settings_generates_json(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    payload_file = tmp_path / "dbus_payload.json"
    log_file = tmp_path / "helper_calls.log"

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
source "{setup_script}"
addAllDbusSettingsFromFile() {{
  printf 'from_file:%s\n' "$1" >> "{log_file}"
  return 1
}}
addAllDbusSettings() {{
  if [[ $# -eq 0 ]]; then
    return 1
  fi
  printf '%s' "$1" > "{payload_file}"
  return 0
}}
register_dbus_settings
"""

    subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)

    payload_text = payload_file.read_text(encoding="utf-8").strip()
    assert payload_text, "Es wurde keine JSON-Payload erzeugt."

    payload = json.loads(payload_text)
    assert isinstance(payload, list)
    assert payload, "Die JSON-Payload darf nicht leer sein."

    first_entry = payload[0]
    assert isinstance(first_entry, dict)
    assert "path" in first_entry and "default" in first_entry
    assert any(
        entry.get("path") == "/Settings/Devices/DPlusSim/GpioPin" for entry in payload
    ), "Erwarteter Settings-Pfad fehlt in der Payload."
