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
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-bash}}"
export BASH_VERSION="${{BASH_VERSION:-5}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT="{install_root}"
export DPLUS_SIMULATOR_FILESETS_TARGET_ROOT="{target_root}"
PYTHONPATH="{module_root}:${{PYTHONPATH:-}}"
export PYTHONPATH
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_HELPER_ROOT="{helper_root}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
SETUP_HELPER_DETECTED_ROOT="$DPLUS_TEST_HELPER_ROOT"
source_helper_resources
SETUP_HELPER_DETECTED_ROOT="$DPLUS_TEST_HELPER_ROOT"
scriptAction=INSTALL
perform_install
'
"""

    subprocess.run(["sh", "-c", script], check=True, cwd=repo_root)

    version_independent_dir = repo_root / "FileSets" / "VersionIndependent"

    qml_src = version_independent_dir / "PageSettingsDPlusSimulator.qml"
    qml_dest = (
        target_root
        / "opt"
        / "victronenergy"
        / "gui"
        / "qml"
        / "PageSettingsDPlusSimulator.qml"
    )
    assert qml_dest.is_file(), "VersionIndependent-QML-Datei wurde nicht kopiert."
    assert qml_dest.read_text(encoding="utf-8") == qml_src.read_text(encoding="utf-8")

    utils_src = version_independent_dir / "PageSettingsDPlusSimulatorUtils.js"
    utils_dest = (
        target_root
        / "opt"
        / "victronenergy"
        / "gui"
        / "qml"
        / "PageSettingsDPlusSimulatorUtils.js"
    )
    assert utils_dest.is_file(), "Helper-Datei wurde nicht kopiert."
    assert utils_dest.read_text(encoding="utf-8") == utils_src.read_text(encoding="utf-8")

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


def test_install_without_preinstalled_dbus_next(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    setup_script = repo_root / "setup"
    install_root = tmp_path / "install"
    target_root = tmp_path / "target"
    helper_root = tmp_path / "helper"
    module_root = tmp_path / "pysite"

    helper_root.mkdir()
    (helper_root / "version").write_text("8.20\n", encoding="utf-8")

    assert not (module_root / "dbus_next").exists(), "dbus_next darf vor der Installation nicht existieren."

    script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-bash}}"
export BASH_VERSION="${{BASH_VERSION:-5}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT="{install_root}"
export DPLUS_SIMULATOR_FILESETS_TARGET_ROOT="{target_root}"
unset PYTHONPATH
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_HELPER_ROOT="{helper_root}"
export DPLUS_TEST_MODULE_ROOT="{module_root}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
SETUP_HELPER_DETECTED_ROOT="$DPLUS_TEST_HELPER_ROOT"
source_helper_resources
SETUP_HELPER_DETECTED_ROOT="$DPLUS_TEST_HELPER_ROOT"
scriptAction=INSTALL

checkPackageDependencies() {{
  mkdir -p "$DPLUS_TEST_MODULE_ROOT/dbus_next"
  printf "# stub\n" > "$DPLUS_TEST_MODULE_ROOT/dbus_next/__init__.py"
  PYTHONPATH="$DPLUS_TEST_MODULE_ROOT"
  export PYTHONPATH
  return 0
}}

perform_install
'
"""

    subprocess.run(["sh", "-c", script], check=True, cwd=repo_root)

    assert (module_root / "dbus_next" / "__init__.py").is_file(), "dbus_next wurde nicht installiert."

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
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-bash}}"
export BASH_VERSION="${{BASH_VERSION:-5}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT="{install_root}"
export DPLUS_SIMULATOR_FILESETS_TARGET_ROOT="{target_root}"
PYTHONPATH="{module_root}:${{PYTHONPATH:-}}"
export PYTHONPATH
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_HELPER_ROOT="{helper_root}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
SETUP_HELPER_DETECTED_ROOT="$DPLUS_TEST_HELPER_ROOT"
source_helper_resources
SETUP_HELPER_DETECTED_ROOT="$DPLUS_TEST_HELPER_ROOT"
scriptAction=INSTALL
perform_install
'
"""

    subprocess.run(["sh", "-c", install_script], check=True, cwd=repo_root)

    uninstall_script = f"""
set -eu
SETUP_SHELL="${{DPLUS_TEST_SETUP_SHELL:-bash}}"
export BASH_VERSION="${{BASH_VERSION:-5}}"
export DPLUS_SIMULATOR_SKIP_MAIN=1
export INSTALL_ROOT="{install_root}"
export DPLUS_SIMULATOR_FILESETS_TARGET_ROOT="{target_root}"
PYTHONPATH="{module_root}:${{PYTHONPATH:-}}"
export PYTHONPATH
export DPLUS_TEST_SETUP_SCRIPT="{setup_script}"
export DPLUS_TEST_HELPER_ROOT="{helper_root}"
"$SETUP_SHELL" -c 'set -eu
. "$DPLUS_TEST_SETUP_SCRIPT"
SETUP_HELPER_DETECTED_ROOT="$DPLUS_TEST_HELPER_ROOT"
source_helper_resources
SETUP_HELPER_DETECTED_ROOT="$DPLUS_TEST_HELPER_ROOT"
scriptAction=UNINSTALL
perform_uninstall
'
"""

    subprocess.run(["sh", "-c", uninstall_script], check=True, cwd=repo_root)

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

    qml_dest = (
        target_root
        / "opt"
        / "victronenergy"
        / "gui"
        / "qml"
        / "PageSettingsDPlusSimulator.qml"
    )
    assert not qml_dest.exists(), "VersionIndependent-QML-Datei wurde beim Uninstall nicht entfernt."

    utils_dest = (
        target_root
        / "opt"
        / "victronenergy"
        / "gui"
        / "qml"
        / "PageSettingsDPlusSimulatorUtils.js"
    )
    assert not utils_dest.exists(), "Helper-Datei wurde beim Uninstall nicht entfernt."

    state_dir = repo_root / "SetupHelper" / ".helper_state" / "filesets"
    action_file = state_dir / "last_action"
    assert action_file.read_text(encoding="utf-8").strip() == "UNINSTALL"

    _cleanup_helper_state(repo_root)
