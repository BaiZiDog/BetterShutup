#!/usr/bin/env python3
"""Build the single-file Windows executable with Nuitka."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "better_shutup" / "BetterShutup.pyw"
OUTPUT_DIR = ROOT / "dist"
OUTPUT_NAME = "BetterShutup.exe"
ICON = ROOT / "better_shutup" / "assets" / "BetterShutup.ico"
DIST_DOCS = ("LICENSE", "NOTICE")


def build_command(*, assume_downloads: bool) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        "--zig",
        "--enable-plugin=tk-inter",
        "--windows-console-mode=disable",
        f"--output-dir={OUTPUT_DIR}",
        f"--output-filename={OUTPUT_NAME}",
        "--remove-output",
        "--include-package=better_shutup",
        "--include-package-data=better_shutup",
        f"--windows-icon-from-ico={ICON}",
        "--company-name=BaiZiDog",
        "--product-name=BetterShutup",
        "--file-version=0.3.0.0",
        "--product-version=0.3.0.0",
        "--file-description=BetterShutup agent shutdown coordinator",
        "--copyright=Copyright 2026 BaiZiDog",
        str(ENTRY),
    ]
    if assume_downloads:
        command.insert(3, "--assume-yes-for-downloads")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a single-file BetterShutup.exe using Nuitka."
    )
    parser.add_argument(
        "--no-downloads",
        action="store_true",
        help="Do not let Nuitka download a missing Zig toolchain.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Nuitka command without running it.",
    )
    args = parser.parse_args(argv)

    if not ENTRY.is_file():
        print(f"error: entry file not found: {ENTRY}", file=sys.stderr)
        return 1
    if not ICON.is_file():
        print(f"error: icon file not found: {ICON}", file=sys.stderr)
        return 1

    command = build_command(assume_downloads=not args.no_downloads)
    print("Running:", subprocess.list2cmdline(command))
    if args.dry_run:
        return 0
    print()

    try:
        import nuitka  # noqa: F401
    except ImportError:
        print(
            "error: Nuitka is not installed.\n"
            "Install build dependencies with:\n"
            '  python -m pip install -e ".[build]"',
            file=sys.stderr,
        )
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(command, cwd=ROOT)
    except OSError as exc:
        print(f"error: could not start Nuitka: {exc}", file=sys.stderr)
        return 1

    if completed.returncode != 0:
        print(
            f"\nNuitka failed with exit code {completed.returncode}.",
            file=sys.stderr,
        )
        return completed.returncode

    output = OUTPUT_DIR / OUTPUT_NAME
    if not output.is_file():
        print(f"error: build finished but {output} was not created.", file=sys.stderr)
        return 1
    try:
        write_distribution_docs(output)
    except OSError as exc:
        print(f"error: failed to copy license files: {exc}", file=sys.stderr)
        return 1
    print(f"\nBuilt {output}")
    print(f"Size: {output.stat().st_size / (1024 * 1024):.1f} MiB")
    print(f"Distribution files: {OUTPUT_DIR}")
    return 0


def write_distribution_docs(output: Path) -> None:
    """Copy Apache notice files next to the binary and write checksums."""

    assets: list[Path] = [output]
    for name in DIST_DOCS:
        source = ROOT / name
        destination = OUTPUT_DIR / f"{name}.txt"
        shutil.copy2(source, destination)
        assets.append(destination)
    lines = []
    for path in assets:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest} *{path.name}")
    (OUTPUT_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="ascii",
    )


if __name__ == "__main__":
    raise SystemExit(main())
