from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "install_skill.py"


def run_installer(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def verify_skill(path: Path) -> None:
    assert (path / "SKILL.md").is_file()
    assert (path / "scripts" / "better_shutup_pipe.py").is_file()
    assert (path / "references" / "protocol.md").is_file()
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: better-shutup\n")


def test_project_install_and_dry_run(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    dry = run_installer(
        "--scope",
        "project",
        "--project-root",
        str(project),
        "--agents",
        "claude,dsh,trae",
        "--dry-run",
    )
    assert dry.returncode == 0, dry.stderr
    assert not (project / ".claude").exists()

    installed = run_installer(
        "--scope",
        "project",
        "--project-root",
        str(project),
        "--agents",
        "claude,dsh,trae",
    )
    assert installed.returncode == 0, installed.stderr
    verify_skill(project / ".claude" / "skills" / "better-shutup")
    verify_skill(project / ".dsh" / "skills" / "better-shutup")
    verify_skill(project / ".trae" / "skills" / "better-shutup")


def test_existing_requires_force(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    args = (
        "--scope",
        "project",
        "--project-root",
        str(project),
        "--agents",
        "claude",
    )
    assert run_installer(*args).returncode == 0
    again = run_installer(*args)
    assert again.returncode == 1
    assert "exists" in again.stderr

    forced = run_installer(*args, "--force")
    assert forced.returncode == 0
    verify_skill(project / ".claude" / "skills" / "better-shutup")


def test_user_install_trae_cn(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    result = run_installer(
        "--scope",
        "user",
        "--home",
        str(home),
        "--agents",
        "trae-cn",
    )
    assert result.returncode == 0, result.stderr
    verify_skill(home / ".trae-cn" / "skills" / "better-shutup")
