#!/usr/bin/env python3
"""Portable BetterShutup named-pipe client for AI agents.

This script intentionally depends only on the Python standard library and
does not import the BetterShutup desktop application.  It supports Windows
named pipes in message mode and implements the wire format documented in
``references/protocol.md``.

Commands:
    register    register a session, generating a session id if omitted
    complete    report that the session's task is complete
    action      report that user attention is required
    error       report a task error
    resume      acknowledge that the user answered/completed an action
    notify      send an informational message to the user
    plan        create or update plan steps
    step-done   mark one plan step as complete

Every command opens one short-lived pipe connection and writes exactly one
complete frame.  BetterShutup does not send an acknowledgement, so success
means the frame was written successfully.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
import sys
import time
import unicodedata
import uuid
from typing import Any, Mapping

DEFAULT_PIPE_NAME = r"\\.\pipe\BetterShutup"
HEADER_SIZE = 4
MAX_BODY_SIZE = 0xFFFFFF
MAX_SESSION_ID_LENGTH = 128
MAX_SESSION_NAME_LENGTH = 256
MAX_PLAN_INDEX = 9999
MAX_PLAN_STEPS_PER_MESSAGE = 200
MAX_PLAN_STEP_TEXT_LENGTH = 2000

STATUS_REGISTER = 0b0000
STATUS_COMPLETE = 0b0001
STATUS_ACTION = 0b0010
STATUS_ERROR = 0b0011
STATUS_RESUME = 0b0100
STATUS_NOTIFY = 0b0101
STATUS_PLAN = 0b0110
STATUS_STEP_COMPLETE = 0b0111

STATUS_NAMES = {
    STATUS_REGISTER: "register",
    STATUS_COMPLETE: "complete",
    STATUS_ACTION: "action",
    STATUS_ERROR: "error",
    STATUS_RESUME: "resume",
    STATUS_NOTIFY: "notify",
    STATUS_PLAN: "plan",
    STATUS_STEP_COMPLETE: "step_done",
}

TEXT_FIELDS = {
    STATUS_COMPLETE: "message",
    STATUS_ACTION: "instruction",
    STATUS_ERROR: "error",
    STATUS_NOTIFY: "message",
}

GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_PIPE_BUSY = 231
ERROR_SEM_TIMEOUT = 121

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_kernel32.CreateFileW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.WaitNamedPipeW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
_kernel32.WaitNamedPipeW.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = (
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
)
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL


class CliError(Exception):
    exit_code = 1


class ValidationError(CliError):
    exit_code = 3


class PipeError(CliError):
    exit_code = 2


class PipeUnavailable(PipeError):
    pass


def normalize_pipe_name(value: str | None) -> str:
    if not value or not value.strip():
        return DEFAULT_PIPE_NAME
    value = value.strip()
    if not value.lower().startswith("\\\\.\\pipe\\"):
        value = "\\\\.\\pipe\\" + value.lstrip("\\")
    return value


def _invalid_handle(handle: int | None) -> bool:
    return not handle or handle == _INVALID_HANDLE_VALUE


def _format_error(code: int) -> str:
    try:
        text = ctypes.FormatError(code).strip()
    except Exception:
        text = ""
    return f"{text} (WinError {code})" if text else f"WinError {code}"


def _validate_session_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("session_id must be a non-empty string")
    if len(value) > MAX_SESSION_ID_LENGTH:
        raise ValidationError(
            f"session_id must be at most {MAX_SESSION_ID_LENGTH} characters"
        )
    for char in value:
        if char.isspace() or unicodedata.category(char).startswith("C"):
            raise ValidationError(
                "session_id must not contain whitespace or control characters"
            )
    return value


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _validate_session_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("session name must be a non-empty string")
    if len(value) > MAX_SESSION_NAME_LENGTH:
        raise ValidationError(
            f"session name must be at most {MAX_SESSION_NAME_LENGTH} characters"
        )
    if "\x00" in value:
        raise ValidationError("session name must not contain NUL")
    if _contains_surrogate(value):
        raise ValidationError("session name must not contain lone Unicode surrogates")
    return value


def _validate_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    if "\x00" in value:
        raise ValidationError(f"{field_name} must not contain NUL")
    if _contains_surrogate(value):
        raise ValidationError(
            f"{field_name} must not contain lone Unicode surrogates"
        )
    return value


def _validate_step_index(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("step index must be a string")
    if not value or not all("0" <= char <= "9" for char in value):
        raise ValidationError(
            f"step index must be a positive integer string (1-{MAX_PLAN_INDEX})"
        )
    if len(value) > len(str(MAX_PLAN_INDEX)):
        raise ValidationError(
            f"step index must be between 1 and {MAX_PLAN_INDEX}"
        )
    if value != str(int(value)):
        raise ValidationError("step index must not have leading zeros")
    number = int(value)
    if number < 1 or number > MAX_PLAN_INDEX:
        raise ValidationError(
            f"step index must be between 1 and {MAX_PLAN_INDEX}"
        )
    return value


def _validate_step_text(value: Any, index: str) -> str:
    text = _validate_text(value, f"plan step {index}")
    if not text.strip():
        raise ValidationError(f"plan step {index} must not be empty")
    if len(text) > MAX_PLAN_STEP_TEXT_LENGTH:
        raise ValidationError(
            f"plan step {index} must be at most "
            f"{MAX_PLAN_STEP_TEXT_LENGTH} characters"
        )
    return text


def _optional_text(fields: Mapping[str, Any], field_name: str) -> str:
    if field_name not in fields:
        return ""
    return _validate_text(fields[field_name], field_name)


def build_frame(status: int, fields: Mapping[str, Any]) -> bytes:
    """Build one complete frame using the BetterShutup wire protocol."""

    if status not in STATUS_NAMES:
        raise ValidationError(f"unknown status: {status!r}")
    if not isinstance(fields, Mapping):
        raise ValidationError("fields must be a mapping")

    if status == STATUS_REGISTER:
        if "session_name" not in fields or "session_id" not in fields:
            raise ValidationError("register requires session_name and session_id")
        payload: dict[str, Any] = {
            "session_name": _validate_session_name(fields["session_name"]),
            "session_id": _validate_session_id(fields["session_id"]),
        }
    elif status == STATUS_PLAN:
        if "session_id" not in fields:
            raise ValidationError("plan requires session_id")
        session_id = _validate_session_id(fields["session_id"])
        step_payload: dict[str, str] = {}
        for raw_index, raw_text in fields.items():
            if raw_index == "session_id":
                continue
            index = _validate_step_index(raw_index)
            step_payload[index] = _validate_step_text(raw_text, index)
        if not step_payload:
            raise ValidationError("plan requires at least one step")
        if len(step_payload) > MAX_PLAN_STEPS_PER_MESSAGE:
            raise ValidationError(
                f"plan may contain at most {MAX_PLAN_STEPS_PER_MESSAGE} steps"
            )
        payload = {"session_id": session_id}
        for index in sorted(step_payload, key=int):
            payload[index] = step_payload[index]
    elif status == STATUS_STEP_COMPLETE:
        if "session_id" not in fields:
            raise ValidationError("step-done requires session_id")
        if "step_index" not in fields:
            raise ValidationError("step-done requires step_index")
        payload = {
            "session_id": _validate_session_id(fields["session_id"]),
            "step_index": _validate_step_index(fields["step_index"]),
        }
        text = _optional_text(fields, "message")
        if text:
            payload["message"] = text
    elif status == STATUS_RESUME:
        if "session_id" not in fields:
            raise ValidationError("resume requires session_id")
        payload = {"session_id": _validate_session_id(fields["session_id"])}
        text = _optional_text(fields, "message")
        if text:
            payload["message"] = text
    else:
        if "session_id" not in fields:
            raise ValidationError("session_id is required")
        text_field = TEXT_FIELDS[status]
        if text_field not in fields:
            raise ValidationError(f"{STATUS_NAMES[status]} requires {text_field}")
        payload = {
            "session_id": _validate_session_id(fields["session_id"]),
            text_field: _validate_text(fields[text_field], text_field),
        }

    try:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValidationError(f"payload contains non-UTF-8 characters: {exc}") from exc
    if len(body) > MAX_BODY_SIZE:
        raise ValidationError(
            f"payload is too large ({len(body)} bytes; maximum {MAX_BODY_SIZE})"
        )
    return bytes((status,)) + len(body).to_bytes(3, "big") + body


def _open_pipe(pipe_name: str, timeout_ms: int) -> int:
    started = time.monotonic()
    deadline = started + max(0, timeout_ms) / 1000.0
    not_found_grace = min(0.30, max(0.0, timeout_ms / 1000.0))
    ever_busy = False

    while True:
        handle = _kernel32.CreateFileW(
            pipe_name,
            GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if not _invalid_handle(handle):
            return int(handle)

        code = ctypes.get_last_error()
        if code in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
            now = time.monotonic()
            if ever_busy and now < deadline:
                time.sleep(0.015)
                continue
            if now - started < not_found_grace and now < deadline:
                time.sleep(0.015)
                continue
            raise PipeUnavailable(
                f"BetterShutup is not running (pipe not found: {pipe_name})"
            )
        if code == ERROR_PIPE_BUSY:
            ever_busy = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PipeUnavailable(
                    f"Pipe is busy and the wait timed out: {pipe_name}"
                )
            wait_ms = min(500, max(1, int(remaining * 1000)))
            if not _kernel32.WaitNamedPipeW(pipe_name, wait_ms):
                wait_error = ctypes.get_last_error()
                if wait_error == ERROR_FILE_NOT_FOUND and time.monotonic() < deadline:
                    continue
                if wait_error == ERROR_SEM_TIMEOUT:
                    continue
                raise PipeError(
                    f"WaitNamedPipe failed: {_format_error(wait_error)}"
                )
            continue
        raise PipeError(f"CreateFile failed: {_format_error(code)}")


def send_frame(pipe_name: str, frame: bytes, timeout_ms: int = 5000) -> int:
    handle = _open_pipe(pipe_name, timeout_ms)
    try:
        buffer = ctypes.create_string_buffer(frame)
        written = wintypes.DWORD(0)
        ok = _kernel32.WriteFile(
            handle,
            ctypes.byref(buffer),
            len(frame),
            ctypes.byref(written),
            None,
        )
        if not ok:
            code = ctypes.get_last_error()
            raise PipeError(f"WriteFile failed: {_format_error(code)}")
        if int(written.value) != len(frame):
            raise PipeError(
                f"WriteFile wrote {int(written.value)} of {len(frame)} bytes"
            )
        return int(written.value)
    finally:
        _kernel32.CloseHandle(handle)


def _emit(data: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=True) + "\n")
    sys.stdout.flush()


class _CliArgumentParser(argparse.ArgumentParser):
    """Return a machine-readable JSON error instead of argparse's exit 2."""

    def error(self, message: str) -> None:
        _emit(
            {
                "ok": False,
                "event": "argument_error",
                "error": message,
            }
        )
        raise SystemExit(3)


