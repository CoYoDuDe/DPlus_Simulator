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
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
source "{setup_script}"
PACKAGE_DEPENDENCIES_FILE="{dependencies_file}"

checkPackageDependencies() {{
  printf 'check:%s\\n' "$1" >> "{log_file}"
  return 0
}}

register_package_dependencies
"""

    subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)
    _cleanup_helper_state(repo_root)

    log_lines = log_file.read_text(encoding="utf-8").splitlines()
    assert f"check:{dependencies_file}" in log_lines


def test_register_package_dependencies_skips_without_helper(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    dependencies_file = tmp_path / "packageDependencies"

    dependencies_file.write_text("conflict\n", encoding="utf-8")

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
source "{setup_script}"
PACKAGE_DEPENDENCIES_FILE="{dependencies_file}"

register_package_dependencies
"""

    completed = subprocess.run(
        ["bash", "-c", script],
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
