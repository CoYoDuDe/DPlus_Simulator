"""Tests für unregister_dbus_settings."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_unregister_dbus_settings_uses_remove_all(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    log_file = tmp_path / "helper_calls.log"
    dbus_list_file = repo_root / "DbusSettingsList"
    preexisting_content = dbus_list_file.read_bytes() if dbus_list_file.exists() else None
    file_exists_after: bool | None = None

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
source \"{setup_script}\"
removeDbusSettingsFromFile() {{
  printf 'from_file:%s\\n' \"$1\" >> \"{log_file}\"
  return 1
}}
removeDbusSettings() {{
  printf 'fallback:%s\\n' \"$*\" >> \"{log_file}\"
  return 1
}}
removeAllDbusSettings() {{
  if [[ -f \"{dbus_list_file}\" ]]; then
    printf 'remove_all:present\\n' >> \"{log_file}\"
  else
    printf 'remove_all:missing\\n' >> \"{log_file}\"
  fi
  return 0
}}
unregister_dbus_settings
"""
    try:
        subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)
        file_exists_after = dbus_list_file.exists()
        log_lines = log_file.read_text(encoding="utf-8").splitlines()

        assert "remove_all:present" in log_lines, "removeAllDbusSettings wurde nicht aufgerufen."
        assert not any(line.startswith("fallback:") for line in log_lines), (
            "removeDbusSettings sollte ohne Parameter nicht aufgerufen werden."
        )
        assert file_exists_after is False, "Die temporäre DbusSettingsList-Datei wurde nicht entfernt."
    finally:
        if preexisting_content is not None:
            dbus_list_file.write_bytes(preexisting_content)
        elif dbus_list_file.exists():
            dbus_list_file.unlink()
