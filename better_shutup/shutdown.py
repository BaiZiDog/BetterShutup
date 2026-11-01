"""Windows shutdown integration with a test-friendly dry-run mode."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    ok: bool
    dry_run: bool
    detail: str


def shutdown_command() -> list[str]:
    system_root = os.environ.get("SystemRoot")
    if system_root:
        executable = Path(system_root) / "System32" / "shutdown.exe"
        if executable.is_file():
            return [str(executable), "/s", "/t", "0"]
    return ["shutdown", "/s", "/t", "0"]


def perform_shutdown(*, dry_run: bool = False) -> ShutdownResult:
    if dry_run:
        return ShutdownResult(
            ok=True,
            dry_run=True,
            detail="演练模式：已模拟发起关机，未执行 shutdown.exe。",
        )

    command = shutdown_command()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return ShutdownResult(
            ok=False,
            dry_run=False,
            detail="找不到 Windows shutdown.exe，无法发起关机。",
        )
    except subprocess.TimeoutExpired:
        return ShutdownResult(
            ok=False,
            dry_run=False,
            detail="调用 Windows 关机命令超时。",
        )
    except OSError as exc:
        return ShutdownResult(
            ok=False,
            dry_run=False,
            detail=f"调用 Windows 关机命令失败: {exc}",
        )

    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout or "").strip()
        detail = f"Windows 关机命令返回代码 {completed.returncode}"
        if output:
            detail = f"{detail}: {output}"
        return ShutdownResult(ok=False, dry_run=False, detail=detail)

    return ShutdownResult(
        ok=True,
        dry_run=False,
        detail="已请求 Windows 关机。",
    )
