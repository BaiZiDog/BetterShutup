"""Client helpers used by tests and local diagnostics."""

from __future__ import annotations

from typing import Any, Mapping

from .protocol import Status, encode_message
from .win32_pipe import close_handle, open_pipe_client, write_pipe_frame


def send_frame(
    pipe_name: str,
    frame: bytes,
    *,
    timeout_ms: int = 5000,
) -> int:
    """Open a short-lived connection and write exactly one frame."""

    handle = open_pipe_client(pipe_name, timeout_ms=timeout_ms)
    try:
        write_pipe_frame(handle, frame)
    finally:
        close_handle(handle)
    return len(frame)


def send_message(
    pipe_name: str,
    status: Status,
    fields: Mapping[str, Any],
    *,
    timeout_ms: int = 5000,
) -> int:
    return send_frame(
        pipe_name,
        encode_message(status, fields),
        timeout_ms=timeout_ms,
    )
