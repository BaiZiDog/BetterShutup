#!/usr/bin/env python3
"""Build the BetterShutup installer with Inno Setup 6."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "better_shutup" / "__init__.py"
ISS = ROOT / "installer" / "BetterShutup.iss"
DIST = ROOT / "dist"
EXE = DIST / "BetterShutup.exe"
DIST_DOCS = ("LICENSE.txt", "NOTICE.txt")


def package_version() -> str:
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"',
        INIT.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise RuntimeError(f"could not read __version__ from {INIT}")
    return match.group(1)


def windows_file_version(version: str) -> str:
    parts = [part for part in version.split(".") if part]
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts[:4])


def find_iscc() -> Path:
    override = os.environ.get("INNO_SETUP_ISCC")
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
        raise FileNotFoundError(
            f"INNO_SETUP_ISCC points to a missing file: {path}"
        )

    for name in ("ISCC.exe", "iscc"):
        found = shutil.which(name)
        if found:
            return Path(found)

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if not base:
            continue
        path = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if path.is_file():
            return path

    try:
        import winreg

        key_path = (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
            r"\Inno Setup 6_is1"
        )
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                try:
                    with winreg.OpenKey(
                        hive,
                        key_path,
                        0,
                        winreg.KEY_READ | view,
                    ) as key:
                        location, _ = winreg.QueryValueEx(
                            key, "InstallLocation"
                        )
                except OSError:
                    continue
                path = Path(str(location)) / "ISCC.exe"
                if path.is_file():
                    return path
    except ImportError:
        pass

    raise FileNotFoundError(
        "Inno Setup 6 ISCC.exe not found. Set INNO_SETUP_ISCC or install "
        "Inno Setup 6."
    )


def installer_command(iscc: Path, version: str) -> list[str]:
    return [
        str(iscc),
        "/Qp",
        f"/DAppVersion={version}",
        f"/DAppFileVersion={windows_file_version(version)}",
        str(ISS),
    ]


def write_checksums(installer: Path, version: str) -> None:
    assets = [EXE, installer]
    for name in DIST_DOCS:
        assets.append(DIST / name)
    lines = []
    for path in assets:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest} *{path.name}")
    contents = "\n".join(lines) + "\n"
    (DIST / "SHA256SUMS.txt").write_text(contents, encoding="ascii")
    (DIST / f"SHA256SUMS-{version}.txt").write_text(
        contents, encoding="ascii"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the BetterShutup Windows installer with Inno Setup 6."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ISCC command without compiling.",
    )
    args = parser.parse_args(argv)

    version = package_version()
    missing = [
        path
        for path in (EXE, *(DIST / name for name in DIST_DOCS))
        if not path.is_file()
    ]
    if missing:
        print(
            "error: missing distribution files:\n"
            + "\n".join(f"  {path}" for path in missing)
            + "\nRun python tools/build_exe.py first.",
            file=sys.stderr,
        )
        return 1
    if not ISS.is_file():
        print(f"error: installer script not found: {ISS}", file=sys.stderr)
        return 1

    try:
        iscc = find_iscc()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    command = installer_command(iscc, version)
    print("Running:", subprocess.list2cmdline(command))
    if args.dry_run:
        return 0

    try:
        completed = subprocess.run(command, cwd=ROOT)
    except OSError as exc:
        print(f"error: could not start ISCC: {exc}", file=sys.stderr)
        return 1
    if completed.returncode != 0:
        print(
            f"\nInno Setup failed with exit code {completed.returncode}.",
            file=sys.stderr,
        )
        return completed.returncode

    installer = DIST / f"BetterShutup-{version}-setup.exe"
    if not installer.is_file():
        print(
            f"error: build finished but {installer} was not created.",
            file=sys.stderr,
        )
        return 1

    write_checksums(installer, version)
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    print(f"\nBuilt {installer}")
    print(f"Size: {installer.stat().st_size / (1024 * 1024):.1f} MiB")
    print(f"SHA256: {digest}")
    print("Updated SHA256SUMS.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
