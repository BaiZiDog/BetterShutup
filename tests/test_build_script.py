from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from better_shutup import __version__

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_exe.py"


def load_build_module():
    spec = importlib.util.spec_from_file_location("better_shutup_build_exe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_command_has_required_nuitka_flags() -> None:
    module = load_build_module()
    command = module.build_command(assume_downloads=True)
    assert command[:4] == [sys.executable, "-m", "nuitka", "--assume-yes-for-downloads"]
    assert "--onefile" in command
    assert "--zig" in command
    assert "--enable-plugin=tk-inter" in command
    assert "--windows-console-mode=disable" in command
    assert "--include-package-data=better_shutup" in command
    assert any(
        arg.startswith("--windows-icon-from-ico=") for arg in command
    )
    assert module.VERSION == __version__
    assert f"--file-version={module.FILE_VERSION}" in command
    assert f"--product-version={module.FILE_VERSION}" in command
    assert module.ICON.is_file()
    assert str(module.ENTRY) in command
    assert command[-1].endswith("BetterShutup.pyw")


def test_build_entry_lives_inside_package() -> None:
    module = load_build_module()
    assert module.ENTRY.parent == ROOT / "better_shutup"
    assert module.ENTRY.is_file()
