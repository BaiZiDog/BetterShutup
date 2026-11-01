#!/usr/bin/env python3
"""Install the portable BetterShutup skill into agent skill directories.

Examples:
    python tools/install_skill.py --scope project --agents claude,dsh,trae
    python tools/install_skill.py --scope user --agents claude,dsh --force
    python tools/install_skill.py --scope project --dry-run

Only the canonical ``skills/better-shutup`` directory is copied.  Existing
skill directories are never overwritten without ``--force``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

SKILL_NAME = "better-shutup"
ALL_AGENTS = ("claude", "dsh", "trae", "trae-cn")


def project_base(agent: str, project_root: Path) -> Path:
    if agent == "claude":
        return project_root / ".claude" / "skills"
    if agent == "dsh":
        return project_root / ".dsh" / "skills"
    if agent in {"trae", "trae-cn"}:
        return project_root / ".trae" / "skills"
    raise ValueError(f"unknown agent: {agent}")


def user_base(agent: str, home: Path) -> Path:
    if agent == "claude":
        return home / ".claude" / "skills"
    if agent == "dsh":
        return home / ".dsh" / "skills"
    if agent == "trae":
        return home / ".trae" / "skills"
    if agent == "trae-cn":
        return home / ".trae-cn" / "skills"
    raise ValueError(f"unknown agent: {agent}")


def parse_agents(value: str) -> list[str]:
    requested = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not requested:
        raise ValueError("no agents selected")
    for agent in requested:
        if agent not in ALL_AGENTS:
            raise ValueError(
                f"unknown agent {agent!r}; expected one of {', '.join(ALL_AGENTS)}"
            )
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(requested))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copy the BetterShutup skill into Claude Code / DSH / TRAE skill "
            "directories."
        )
    )
    parser.add_argument(
        "--scope",
        choices=("project", "user"),
        default="project",
        help="Install into the current project or the user profile.",
    )
    parser.add_argument(
        "--agents",
        default="claude,dsh,trae",
        help=(
            "Comma-separated targets: claude,dsh,trae,trae-cn "
            "(default: claude,dsh,trae)."
        ),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root for project scope (default: current directory).",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="Home directory for user scope (default: current user profile).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing better-shutup skill directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print destinations without copying anything.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        agents = parse_agents(args.agents)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    source = Path(__file__).resolve().parents[1] / "skills" / SKILL_NAME
    if not (source / "SKILL.md").is_file():
        print(f"error: source skill not found at {source}", file=sys.stderr)
        return 1

    project_root = args.project_root.expanduser().resolve()
    home = args.home.expanduser().resolve()
    destinations: list[tuple[str, Path]] = []
    for agent in agents:
        base = (
            project_base(agent, project_root)
            if args.scope == "project"
            else user_base(agent, home)
        )
        destination = base / SKILL_NAME
        if all(existing != destination for _, existing in destinations):
            destinations.append((agent, destination))

    errors: list[str] = []
    for agent, destination in destinations:
        if destination.exists() and not args.force:
            errors.append(
                f"{agent}: destination exists (use --force to replace): {destination}"
            )
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    for agent, destination in destinations:
        print(f"{'[dry-run] ' if args.dry_run else ''}{agent}: {destination}")
        if args.dry_run:
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
        except OSError as exc:
            print(f"error: failed to install for {agent}: {exc}", file=sys.stderr)
            return 1

    if not args.dry_run:
        print("")
        print("Installed. Restart the agent or reload its skills, then invoke")
        print("better-shutup when you want to track a task.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
