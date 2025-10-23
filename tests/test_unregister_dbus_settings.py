"""Tests für unregister_dbus_settings."""

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


def test_unregister_dbus_settings_uses_remove_all(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    log_file = tmp_path / "helper_calls.log"
    payload_file = tmp_path / "dbus_payload.json"
    dbus_list_file = repo_root / "DbusSettingsList"
    preexisting_content = dbus_list_file.read_bytes() if dbus_list_file.exists() else None
    file_exists_after: bool | None = None

    if dbus_list_file.exists():
        dbus_list_file.unlink()

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
source \"{setup_script}\"
removeDbusSettings() {{
  printf 'remove|%s|%s\\n' "$#" "$*" >> \"{log_file}\"
  return 1
}}
removeAllDbusSettings() {{
  local argc="$#"
  local args="$*"
  local state="missing"
  if [[ -f \"{dbus_list_file}\" ]]; then
    state="present"
    cp \"{dbus_list_file}\" \"{payload_file}\"
  fi
  printf 'remove_all|%s|%s|%s\\n' "${{argc}}" "${{args}}" "${{state}}" >> \"{log_file}\"
  return 0
}}
unregister_dbus_settings
"""
    try:
        subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)
        file_exists_after = dbus_list_file.exists()
        log_lines = log_file.read_text(encoding="utf-8").splitlines()

        remove_all_calls = [line for line in log_lines if line.startswith("remove_all|")]
        assert remove_all_calls, "removeAllDbusSettings wurde nicht aufgerufen."

        first_call = remove_all_calls[0].split("|")
        assert first_call[3] == "present", "DbusSettingsList war während removeAllDbusSettings nicht vorhanden."
        argc = int(first_call[1])
        assert argc in {0, 1}, "removeAllDbusSettings wurde mit unerwarteter Argumentanzahl aufgerufen."

        assert not any(line.startswith("remove|") for line in log_lines), (
            "removeDbusSettings sollte in diesem Pfad nicht benötigt werden."
        )

        assert file_exists_after is False, "Die temporäre DbusSettingsList-Datei wurde nicht entfernt."

        payload = _load_line_delimited_json(payload_file)
        assert payload, "Es wurde keine JSON-Payload für removeAllDbusSettings erzeugt."
    finally:
        _cleanup_helper_state(repo_root)
        if preexisting_content is not None:
            dbus_list_file.write_bytes(preexisting_content)
        elif dbus_list_file.exists():
            dbus_list_file.unlink()


def test_perform_uninstall_reports_end_script_flags(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    install_root = tmp_path / "install_root"
    install_root.mkdir()
    (install_root / "marker").touch()
    log_file = tmp_path / "end_script.log"
    payload_file = tmp_path / "uninstall_payload.json"

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT=\"{install_root}\"
source \"{setup_script}\"
source_helper_resources

remove_service() {{
  printf 'remove_service\\n' >> \"{log_file}\"
  return 0
}}

removeDbusSettings() {{
  printf 'remove|%s|%s\\n' "$#" "$*" >> \"{log_file}\"
  return 1
}}

removeAllDbusSettings() {{
  local argc="$#"
  local args="$*"
  local state="missing"
  if [[ -f \"{repo_root}/DbusSettingsList\" ]]; then
    state="present"
    cp \"{repo_root}/DbusSettingsList\" \"{payload_file}\"
  fi
  printf 'remove_all|%s|%s|%s\\n' "${{argc}}" "${{args}}" "${{state}}" >> \"{log_file}\"
  return 0
}}

endScript() {{
  printf 'endScript:%s\\n' \"$*\" >> \"{log_file}\"
  return 0
}}

perform_uninstall
"""

    subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)
    _cleanup_helper_state(repo_root)

    assert not install_root.exists(), "Installationsverzeichnis wurde nicht entfernt."

    log_lines = log_file.read_text(encoding="utf-8").splitlines()
    remove_all_calls = [line for line in log_lines if line.startswith("remove_all|")]
    assert remove_all_calls, "removeAllDbusSettings wurde nicht verwendet."

    first_call = remove_all_calls[0].split("|")
    assert first_call[3] == "present", "DbusSettingsList war während removeAllDbusSettings nicht vorhanden."
    argc = int(first_call[1])
    assert argc in {0, 1}, "removeAllDbusSettings wurde mit unerwarteter Argumentanzahl aufgerufen."

    assert not any(line.startswith("remove|") for line in log_lines), (
        "removeDbusSettings sollte während der Deinstallation nicht benötigt werden."
    )

    dbus_list_file = repo_root / "DbusSettingsList"
    assert not dbus_list_file.exists(), "Die temporäre DbusSettingsList-Datei wurde nicht entfernt."

    payload = _load_line_delimited_json(payload_file)
    assert payload, "Es wurde keine JSON-Payload für removeAllDbusSettings erzeugt."

    assert f"endScript:INSTALL_FILES INSTALL_SERVICES ADD_DBUS_SETTINGS" in log_lines, (
        "endScript wurde nicht mit den erwarteten Flags aufgerufen."
    )
