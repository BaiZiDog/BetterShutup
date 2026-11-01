from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import queue
import subprocess
import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows named pipes only"
)
if sys.platform != "win32":
    pytest.skip("Windows named pipes only", allow_module_level=True)

from better_shutup import DEFAULT_PIPE_NAME
from better_shutup.pipe_server import PipeServer
from better_shutup.protocol import Status, decode_frame, encode_message

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "better-shutup" / "scripts" / "better_shutup_pipe.py"


def load_skill_module():
    spec = importlib.util.spec_from_file_location("better_shutup_skill_client", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unique_pipe() -> str:
    return DEFAULT_PIPE_NAME + "-skill-test-" + uuid.uuid4().hex


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=SCRIPT.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize(
    ("status", "fields"),
    [
        (
            Status.REGISTER,
            {"session_name": "Claude Code · 测试", "session_id": "id-1"},
        ),
        (
            Status.COMPLETE,
            {"session_id": "id-1", "message": "完成：测试通过"},
        ),
        (
            Status.ACTION,
            {"session_id": "id-1", "instruction": "请确认发布"},
        ),
        (
            Status.ERROR,
            {"session_id": "id-1", "error": "构建失败"},
        ),
    ],
)
def test_frame_bytes_match_application_protocol(status, fields) -> None:
    module = load_skill_module()
    assert module.build_frame(int(status), fields) == encode_message(status, fields)
    decoded = decode_frame(module.build_frame(int(status), fields))
    assert decoded.status is status


def test_skill_validation() -> None:
    module = load_skill_module()
    with pytest.raises(module.ValidationError):
        module.build_frame(
            module.STATUS_COMPLETE,
            {"session_id": "has space", "message": "x"},
        )
    with pytest.raises(module.ValidationError):
        module.build_frame(
            module.STATUS_REGISTER,
            {"session_name": "", "session_id": "id"},
        )
    with pytest.raises(module.ValidationError):
        module.build_frame(
            module.STATUS_COMPLETE,
            {"session_id": "id", "message": "\ud800"},
        )


def test_cli_lifecycle_and_portability() -> None:
    pipe_name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server = PipeServer(pipe_name, q.put, lambda message: q.put(b"ERROR"))
    server.start()
    try:
        register = run_cli(
            "register",
            "--name",
            "Skill CLI · 测试",
            "--session-id",
            "skill-1",
            "--pipe",
            pipe_name,
        )
        assert register.returncode == 0, register.stderr + register.stdout
        payload = json.loads(register.stdout)
        assert payload["ok"] is True
        assert payload["session_id"] == "skill-1"
        assert decode_frame(q.get(timeout=3)).session_id == "skill-1"

        action = run_cli(
            "action",
            "--session-id",
            "skill-1",
            "--instruction",
            "需要确认",
            "--pipe",
            pipe_name,
        )
        assert action.returncode == 0
        action_message = decode_frame(q.get(timeout=3))
        assert action_message.status is Status.ACTION
        assert action_message.text == "需要确认"

        complete = run_cli(
            "complete",
            "--session-id",
            "skill-1",
            "--message",
            "完成",
            "--pipe",
            pipe_name,
        )
        assert complete.returncode == 0
        assert decode_frame(q.get(timeout=3)).status is Status.COMPLETE
    finally:
        server.stop()


def test_cli_register_generates_session_id() -> None:
    pipe_name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server = PipeServer(pipe_name, q.put)
    server.start()
    try:
        result = run_cli(
            "register",
            "--name",
            "Generated ID",
            "--pipe",
            pipe_name,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert len(payload["session_id"]) == 32
        received = decode_frame(q.get(timeout=3))
        assert received.session_id == payload["session_id"]
    finally:
        server.stop()


def test_cli_missing_server_is_clean_error() -> None:
    pipe_name = unique_pipe()
    result = run_cli(
        "register",
        "--name",
        "No App",
        "--pipe",
        pipe_name,
        "--timeout-ms",
        "800",
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "not running" in payload["error"]


def test_cli_dry_run_does_not_need_server() -> None:
    result = run_cli(
        "register",
        "--name",
        "Dry Run",
        "--dry-run",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["frame_length"] > 4


def test_cli_validation_exit_code() -> None:
    result = run_cli(
        "complete",
        "--session-id",
        "bad id",
        "--message",
        "x",
        "--dry-run",
    )
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False


def test_cli_explicit_empty_session_id_is_rejected() -> None:
    result = run_cli(
        "register",
        "--name",
        "Empty ID",
        "--session-id",
        "",
        "--dry-run",
    )
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "session_id" in payload["error"]


def test_cli_missing_argument_returns_json_error() -> None:
    result = run_cli("complete", "--session-id", "abc")
    assert result.returncode == 3
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["event"] == "argument_error"
    assert "--message" in payload["error"]