def _build_parser() -> argparse.ArgumentParser:
    common = _CliArgumentParser(add_help=False)
    common.add_argument(
        "--pipe",
        default=os.environ.get("BETTER_SHUTUP_PIPE", DEFAULT_PIPE_NAME),
        help=f"Named pipe path (default: {DEFAULT_PIPE_NAME})",
    )
    common.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="Connection timeout in milliseconds (default: 5000)",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate/build the frame without connecting (diagnostic only)",
    )

    parser = _CliArgumentParser(
        prog="better-shutup-pipe",
        description=(
            "Send BetterShutup session messages through its Windows named pipe. "
            "The app must already be running."
        ),
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_CliArgumentParser,
    )

    register = sub.add_parser(
        "register",
        parents=[common],
        help="Register a session (0000)",
    )
    register.add_argument("--name", required=True, help="Human-readable session name")
    register.add_argument(
        "--session-id",
        default=None,
        help="Stable session id; generated if omitted",
    )

    complete = sub.add_parser(
        "complete",
        parents=[common],
        help="Report task completion (0001)",
    )
    complete.add_argument("--session-id", required=True)
    complete.add_argument("--message", required=True)

    action = sub.add_parser(
        "action",
        parents=[common],
        help="Report that user action is required (0010)",
    )
    action.add_argument("--session-id", required=True)
    action.add_argument("--instruction", required=True)

    error = sub.add_parser(
        "error",
        parents=[common],
        help="Report an error (0011)",
    )
    error.add_argument("--session-id", required=True)
    error.add_argument("--error", required=True)

    resume = sub.add_parser(
        "resume",
        parents=[common],
        help="Acknowledge that the user responded to an action request (0100)",
    )
    resume.add_argument("--session-id", required=True)
    resume.add_argument(
        "--message",
        default="",
        help="Optional acknowledgement note for the event log",
    )

    notify = sub.add_parser(
        "notify",
        parents=[common],
        help="Send an informational message that needs no action (0101)",
    )
    notify.add_argument("--session-id", required=True)
    notify.add_argument("--message", required=True)

    plan = sub.add_parser(
        "plan",
        parents=[common],
        help="Create or update plan steps (0110)",
    )
    plan.add_argument("--session-id", required=True)
    plan_steps = plan.add_mutually_exclusive_group(required=True)
    plan_steps.add_argument(
        "--steps-json",
        help=(
            'JSON object mapping 1-based index to text, for example '
            '\'{"1":"Analyze code","2":"Implement"}\''
        ),
    )
    plan_steps.add_argument(
        "--step",
        action="append",
        nargs=2,
        metavar=("INDEX", "TEXT"),
        help="Repeatable index/text pair; later duplicates overwrite earlier ones",
    )

    step_done = sub.add_parser(
        "step-done",
        parents=[common],
        help="Mark one existing plan step as complete (0111)",
    )
    step_done.add_argument("--session-id", required=True)
    step_done.add_argument(
        "--index",
        required=True,
        help=f"Plan step index, 1-{MAX_PLAN_INDEX}",
    )
    step_done.add_argument(
        "--message",
        default="",
        help="Optional completion note for the event log",
    )

    return parser


