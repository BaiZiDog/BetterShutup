from __future__ import annotations

import importlib.util
from pathlib import Path

from better_shutup import __version__

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_installer.py"
ISS = ROOT / "installer" / "BetterShutup.iss"


def load_installer_module():
    spec = importlib.util.spec_from_file_location(
        "better_shutup_build_installer", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_version_matches_package() -> None:
    module = load_installer_module()
    assert module.package_version() == __version__
    assert module.windows_file_version(__version__) == f"{__version__}.0"


def test_installer_command_passes_version_and_script() -> None:
    module = load_installer_module()
    command = module.installer_command(Path("ISCC.exe"), __version__)
    assert command[0] == "ISCC.exe"
    assert f"/DAppVersion={__version__}" in command
    assert f"/DAppFileVersion={__version__}.0" in command
    assert str(ISS) in command


def test_installer_script_has_expected_metadata() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    assert 'AppName={#AppName}' in text
    assert 'AppVersion={#AppVersion}' in text
    assert "DefaultDirName={localappdata}\\Programs\\BetterShutup" in text
    assert "OutputBaseFilename=BetterShutup-{#AppVersion}-setup" in text
    assert "Source: \"..\\dist\\BetterShutup.exe\"" in text
