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


def _load_line_delimited_json(path: Path) -> list[dict]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_register_dbus_settings_generates_json(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    payload_file = tmp_path / "dbus_payload.json"
    log_file = tmp_path / "helper_calls.log"

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
source "{setup_script}"
addAllDbusSettings() {{
  printf 'addAll|%s|%s\n' "$#" "$*" >> "{log_file}"
  if [[ -f "{repo_root}/DbusSettingsList" ]]; then
    cp "{repo_root}/DbusSettingsList" "{payload_file}"
  fi
  return 0
}}
register_dbus_settings
"""

    subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)
    _cleanup_helper_state(repo_root)

    log_lines = log_file.read_text(encoding="utf-8").splitlines()
    add_calls = [line for line in log_lines if line.startswith("addAll|")]
    assert add_calls, "addAllDbusSettings wurde nicht aufgerufen."

    argc = int(add_calls[0].split("|")[1])
    assert argc in {0, 1}, "addAllDbusSettings wurde mit unerwarteter Argumentanzahl aufgerufen."

    dbus_list_file = repo_root / "DbusSettingsList"
    assert not dbus_list_file.exists(), "Die temporäre DbusSettingsList-Datei wurde nicht entfernt."

    payload = _load_line_delimited_json(payload_file)
    assert payload, "Es wurde keine JSON-Payload erzeugt."

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

addAllDbusSettings() {{
  printf 'addAll|%s|%s\n' "$#" "$*" >> "{log_file}"
  if [[ -f "{repo_root}/DbusSettingsList" ]]; then
    cp "{repo_root}/DbusSettingsList" "{payload_file}"
  fi
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

    payload = _load_line_delimited_json(payload_file)
    assert payload, "Es wurde keine JSON-Payload erzeugt."

    dbus_list_file = repo_root / "DbusSettingsList"
    assert not dbus_list_file.exists(), "Die temporäre DbusSettingsList-Datei wurde nicht entfernt."

    log_lines = log_file.read_text(encoding="utf-8").splitlines()
    add_calls = [line for line in log_lines if line.startswith("addAll|")]
    assert add_calls, "addAllDbusSettings wurde nicht aufgerufen."

    argc = int(add_calls[0].split("|")[1])
    assert argc in {0, 1}, "addAllDbusSettings wurde mit unerwarteter Argumentanzahl aufgerufen."

    assert f"endScript:INSTALL_FILES INSTALL_SERVICES ADD_DBUS_SETTINGS" in log_lines, (
        "endScript wurde nicht mit den erwarteten Flags aufgerufen."
    )
