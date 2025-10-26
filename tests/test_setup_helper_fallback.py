import shutil
import subprocess
from pathlib import Path


def _cleanup_helper_state(repo_root: Path) -> None:
    helper_root = repo_root / "SetupHelper"
    if helper_root.exists():
        shutil.rmtree(helper_root)


def test_perform_install_succeeds_with_helper_fallback(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    install_root = tmp_path / "install_root"
    log_file = tmp_path / "fallback_install.log"

    script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-sh}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT="{install_root}"
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_LOG_FILE="{log_file}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
unset SETUP_HELPER_ROOT
unset HELPER_RESOURCE
unset SETUP_HELPER_DETECTED_ROOT
source_helper_resources

register_package_dependencies() {{
  printf "register_package_dependencies\\n" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

require_python_module() {{
  printf "require_python_module:%s\\n" "$1" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

install_payload() {{
  printf "install_payload\\n" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

process_file_sets_for_action() {{
  printf "process_file_sets_for_action:%s\\n" "$1" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

install_service() {{
  printf "install_service\\n" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

register_dbus_settings() {{
  dbusSettingsUpdated=true
  printf "register_dbus_settings\\n" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

finalize_helper_session() {{
  printf "finalize_helper_session\\n" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

perform_install
'
"""

    result = subprocess.run(
        ["sh", "-c", script],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    try:
        assert "SetupHelper-Fallback aktiv" in result.stdout
        assert log_file.exists(), "Das Fallback-Protokoll wurde nicht erzeugt."
        log_lines = log_file.read_text(encoding="utf-8").splitlines()
        assert "register_package_dependencies" in log_lines
        assert any(line.startswith("require_python_module:") for line in log_lines)
        assert "install_payload" in log_lines
        assert any(line.startswith("process_file_sets_for_action") for line in log_lines)
        assert "install_service" in log_lines
        assert "register_dbus_settings" in log_lines
        assert "finalize_helper_session" in log_lines
    finally:
        _cleanup_helper_state(repo_root)

