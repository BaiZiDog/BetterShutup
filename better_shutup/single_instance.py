"""Single-instance guard backed by a Windows named mutex."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.CreateMutexW.argtypes = (
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.LPCWSTR,
)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstance:
    def __init__(self, name: str) -> None:
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        ctypes.set_last_error(0)
        handle = _kernel32.CreateMutexW(None, False, self.name)
        error_code = ctypes.get_last_error()
        if not handle:
            raise OSError(error_code, "无法创建单实例互斥体")
        if error_code == ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(handle)
            return False
        self._handle = int(handle)
        return True

    def close(self) -> None:
        if self._handle is not None:
            _kernel32.CloseHandle(self._handle)
            self._handle = None
