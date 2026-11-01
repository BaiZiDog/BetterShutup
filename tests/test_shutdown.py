from __future__ import annotations

import subprocess

from better_shutup import shutdown


class FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_dry_run_never_calls_subprocess(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("subprocess must not run in dry-run mode")

    monkeypatch.setattr(shutdown.subprocess, "run", fail)
    result = shutdown.perform_shutdown(dry_run=True)
    assert result.ok is True
    assert result.dry_run is True
    assert "演练" in result.detail


def test_successful_shutdown_command(monkeypatch) -> None:
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return FakeCompleted(0)

    monkeypatch.setattr(shutdown.subprocess, "run", fake_run)
    result = shutdown.perform_shutdown(dry_run=False)
    assert result.ok is True
    assert result.dry_run is False
    command = calls["command"]
    assert command[-3:] == ["/s", "/t", "0"]
    assert "/f" not in command
    assert calls["kwargs"]["creationflags"] == shutdown.CREATE_NO_WINDOW
    assert calls["kwargs"]["check"] is False


def test_failed_shutdown_command(monkeypatch) -> None:
    monkeypatch.setattr(
        shutdown.subprocess,
        "run",
        lambda *_args, **_kwargs: FakeCompleted(5, stderr="access denied"),
    )
    result = shutdown.perform_shutdown()
    assert result.ok is False
    assert "5" in result.detail
    assert "access denied" in result.detail


def test_missing_shutdown_executable(monkeypatch) -> None:
    def raise_missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(shutdown.subprocess, "run", raise_missing)
    result = shutdown.perform_shutdown()
    assert result.ok is False
    assert "shutdown.exe" in result.detail


def test_shutdown_timeout(monkeypatch) -> None:
    def raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="shutdown", timeout=15)

    monkeypatch.setattr(shutdown.subprocess, "run", raise_timeout)
    result = shutdown.perform_shutdown()
    assert result.ok is False
    assert "超时" in result.detail
