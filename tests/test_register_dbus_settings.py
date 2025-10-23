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
    install_root = tmp_path / "install_root"
    log_file = tmp_path / "helper_calls.log"

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT=\"{install_root}\"
source "{setup_script}"
addAllDbusSettings() {{
  printf 'addAll|%s|%s\n' "$#" "$*" >> "{log_file}"
  if [[ -f "{repo_root}/DbusSettingsList" ]]; then
    printf 'unexpected-copy' >> /dev/null
  fi
  return 0
}}
endScript() {{
  printf 'endScript|%s\n' "$*" >> "{log_file}"
  return 0
}}
register_dbus_settings
"""

    subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)
    _cleanup_helper_state(repo_root)

    if log_file.exists():
        log_lines = log_file.read_text(encoding="utf-8").splitlines()
    else:
        log_lines = []
    assert not any(line.startswith("addAll|") for line in log_lines), (
        "addAllDbusSettings darf vor finalize_helper_session nicht ausgelöst werden."
    )
    assert not any(line.startswith("endScript|") for line in log_lines), (
        "endScript darf ohne finalize_helper_session nicht aufgerufen werden."
    )

    dbus_list_file = repo_root / "DbusSettingsList"
    assert dbus_list_file.exists(), "DbusSettingsList muss bis finalize_helper_session bestehen bleiben."

    payload = _load_line_delimited_json(dbus_list_file)
    assert payload, "Es wurde keine JSON-Payload erzeugt."

    first_entry = payload[0]
    assert isinstance(first_entry, dict)
    assert "path" in first_entry and "default" in first_entry
    assert any(
        entry.get("path") == "/Settings/Devices/DPlusSim/GpioPin" for entry in payload
    ), "Erwarteter Settings-Pfad fehlt in der Payload."

    persistent_file = install_root / "DbusSettingsList"
    assert persistent_file.exists(), "Persistente DbusSettingsList wurde nicht erzeugt."
    assert persistent_file.read_bytes() == dbus_list_file.read_bytes(), (
        "Persistente und temporäre DbusSettingsList unterscheiden sich."
    )

    dbus_list_file.unlink()
    if persistent_file.exists():
        persistent_file.unlink()
    if install_root.exists():
        shutil.rmtree(install_root)


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
unset __DPLUS_HELPER_FALLBACK_DEFINED

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
  local payload_path="${{1:-}}"
  if [[ -n "${{payload_path}}" && -f "${{payload_path}}" ]]; then
    cp "${{payload_path}}" "{payload_file}"
  elif [[ -f "{repo_root}/DbusSettingsList" ]]; then
    cp "{repo_root}/DbusSettingsList" "{payload_file}"
  fi
  return 0
}}

endScript() {{
  printf 'endScript-begin:%s\\n' \"$*\" >> \"{log_file}\"
  if [[ "$*" == *"ADD_DBUS_SETTINGS"* ]]; then
    if [[ -f "{repo_root}/DbusSettingsList" ]]; then
      addAllDbusSettings "{repo_root}/DbusSettingsList"
    else
      addAllDbusSettings
    fi
  fi
  printf 'endScript-end:%s\\n' \"$*\" >> \"{log_file}\"
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

    persistent_file = install_root / "DbusSettingsList"
    assert persistent_file.exists(), "Persistente DbusSettingsList fehlt nach Installation."

    log_lines = log_file.read_text(encoding="utf-8").splitlines()
    add_calls = [line for line in log_lines if line.startswith("addAll|")]
    assert add_calls, "addAllDbusSettings wurde nicht aufgerufen."

    argc = int(add_calls[0].split("|")[1])
    assert argc in {0, 1}, "addAllDbusSettings wurde mit unerwarteter Argumentanzahl aufgerufen."

    assert any(line.startswith("endScript-begin:INSTALL_FILES INSTALL_SERVICES ADD_DBUS_SETTINGS") for line in log_lines), (
        "endScript wurde nicht mit den erwarteten Flags aufgerufen."
    )
    assert any(line.startswith("endScript-end:INSTALL_FILES INSTALL_SERVICES ADD_DBUS_SETTINGS") for line in log_lines), (
        "endScript wurde nicht korrekt abgeschlossen."
    )

    begin_index = log_lines.index(
        next(line for line in log_lines if line.startswith("endScript-begin:"))
    )
    add_index = log_lines.index(add_calls[0])
    end_index = log_lines.index(
        next(line for line in log_lines if line.startswith("endScript-end:"))
    )
    assert begin_index < add_index < end_index, (
        "addAllDbusSettings muss innerhalb von endScript aufgerufen werden."
    )

    shutil.rmtree(install_root)
