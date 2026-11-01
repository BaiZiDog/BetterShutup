#!/usr/bin/env python3
"""Portable BetterShutup named-pipe client for AI agents.

This script intentionally depends only on the Python standard library and
does not import the BetterShutup desktop application.  It supports Windows
named pipes in message mode and implements the wire format documented in
``references/protocol.md``.

Commands:
    register   register a session, generating a session id if omitted
    complete   report that the session's task is complete
    action     report that user attention is required
    error      report a task error

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

STATUS_REGISTER = 0b00
STATUS_COMPLETE = 0b01
STATUS_ACTION = 0b10
STATUS_ERROR = 0b11

STATUS_NAMES = {
    STATUS_REGISTER: "register",
    STATUS_COMPLETE: "complete",
    STATUS_ACTION: "action",
    STATUS_ERROR: "error",
}

TEXT_FIELDS = {
    STATUS_COMPLETE: "message",
    STATUS_ACTION: "instruction",
    STATUS_ERROR: "error",
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


def _validate_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    if "\x00" in value:
        raise ValidationError(f"{field_name} must not contain NUL")
    if _contains_surrogate(value):
        raise ValidationError(
            f"{field_name} must not contain lone Unicode surrogates"
        )
    return value


def build_frame(status: int, fields: Mapping[str, Any]) -> bytes:
    """Build one complete frame using the BetterShutup wire protocol."""

    if status not in STATUS_NAMES:
        raise ValidationError(f"unknown status: {status!r}")
    if not isinstance(fields, Mapping):
        raise ValidationError("fields must be a mapping")

    if status == STATUS_REGISTER:
        if "session_name" not in fields or "session_id" not in fields:
            raise ValidationError("register requires session_name and session_id")
        payload = {
            "session_name": _validate_session_name(fields["session_name"]),
            "session_id": _validate_session_id(fields["session_id"]),
        }
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
        help="Register a session (00)",
    )
    register.add_argument("--name", required=True, help="Human-readable session name")
    register.add_argument(
        "--session-id",
        default=None,
        help="Stable session id; generated if omitted",
    )

    resume = sub.add_parser(
        "resume",
        parents=[common],
        help="Clear an existing session's action-needed state (00)",
    )
    resume.add_argument("--session-id", required=True)
    resume.add_argument(
        "--name",
        required=True,
        help="Session name to keep/update",
    )

    complete = sub.add_parser(
        "complete",
        parents=[common],
        help="Report task completion (01)",
    )
    complete.add_argument("--session-id", required=True)
    complete.add_argument("--message", required=True)

    action = sub.add_parser(
        "action",
        parents=[common],
        help="Report that user action is required (10)",
    )
    action.add_argument("--session-id", required=True)
    action.add_argument("--instruction", required=True)

    error = sub.add_parser(
        "error",
        parents=[common],
        help="Report an error (11)",
    )
    error.add_argument("--session-id", required=True)
    error.add_argument("--error", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pipe_name = normalize_pipe_name(args.pipe)
    command = args.command

    session_id = getattr(args, "session_id", None)
    if command == "register":
        if session_id is None:
            session_id = uuid.uuid4().hex
        status = STATUS_REGISTER
        fields = {"session_name": args.name, "session_id": session_id}
        event = "register"
    elif command == "resume":
        status = STATUS_REGISTER
        fields = {"session_name": args.name, "session_id": session_id}
        event = "resume"
    elif command == "complete":
        status = STATUS_COMPLETE
        fields = {"session_id": session_id, "message": args.message}
        event = "complete"
    elif command == "action":
        status = STATUS_ACTION
        fields = {"session_id": session_id, "instruction": args.instruction}
        event = "action"
    else:
        status = STATUS_ERROR
        fields = {"session_id": session_id, "error": args.error}
        event = "error"
    try:
        frame = build_frame(status, fields)
        if args.dry_run:
            _emit(
                {
                    "ok": True,
                    "dry_run": True,
                    "event": event,
                    "session_id": session_id,
                    "pipe": pipe_name,
                    "frame_length": len(frame),
                    "header_hex": frame[:HEADER_SIZE].hex(),
                }
            )
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

    _emit(
        {
            "ok": True,
            "event": event,
            "session_id": session_id,
            "pipe": pipe_name,
            "bytes_written": len(frame),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