def _plan_fields(args: argparse.Namespace) -> dict[str, Any]:
    fields: dict[str, Any] = {"session_id": args.session_id}
    if args.steps_json is not None:
        try:
            steps = json.loads(args.steps_json)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"--steps-json is not valid JSON: {exc.msg}") from exc
        if not isinstance(steps, dict):
            raise ValidationError("--steps-json must be a JSON object")
        if "session_id" in steps:
            raise ValidationError(
                "--steps-json must not contain session_id; use --session-id"
            )
        fields.update(steps)
        return fields
    for index, text in args.step or []:
        if index == "session_id":
            raise ValidationError(
                "step index must not be 'session_id'; use --session-id"
            )
        fields[index] = text
    return fields


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pipe_name = normalize_pipe_name(args.pipe)
    command = args.command

    session_id = getattr(args, "session_id", None)
    step_index: str | None = None
    if command == "register":
        if session_id is None:
            session_id = uuid.uuid4().hex
        status = STATUS_REGISTER
        fields = {"session_name": args.name, "session_id": session_id}
    elif command == "complete":
        status = STATUS_COMPLETE
        fields = {"session_id": session_id, "message": args.message}
    elif command == "action":
        status = STATUS_ACTION
        fields = {"session_id": session_id, "instruction": args.instruction}
    elif command == "error":
        status = STATUS_ERROR
        fields = {"session_id": session_id, "error": args.error}
    elif command == "resume":
        status = STATUS_RESUME
        fields = {"session_id": session_id, "message": args.message}
    elif command == "notify":
        status = STATUS_NOTIFY
        fields = {"session_id": session_id, "message": args.message}
    elif command == "plan":
        status = STATUS_PLAN
        try:
            fields = _plan_fields(args)
        except ValidationError as exc:
            _emit(
                {
                    "ok": False,
                    "event": STATUS_NAMES[STATUS_PLAN],
                    "session_id": session_id,
                    "error": str(exc),
                }
            )
            return exc.exit_code
    else:
        status = STATUS_STEP_COMPLETE
        fields = {
            "session_id": session_id,
            "step_index": args.index,
            "message": args.message,
        }
    event = STATUS_NAMES[status]
    if status == STATUS_STEP_COMPLETE:
        step_index = args.index

    try:
        frame = build_frame(status, fields)
        if args.dry_run:
            result = {
                "ok": True,
                "dry_run": True,
                "event": event,
                "session_id": session_id,
                "pipe": pipe_name,
                "frame_length": len(frame),
                "header_hex": frame[:HEADER_SIZE].hex(),
            }
            if step_index is not None:
                result["step_index"] = step_index
            if status == STATUS_PLAN:
                result["step_count"] = len(fields) - 1
            _emit(result)
            return 0
        send_frame(pipe_name, frame, timeout_ms=args.timeout_ms)
    except ValidationError as exc:
        _emit(
            {
                "ok": False,
                "event": event,
                "session_id": session_id,
                "error": str(exc),
            }
        )
        return exc.exit_code
    except PipeError as exc:
        _emit(
            {
                "ok": False,
                "event": event,
                "session_id": session_id,
                "pipe": pipe_name,
                "error": str(exc),
                "hint": "Start the BetterShutup desktop app first.",
            }
        )
        return exc.exit_code
    except Exception as exc:  # Defensive CLI boundary.
        _emit(
            {
                "ok": False,
                "event": event,
                "session_id": session_id,
                "error": f"unexpected error: {exc}",
            }
        )
        return 1

    result = {
        "ok": True,
        "event": event,
        "session_id": session_id,
        "pipe": pipe_name,
        "bytes_written": len(frame),
    }
    if step_index is not None:
        result["step_index"] = step_index
    if status == STATUS_PLAN:
        result["step_count"] = len(fields) - 1
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
