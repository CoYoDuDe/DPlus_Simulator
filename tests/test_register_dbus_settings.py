"""Tests für die JSON-Erzeugung in register_dbus_settings."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def _cleanup_helper_state(repo_root: Path) -> None:
    helper_state_root = repo_root / "SetupHelper"
    helper_state_dir = helper_state_root / ".helper_state"
    if helper_state_dir.exists():
        shutil.rmtree(helper_state_dir)
        try:
            helper_state_root.rmdir()
        except OSError:
            pass



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
    _cleanup_helper_state(repo_root)

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


def test_perform_install_reports_end_script_flags(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    install_root = tmp_path / "install_root"
    payload_file = tmp_path / "end_payload.json"
    log_file = tmp_path / "end_script.log"

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT=\"{install_root}\"
source \"{setup_script}\"
source_helper_resources

perform_install_preflight() {{
  return 0
}}

install_payload() {{
  printf 'install_payload\\n' >> \"{log_file}\"
  return 0
}}

install_service() {{
  printf 'install_service\\n' >> \"{log_file}\"
  return 0
}}

addAllDbusSettingsFromFile() {{
  return 1
}}

addAllDbusSettings() {{
  if [[ $# -eq 0 ]]; then
    return 1
  fi

  local payload
  if [[ $# -gt 1 ]]; then
    local first=true
    payload='['
    for arg in "$@"; do
      if [[ "${{first}}" == true ]]; then
        payload+="${{arg}}"
        first=false
      else
        payload+="${{IFS:0:0}},${{arg}}"
      fi
    done
    payload+=']'
  else
    payload="$1"
  fi

  printf 'addAll:%s\n' "${{payload}}" >> "{log_file}"
  printf '%s' "${{payload}}" > "{payload_file}"
  return 0
}}

endScript() {{
  printf 'endScript:%s\\n' \"$*\" >> \"{log_file}\"
  return 0
}}

perform_install
"""

    subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)
    _cleanup_helper_state(repo_root)

    payload_text = payload_file.read_text(encoding="utf-8").strip()
    assert payload_text, "Es wurde keine JSON-Payload erzeugt."

    payload_lines = [line for line in payload_text.splitlines() if line]
    assert payload_lines, "Es wurde keine Payload ausgegeben."

    payload = [json.loads(line) for line in payload_lines]
    assert payload, "Die JSON-Payload darf nicht leer sein."

    log_lines = log_file.read_text(encoding="utf-8").splitlines()
    assert f"endScript:INSTALL_FILES INSTALL_SERVICE ADD_DBUS_SETTINGS" in log_lines, (
        "endScript wurde nicht mit den erwarteten Flags aufgerufen."
    )
