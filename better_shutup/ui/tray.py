"""Windows system-tray icon with a message-only window."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import threading
from typing import Final

_WM_APP = 0x8000
_WM_TRAY = _WM_APP + 1
_WM_CLOSE = 0x0010
_WM_DESTROY = 0x0002
_WM_COMMAND = 0x0111
_WM_NULL = 0x0000
_WM_RBUTTONUP = 0x0205
_WM_LBUTTONDBLCLK = 0x0203
_WM_LBUTTONUP = 0x0202

_NIM_ADD = 0x00000000
_NIM_DELETE = 0x00000002
_NIM_SETVERSION = 0x00000004
_NIF_MESSAGE = 0x00000001
_NIF_ICON = 0x00000002
_NIF_TIP = 0x00000004
_NIF_SHOWTIP = 0x00000080
_NOTIFYICON_VERSION_3 = 3

_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_LR_DEFAULTSIZE = 0x0040
_IDI_APPLICATION = 32512

_MF_STRING = 0x00000000
_MF_SEPARATOR = 0x00000800
_TPM_RETURNCMD = 0x0100
_TPM_NONOTIFY = 0x0080
_TPM_RIGHTBUTTON = 0x0002

_HWND_MESSAGE = wintypes.HWND(-3)
_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

_MENU_SHOW: Final = 1
_MENU_HIDE: Final = 2
_MENU_SETTINGS: Final = 3
_MENU_EXIT: Final = 4


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _GUID),
        ("hBalloonIcon", wintypes.HICON),
    )


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    )


class _POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class _MSG(ctypes.Structure):
    _fields_ = (
        ("hWnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _POINT),
    )


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.RegisterClassExW.argtypes = (ctypes.POINTER(_WNDCLASSEXW),)
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
_user32.CreateWindowExW.argtypes = (
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
)
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DefWindowProcW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.GetMessageW.argtypes = (
    ctypes.POINTER(_MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
_user32.GetMessageW.restype = wintypes.BOOL
_user32.TranslateMessage.argtypes = (ctypes.POINTER(_MSG),)
_user32.TranslateMessage.restype = wintypes.BOOL
_user32.DispatchMessageW.argtypes = (ctypes.POINTER(_MSG),)
_user32.DispatchMessageW.restype = ctypes.c_ssize_t
_user32.DestroyWindow.argtypes = (wintypes.HWND,)
_user32.DestroyWindow.restype = wintypes.BOOL
_user32.PostQuitMessage.argtypes = (ctypes.c_int,)
_user32.PostMessageW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_user32.PostMessageW.restype = wintypes.BOOL
_user32.GetCursorPos.argtypes = (ctypes.POINTER(_POINT),)
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.CreatePopupMenu.restype = wintypes.HMENU
_user32.AppendMenuW.argtypes = (
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_size_t,
    wintypes.LPCWSTR,
)
_user32.AppendMenuW.restype = wintypes.BOOL
_user32.TrackPopupMenu.argtypes = (
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.LPVOID,
)
_user32.TrackPopupMenu.restype = wintypes.UINT
_user32.DestroyMenu.argtypes = (wintypes.HMENU,)
_user32.DestroyMenu.restype = wintypes.BOOL
_user32.LoadImageW.argtypes = (
    wintypes.HINSTANCE,
    wintypes.LPCWSTR,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.LoadIconW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR)
_user32.LoadIconW.restype = wintypes.HICON
_user32.DestroyIcon.argtypes = (wintypes.HICON,)
_user32.DestroyIcon.restype = wintypes.BOOL
_user32.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
_user32.RegisterWindowMessageW.restype = wintypes.UINT
_shell32.Shell_NotifyIconW.argtypes = (
    wintypes.DWORD,
    ctypes.POINTER(_NOTIFYICONDATAW),
)
_shell32.Shell_NotifyIconW.restype = wintypes.BOOL
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class TrayIcon:
    """A tray icon whose menu commands are delivered on a thread-safe queue."""

    def __init__(
        self,
        icon_path: Path,
        commands: queue.Queue[str],
        *,
        tooltip: str = "BetterShutup",
    ) -> None:
        self.icon_path = Path(icon_path)
        self.commands = commands
        self.tooltip = tooltip
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._hwnd: int | None = None
        self._icon = 0
        self._owns_icon = False
        self._started = False
        self._stopping = False
        self._wndproc = None
        self._class_name = ""
        self._taskbar_created = 0
        self._icon_data = _NOTIFYICONDATAW()

    @property
    def available(self) -> bool:
        return (
            self._started
            and self._thread is not None
            and self._thread.is_alive()
        )

    def start(self) -> bool:
        if self._thread is not None:
            return self.available
        self._thread = threading.Thread(
            target=self._run,
            name="BetterShutupTray",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(2.0)
        return self._started

    def stop(self) -> None:
        self._stopping = True
        if self._hwnd:
            try:
                _user32.PostMessageW(
                    self._hwnd, _WM_CLOSE, 0, 0
                )
            except Exception:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(1.5)
        self._started = False
        self._thread = None

    # --------------------------------------------------------------- thread
    def _run(self) -> None:
        instance = _kernel32.GetModuleHandleW(None)
        class_name = (
            f"BetterShutupTray-{os.getpid()}-{id(self)}"
        )
        self._class_name = class_name
        self._wndproc = _WNDPROC(self._window_proc)
        window_class = _WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = instance
        window_class.lpszClassName = class_name
        registered = _user32.RegisterClassExW(
            ctypes.byref(window_class)
        )
        if not registered:
            self._ready.set()
            return

        hwnd = _user32.CreateWindowExW(
            0,
            class_name,
            "BetterShutup",
            0,
            0,
            0,
            0,
            0,
            _HWND_MESSAGE,
            None,
            instance,
            None,
        )
        if not hwnd:
            _user32.UnregisterClassW(class_name, instance)
            self._ready.set()
            return

        self._hwnd = int(hwnd)
        self._taskbar_created = _user32.RegisterWindowMessageW(
            "TaskbarCreated"
        )
        if not self._add_icon():
            self._destroy_window()
            self._ready.set()
            return

        self._started = True
        self._ready.set()
        message = _MSG()
        while _user32.GetMessageW(
            ctypes.byref(message), None, 0, 0
        ) > 0:
            _user32.TranslateMessage(ctypes.byref(message))
            _user32.DispatchMessageW(ctypes.byref(message))

        self._remove_icon()
        self._started = False
        if self._class_name:
            _user32.UnregisterClassW(class_name, instance)
            self._class_name = ""

    def _window_proc(
        self,
        hwnd: int,
        message: int,
        wparam: int,
        lparam: int,
    ) -> int:
        if message == _WM_TRAY:
            event = int(lparam) & 0xFFFF
            if event in (_WM_RBUTTONUP, _WM_LBUTTONUP):
                if event == _WM_RBUTTONUP:
                    self._show_menu(hwnd)
                else:
                    self.commands.put("show")
            elif event == _WM_LBUTTONDBLCLK:
                self.commands.put("show")
            return 0
        if message == _WM_COMMAND:
            command = int(wparam) & 0xFFFF
            if command == _MENU_SHOW:
                self.commands.put("show")
            elif command == _MENU_HIDE:
                self.commands.put("hide")
            elif command == _MENU_SETTINGS:
                self.commands.put("settings")
            elif command == _MENU_EXIT:
                self.commands.put("exit")
            return 0
        if message == self._taskbar_created and self._started:
            self._add_icon()
            return 0
        if message == _WM_CLOSE:
            _user32.DestroyWindow(hwnd)
            return 0
        if message == _WM_DESTROY:
            self._remove_icon()
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self, hwnd: int) -> None:
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        try:
            _user32.AppendMenuW(menu, _MF_STRING, _MENU_SHOW, "显示主窗口")
            _user32.AppendMenuW(menu, _MF_STRING, _MENU_HIDE, "隐藏主窗口")
            _user32.AppendMenuW(menu, _MF_STRING, _MENU_SETTINGS, "设置")
            _user32.AppendMenuW(menu, _MF_SEPARATOR, 0, None)
            _user32.AppendMenuW(menu, _MF_STRING, _MENU_EXIT, "退出 BetterShutup")
            point = _POINT()
            if not _user32.GetCursorPos(ctypes.byref(point)):
                return
            _user32.SetForegroundWindow(hwnd)
            command = _user32.TrackPopupMenu(
                menu,
                _TPM_RETURNCMD | _TPM_NONOTIFY | _TPM_RIGHTBUTTON,
                point.x,
                point.y,
                0,
                hwnd,
                None,
            )
            _user32.PostMessageW(hwnd, _WM_NULL, 0, 0)
            if command == _MENU_SHOW:
                self.commands.put("show")
            elif command == _MENU_HIDE:
                self.commands.put("hide")
            elif command == _MENU_SETTINGS:
                self.commands.put("settings")
            elif command == _MENU_EXIT:
                self.commands.put("exit")
        finally:
            _user32.DestroyMenu(menu)

    def _load_icon(self) -> int:
        if self.icon_path.is_file():
            icon = _user32.LoadImageW(
                None,
                str(self.icon_path),
                _IMAGE_ICON,
                0,
                0,
                _LR_LOADFROMFILE | _LR_DEFAULTSIZE,
            )
            if icon:
                self._owns_icon = True
                return int(icon)
        icon = _user32.LoadIconW(
            None,
            ctypes.cast(_IDI_APPLICATION, wintypes.LPCWSTR),
        )
        self._owns_icon = False
        return int(icon or 0)

    def _add_icon(self) -> bool:
        if not self._hwnd:
            return False
        if not self._icon:
            self._icon = self._load_icon()
        if not self._icon:
            return False
        data = self._icon_data
        data.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP | _NIF_SHOWTIP
        data.uCallbackMessage = _WM_TRAY
        data.hIcon = self._icon
        data.szTip = self.tooltip[:127]
        if not _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data)):
            return False
        data.uVersion = _NOTIFYICON_VERSION_3
        _shell32.Shell_NotifyIconW(_NIM_SETVERSION, ctypes.byref(data))
        return True

    def _remove_icon(self) -> None:
        if self._hwnd and self._icon:
            data = self._icon_data
            data.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            data.hWnd = self._hwnd
            data.uID = 1
            _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(data))
        if self._icon and self._owns_icon:
            _user32.DestroyIcon(self._icon)
        self._icon = 0
        self._owns_icon = False

    def _destroy_window(self) -> None:
        if self._hwnd:
            _user32.DestroyWindow(self._hwnd)
            self._hwnd = None
