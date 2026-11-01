"""Small ctypes wrapper around the Win32 named-pipe APIs used by BetterShutup."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time

from .protocol import MAX_FRAME_SIZE

GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3

FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_ACCESS_INBOUND = 0x00000001
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
PIPE_UNLIMITED_INSTANCES = 255

ERROR_ACCESS_DENIED = 5
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_BUSY = 231
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_MORE_DATA = 234
ERROR_NO_DATA = 232
ERROR_PIPE_CONNECTED = 535
ERROR_SEM_TIMEOUT = 121
ERROR_OPERATION_ABORTED = 995

_PIPE_BUFFER_SIZE = 64 * 1024
_CLOSED_ERRORS = {ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_PIPE_NOT_CONNECTED}
_BUSY_ERRORS = {ERROR_PIPE_BUSY}
_NOT_FOUND_ERRORS = {ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND}

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_kernel32.CreateNamedPipeW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
)
_kernel32.CreateNamedPipeW.restype = wintypes.HANDLE

_kernel32.ConnectNamedPipe.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
_kernel32.ConnectNamedPipe.restype = wintypes.BOOL

_kernel32.ReadFile.argtypes = (
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
)
_kernel32.ReadFile.restype = wintypes.BOOL

_kernel32.WriteFile.argtypes = (
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
)
_kernel32.WriteFile.restype = wintypes.BOOL

_kernel32.WaitNamedPipeW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
_kernel32.WaitNamedPipeW.restype = wintypes.BOOL

_kernel32.DisconnectNamedPipe.argtypes = (wintypes.HANDLE,)
_kernel32.DisconnectNamedPipe.restype = wintypes.BOOL

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

_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL


class PipeError(OSError):
    """A named-pipe operation failed."""

    def __init__(self, message: str, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class PipeUnavailable(PipeError):
    """The BetterShutup server is not listening on the requested pipe."""


class PipeMessageTooLarge(PipeError):
    """A peer sent a message larger than the protocol permits."""


def _is_invalid_handle(handle: int | None) -> bool:
    return not handle or handle == _INVALID_HANDLE_VALUE


def _format_error(error_code: int) -> str:
    try:
        detail = ctypes.FormatError(error_code).strip()
    except Exception:
        detail = ""
    if detail:
        return f"{detail} (WinError {error_code})"
    return f"WinError {error_code}"


def create_pipe_instance(pipe_name: str, *, first: bool = False) -> int:
    """Create one server-side inbound message-mode pipe instance."""

    open_mode = PIPE_ACCESS_INBOUND
    if first:
        open_mode |= FILE_FLAG_FIRST_PIPE_INSTANCE
    pipe_mode = (
        PIPE_TYPE_MESSAGE
        | PIPE_READMODE_MESSAGE
        | PIPE_WAIT
        | PIPE_REJECT_REMOTE_CLIENTS
    )
    handle = _kernel32.CreateNamedPipeW(
        pipe_name,
        open_mode,
        pipe_mode,
        PIPE_UNLIMITED_INSTANCES,
        _PIPE_BUFFER_SIZE,
        _PIPE_BUFFER_SIZE,
        0,
        None,
    )
    if _is_invalid_handle(handle):
        code = ctypes.get_last_error()
        if code == ERROR_ACCESS_DENIED and first:
            raise PipeError(
                f"命名管道已被占用或无法创建: {pipe_name} "
                f"({_format_error(code)})",
                code,
            )
        raise PipeError(
            f"无法创建命名管道 {pipe_name}: {_format_error(code)}", code
        )
    return int(handle)


def connect_pipe(handle: int) -> bool:
    """Wait for a client to connect to a server instance.

    Returns ``True`` when connected.  ``False`` means a client connected and
    closed before the server began waiting.  Even in that case the pipe may
    still hold buffered data, so the caller should attempt to read a message.
    """

    ok = _kernel32.ConnectNamedPipe(handle, None)
    if ok:
        return True
    code = ctypes.get_last_error()
    if code == ERROR_PIPE_CONNECTED:
        return True
    if code == ERROR_NO_DATA:
        return False
    raise PipeError(f"等待客户端连接失败: {_format_error(code)}", code)


def disconnect_pipe(handle: int) -> None:
    try:
        _kernel32.DisconnectNamedPipe(handle)
    except Exception:
        pass


def close_handle(handle: int) -> None:
    if handle and not _is_invalid_handle(handle):
        _kernel32.CloseHandle(handle)


def read_pipe_message(handle: int) -> bytes | None:
    """Read exactly one message-mode message.

    Returns ``None`` if a client connects and closes without sending data.
    Raises :class:`PipeError` on I/O failures and
    :class:`PipeMessageTooLarge` if the peer exceeds the protocol maximum.
    """

    chunks: list[bytes] = []
    total = 0
    buffer = ctypes.create_string_buffer(_PIPE_BUFFER_SIZE)

    while True:
        bytes_read = wintypes.DWORD(0)
        ok = _kernel32.ReadFile(
            handle,
            ctypes.byref(buffer),
            _PIPE_BUFFER_SIZE,
            ctypes.byref(bytes_read),
            None,
        )
        count = int(bytes_read.value)
        code = 0 if ok else ctypes.get_last_error()

        if ok:
            if count:
                chunks.append(bytes(buffer.raw[:count]))
                total += count
            if not chunks:
                return None
            if total > MAX_FRAME_SIZE:
                raise PipeMessageTooLarge(
                    f"消息超过最大帧长度 {MAX_FRAME_SIZE} 字节"
                )
            return b"".join(chunks)

        if code == ERROR_MORE_DATA:
            if count:
                chunks.append(bytes(buffer.raw[:count]))
                total += count
            if total > MAX_FRAME_SIZE:
                raise PipeMessageTooLarge(
                    f"消息超过最大帧长度 {MAX_FRAME_SIZE} 字节",
                    code,
                )
            if count == 0:
                raise PipeError(
                    "读取管道消息时没有取得数据，无法继续", code
                )
            continue

        if code in _CLOSED_ERRORS:
            if chunks:
                raise PipeError(
                    "客户端在发送完整消息前断开连接", code
                )
            return None

        raise PipeError(f"读取管道消息失败: {_format_error(code)}", code)


def write_pipe_frame(handle: int, frame: bytes) -> None:
    """Write one complete frame with a single WriteFile call."""

    if len(frame) > 0xFFFFFFFF:
        raise PipeError("待写入帧过大")
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
        raise PipeError(f"写入命名管道失败: {_format_error(code)}", code)
    if int(written.value) != len(frame):
        raise PipeError(
            f"写入不完整: 期望 {len(frame)} 字节，实际 {int(written.value)} 字节"
        )


def wait_named_pipe(pipe_name: str, timeout_ms: int) -> None:
    ok = _kernel32.WaitNamedPipeW(pipe_name, max(0, int(timeout_ms)))
    if not ok:
        code = ctypes.get_last_error()
        if code == ERROR_SEM_TIMEOUT:
            raise PipeUnavailable(
                f"等待命名管道超时: {pipe_name}", code
            )
        if code in _NOT_FOUND_ERRORS:
            raise PipeUnavailable(
                f"BetterShutup 未运行（找不到管道 {pipe_name}）", code
            )
        raise PipeError(
            f"等待命名管道失败: {_format_error(code)}", code
        )


def open_pipe_client(pipe_name: str, timeout_ms: int = 5000) -> int:
    """Open a client handle, waiting for a free server instance if necessary."""

    started = time.monotonic()
    deadline = started + max(0, int(timeout_ms)) / 1000.0
    # The server briefly has no free instance while it replaces the accepted
    # one.  Allow a short grace period so a truly absent server still fails
    # promptly, without losing messages sent in rapid succession.
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
        if not _is_invalid_handle(handle):
            return int(handle)

        code = ctypes.get_last_error()
        if code in _NOT_FOUND_ERRORS:
            now = time.monotonic()
            if ever_busy and now < deadline:
                time.sleep(0.015)
                continue
            if now - started < not_found_grace and now < deadline:
                time.sleep(0.015)
                continue
            raise PipeUnavailable(
                f"BetterShutup 未运行（找不到管道 {pipe_name}）", code
            )
        if code in _BUSY_ERRORS:
            ever_busy = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PipeUnavailable(
                    f"命名管道正忙，等待超时: {pipe_name}", code
                )
            wait_ms = min(500, max(1, int(remaining * 1000)))
            try:
                wait_named_pipe(pipe_name, wait_ms)
            except PipeUnavailable:
                if time.monotonic() >= deadline:
                    raise
            continue

        raise PipeError(
            f"无法连接命名管道 {pipe_name}: {_format_error(code)}", code
        )


def open_pipe_probe(pipe_name: str, timeout_ms: int = 150) -> bool:
    """Try to open and immediately close the pipe without sending data."""

    try:
        handle = open_pipe_client(pipe_name, timeout_ms=timeout_ms)
    except PipeError:
        return False
    close_handle(handle)
    return True
