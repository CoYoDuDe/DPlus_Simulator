"""Tests für register_package_dependencies."""

from __future__ import annotations

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


def test_register_package_dependencies_uses_check(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    dependencies_file = tmp_path / "packageDependencies"
    log_file = tmp_path / "helper_calls.log"

    dependencies_file.write_text("conflict\n", encoding="utf-8")

    script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-sh}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export DPLUS_TEST_DEPENDENCIES_FILE="{dependencies_file}"
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_LOG_FILE="{log_file}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
PACKAGE_DEPENDENCIES_FILE="$DPLUS_TEST_DEPENDENCIES_FILE"
scriptAction=INSTALL

checkPackageDependencies() {{
  printf "check:%s\n" "$1" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

register_package_dependencies
'
"""

    subprocess.run(["sh", "-c", script], check=True, cwd=repo_root)
    _cleanup_helper_state(repo_root)

    log_lines = log_file.read_text(encoding="utf-8").splitlines()
    assert f"check:{dependencies_file}" in log_lines


def test_register_package_dependencies_skips_without_helper(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    dependencies_file = tmp_path / "packageDependencies"

    dependencies_file.write_text("conflict\n", encoding="utf-8")

    script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-sh}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export DPLUS_TEST_DEPENDENCIES_FILE="{dependencies_file}"
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
PACKAGE_DEPENDENCIES_FILE="$DPLUS_TEST_DEPENDENCIES_FILE"
scriptAction=INSTALL

register_package_dependencies
'
"""

    completed = subprocess.run(
        ["sh", "-c", script],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    _cleanup_helper_state(repo_root)

    stdout_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert any(
        "überspringe packageDependencies-Prüfung" in line
        for line in stdout_lines
    ), "Es wurde keine informative Meldung zum Überspringen der Prüfung ausgegeben."


def test_register_package_dependencies_skips_for_uninstall(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    dependencies_file = tmp_path / "packageDependencies"
    log_file = tmp_path / "helper_calls.log"

    dependencies_file.write_text("conflict\n", encoding="utf-8")

    script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-sh}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export DPLUS_TEST_DEPENDENCIES_FILE="{dependencies_file}"
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_LOG_FILE="{log_file}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
PACKAGE_DEPENDENCIES_FILE="$DPLUS_TEST_DEPENDENCIES_FILE"
scriptAction=UNINSTALL

checkPackageDependencies() {{
  printf "check:%s\n" "$1" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

register_package_dependencies
'
"""

    subprocess.run(["sh", "-c", script], check=True, cwd=repo_root)
    _cleanup_helper_state(repo_root)

    assert not log_file.exists(), "checkPackageDependencies darf bei UNINSTALL nicht aufgerufen werden."


def test_register_package_dependencies_skips_for_status(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    dependencies_file = tmp_path / "packageDependencies"
    log_file = tmp_path / "helper_calls.log"

    dependencies_file.write_text("conflict\n", encoding="utf-8")

    script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-sh}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export DPLUS_TEST_DEPENDENCIES_FILE="{dependencies_file}"
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_LOG_FILE="{log_file}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
PACKAGE_DEPENDENCIES_FILE="$DPLUS_TEST_DEPENDENCIES_FILE"
scriptAction=CHECK

checkPackageDependencies() {{
  printf "check:%s\n" "$1" >> "$DPLUS_TEST_LOG_FILE"
  return 0
}}

register_package_dependencies
'
"""

    subprocess.run(["sh", "-c", script], check=True, cwd=repo_root)
    _cleanup_helper_state(repo_root)

    assert not log_file.exists(), "checkPackageDependencies darf bei CHECK nicht aufgerufen werden."


def test_register_package_dependencies_fails_on_conflict(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    dependencies_file = tmp_path / "packageDependencies"
    log_file = tmp_path / "helper_calls.log"

    dependencies_file.write_text("conflict\n", encoding="utf-8")

    script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-sh}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export DPLUS_TEST_DEPENDENCIES_FILE="{dependencies_file}"
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_LOG_FILE="{log_file}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
PACKAGE_DEPENDENCIES_FILE="$DPLUS_TEST_DEPENDENCIES_FILE"
scriptAction=INSTALL

checkPackageDependencies() {{
  printf "check:%s\n" "$1" >> "$DPLUS_TEST_LOG_FILE"
  return 3
}}

register_package_dependencies
'
"""

    completed = subprocess.run(
        ["sh", "-c", script],
        check=False,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    _cleanup_helper_state(repo_root)

    assert completed.returncode != 0, "Das Setup-Skript hätte bei Konflikten abbrechen müssen."
    stdout = completed.stdout.strip().splitlines()
    assert any("checkPackageDependencies meldete Fehler" in line for line in stdout)
    log_lines = log_file.read_text(encoding="utf-8").splitlines()
    assert f"check:{dependencies_file}" in log_lines


def test_register_package_dependencies_aborts_on_helper_abort(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    dependencies_file = tmp_path / "packageDependencies"

    dependencies_file.write_text("conflict\n", encoding="utf-8")

    script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-sh}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export DPLUS_TEST_DEPENDENCIES_FILE="{dependencies_file}"
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
PACKAGE_DEPENDENCIES_FILE="$DPLUS_TEST_DEPENDENCIES_FILE"
scriptAction=INSTALL

checkPackageDependencies() {{
  scriptAction=UNINSTALL
  installFailed=true
  installFailMessage="Konflikt erkannt"
  return 0
}}

register_package_dependencies
'
"""

    completed = subprocess.run(
        ["sh", "-c", script],
        check=False,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    _cleanup_helper_state(repo_root)

    assert completed.returncode != 0, "Das Setup-Skript muss bei Konfliktmeldungen des Helpers abbrechen."
    stdout_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert any("Konflikt erkannt" in line for line in stdout_lines), "Die Konfliktmeldung des Helpers wurde nicht ausgegeben."
    assert any("scriptAction=UNINSTALL" in line for line in stdout_lines), "Die geänderte Helper-Aktion wurde nicht protokolliert."
