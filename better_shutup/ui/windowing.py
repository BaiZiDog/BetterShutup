"""Shared borderless-window and fullscreen helpers.

Tk on Windows rejects ``-fullscreen`` on an override-redirect window, so
fullscreen is implemented as a borderless, topmost, screen-sized geometry.
The previous geometry and topmost state are restored when leaving fullscreen.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk

_GWL_EXSTYLE = -20
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_TOOLWINDOW = 0x00000080
_WM_SETICON = 0x0080
_ICON_SMALL = 0
_ICON_BIG = 1
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_LR_DEFAULTSIZE = 0x0040
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetParent.argtypes = (wintypes.HWND,)
_user32.GetParent.restype = wintypes.HWND
_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = (
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_long,
)
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.SetWindowPos.argtypes = (
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
)
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.LoadImageW.argtypes = (
    wintypes.HINSTANCE,
    wintypes.LPCWSTR,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.SendMessageW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_user32.SendMessageW.restype = wintypes.LPARAM

_TEXT_INPUT_CLASSES = {
    "Entry",
    "TEntry",
    "Spinbox",
    "TSpinbox",
    "TCombobox",
}

_FULLSCREEN_FLAG = "_better_shutup_fullscreen"
_NORMAL_GEOMETRY = "_better_shutup_normal_geometry"
_NORMAL_TOPMOST = "_better_shutup_normal_topmost"


def make_borderless(window: tk.Misc) -> None:
    """Remove the native title bar and border without forcing fullscreen."""

    try:
        window.overrideredirect(True)
    except tk.TclError:
        pass


def ensure_taskbar_icon(window: tk.Misc, icon_path: str | None = None) -> None:
    """Force a borderless top-level window to own a taskbar button and icon.

    Tk's override-redirect windows normally disappear from the taskbar.  The
    native WS_EX_APPWINDOW style restores the button; an explicit WM_SETICON
    keeps the provided icon visible on it.
    """

    try:
        window.update_idletasks()
        hwnd = int(window.winfo_id())
        parent = _user32.GetParent(hwnd)
        if parent:
            hwnd = int(parent)
        style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        style = (style | _WS_EX_APPWINDOW) & ~_WS_EX_TOOLWINDOW
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style)
        _user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE
            | _SWP_NOSIZE
            | _SWP_NOZORDER
            | _SWP_NOACTIVATE
            | _SWP_FRAMECHANGED,
        )
        if icon_path:
            icon = _user32.LoadImageW(
                None,
                icon_path,
                _IMAGE_ICON,
                0,
                0,
                _LR_LOADFROMFILE | _LR_DEFAULTSIZE,
            )
            if icon:
                _user32.SendMessageW(hwnd, _WM_SETICON, _ICON_SMALL, icon)
                _user32.SendMessageW(hwnd, _WM_SETICON, _ICON_BIG, icon)
                # Keep the HICON alive for as long as the window exists.
                setattr(window, "_better_shutup_taskbar_hicon", icon)
    except Exception:
        # Taskbar decoration is best-effort; never break window creation.
        pass


def enable_drag(window: tk.Misc, *handles: tk.Misc) -> None:
    """Allow a borderless window to be moved by dragging one of its handles."""

    state = {"active": False, "x": 0, "y": 0, "px": 0, "py": 0}

    def press(event: tk.Event) -> None:
        if is_fullscreen(window):
            return
        state["active"] = True
        state["px"] = event.x_root
        state["py"] = event.y_root
        state["x"] = window.winfo_x()
        state["y"] = window.winfo_y()

    def motion(event: tk.Event) -> None:
        if not state["active"] or is_fullscreen(window):
            return
        dx = event.x_root - state["px"]
        dy = event.y_root - state["py"]
        try:
            window.geometry(f"+{state['x'] + dx}+{state['y'] + dy}")
        except tk.TclError:
            state["active"] = False

    def release(_event: tk.Event) -> None:
        state["active"] = False

    for handle in handles:
        handle.bind("<ButtonPress-1>", press, add="+")
        handle.bind("<B1-Motion>", motion, add="+")
        handle.bind("<ButtonRelease-1>", release, add="+")


def enable_fullscreen_toggle(window: tk.Misc) -> None:
    """Toggle borderless fullscreen on F when focus is not a text input."""

    def toggle(event: tk.Event) -> str | None:
        if event.keysym.lower() != "f":
            return None
        # Ignore Ctrl/Alt shortcuts; plain Shift+F is still the F key.
        if event.state & (0x4 | 0x8 | 0x20000):
            return None
        focus = window.focus_get()
        if focus is not None:
            try:
                if focus.winfo_toplevel() is not window:
                    return None
                if focus.winfo_class() in _TEXT_INPUT_CLASSES:
                    return None
            except tk.TclError:
                pass
        set_fullscreen(window, not is_fullscreen(window))
        return "break"

    window.bind("<KeyPress>", toggle, add="+")


def force_fullscreen(window: tk.Misc) -> None:
    """Put a borderless window into screen-sized topmost fullscreen."""

    set_fullscreen(window, True)


def set_fullscreen(window: tk.Misc, enabled: bool) -> None:
    if enabled == is_fullscreen(window):
        return

    if enabled:
        try:
            window.update_idletasks()
            setattr(window, _NORMAL_GEOMETRY, window.geometry())
            setattr(
                window,
                _NORMAL_TOPMOST,
                bool(window.attributes("-topmost")),
            )
            window.geometry(
                f"{window.winfo_screenwidth()}x"
                f"{window.winfo_screenheight()}+0+0"
            )
            window.attributes("-topmost", True)
            window.lift()
            setattr(window, _FULLSCREEN_FLAG, True)
        except tk.TclError:
            return
    else:
        geometry = getattr(window, _NORMAL_GEOMETRY, None)
        topmost = bool(getattr(window, _NORMAL_TOPMOST, False))
        try:
            if geometry:
                window.geometry(geometry)
            window.attributes("-topmost", topmost)
            setattr(window, _FULLSCREEN_FLAG, False)
        except tk.TclError:
            return

    try:
        window.update_idletasks()
    except tk.TclError:
        pass


def is_fullscreen(window: tk.Misc) -> bool:
    return bool(getattr(window, _FULLSCREEN_FLAG, False))
