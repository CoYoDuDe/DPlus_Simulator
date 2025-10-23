"""Tests für die FileSets-Verteilung über das Setup-Skript."""

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


def test_update_file_sets_install(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    install_root = tmp_path / "install"
    target_root = tmp_path / "target"
    helper_root = tmp_path / "helper"
    module_root = tmp_path / "py"
    helper_root.mkdir()
    module_root.mkdir()
    (helper_root / "version").write_text("8.20\n", encoding="utf-8")
    (module_root / "dbus_next").mkdir()
    (module_root / "dbus_next" / "__init__.py").write_text("# stub\n", encoding="utf-8")

    script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT="{install_root}"
export DPLUS_SIMULATOR_FILESETS_TARGET_ROOT="{target_root}"
PYTHONPATH="{module_root}:{{PYTHONPATH:-}}"
export PYTHONPATH
source "{setup_script}"
SETUP_HELPER_DETECTED_ROOT="{helper_root}"
source_helper_resources
SETUP_HELPER_DETECTED_ROOT="{helper_root}"
scriptAction=INSTALL
perform_install
"""

    subprocess.run(["bash", "-c", script], check=True, cwd=repo_root)

    version_independent_src = (
        repo_root
        / "FileSets"
        / "VersionIndependent"
        / "PageSettingsDPlusSimulator.qml"
    )
    version_independent_dest = (
        target_root
        / "opt"
        / "victronenergy"
        / "gui"
        / "qml"
        / "PageSettingsDPlusSimulator.qml"
    )
    assert version_independent_dest.is_file(), "VersionIndependent-Datei wurde nicht kopiert."
    assert (
        version_independent_dest.read_text(encoding="utf-8")
        == version_independent_src.read_text(encoding="utf-8")
    )

    patched_src = repo_root / "FileSets" / "PatchSource" / "PageSettings.qml"
    patched_dest = (
        target_root
        / "opt"
        / "victronenergy"
        / "gui"
        / "qml"
        / "PageSettings.qml"
    )
    assert patched_dest.is_file(), "Patch-Datei wurde nicht bereitgestellt."
    assert (
        patched_dest.read_text(encoding="utf-8")
        == patched_src.read_text(encoding="utf-8")
    )

    state_dir = repo_root / "SetupHelper" / ".helper_state" / "filesets"
    action_file = state_dir / "last_action"
    assert action_file.read_text(encoding="utf-8").strip() == "INSTALL"

    _cleanup_helper_state(repo_root)


def test_update_file_sets_uninstall(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    install_root = tmp_path / "install"
    target_root = tmp_path / "target"
    helper_root = tmp_path / "helper"
    module_root = tmp_path / "py"
    helper_root.mkdir()
    module_root.mkdir()
    (helper_root / "version").write_text("8.20\n", encoding="utf-8")
    (module_root / "dbus_next").mkdir()
    (module_root / "dbus_next" / "__init__.py").write_text("# stub\n", encoding="utf-8")

    install_script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT="{install_root}"
export DPLUS_SIMULATOR_FILESETS_TARGET_ROOT="{target_root}"
PYTHONPATH="{module_root}:{{PYTHONPATH:-}}"
export PYTHONPATH
source "{setup_script}"
SETUP_HELPER_DETECTED_ROOT="{helper_root}"
source_helper_resources
SETUP_HELPER_DETECTED_ROOT="{helper_root}"
scriptAction=INSTALL
perform_install
"""

    subprocess.run(["bash", "-c", install_script], check=True, cwd=repo_root)

    uninstall_script = f"""
set -euo pipefail
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT="{install_root}"
export DPLUS_SIMULATOR_FILESETS_TARGET_ROOT="{target_root}"
PYTHONPATH="{module_root}:{{PYTHONPATH:-}}"
export PYTHONPATH
source "{setup_script}"
SETUP_HELPER_DETECTED_ROOT="{helper_root}"
source_helper_resources
SETUP_HELPER_DETECTED_ROOT="{helper_root}"
scriptAction=UNINSTALL
perform_uninstall
"""

    subprocess.run(["bash", "-c", uninstall_script], check=True, cwd=repo_root)

    restored_dest = (
        target_root
        / "opt"
        / "victronenergy"
        / "gui"
        / "qml"
        / "PageSettings.qml"
    )
    restored_src = repo_root / "FileSets" / "PatchSource" / "PageSettings.qml.orig"
    assert restored_dest.is_file(), "Originaldatei fehlt nach der Deinstallation."
    assert (
        restored_dest.read_text(encoding="utf-8")
        == restored_src.read_text(encoding="utf-8")
    )

    version_independent_dest = (
        target_root
        / "opt"
        / "victronenergy"
        / "gui"
        / "qml"
        / "PageSettingsDPlusSimulator.qml"
    )
    assert (
        not version_independent_dest.exists()
    ), "VersionIndependent-Datei wurde beim Uninstall nicht entfernt."

    state_dir = repo_root / "SetupHelper" / ".helper_state" / "filesets"
    action_file = state_dir / "last_action"
    assert action_file.read_text(encoding="utf-8").strip() == "UNINSTALL"

    _cleanup_helper_state(repo_root)
