"""Shared visual theme, DPI helpers, and small UI utilities."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

BG = "#EEF2F6"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F7F9FC"
SURFACE_SUNKEN = "#F1F4F8"
BORDER = "#DFE5ED"
TEXT = "#172033"
TEXT_SOFT = "#354155"
MUTED = "#667085"
PRIMARY = "#2463EB"
PRIMARY_DARK = "#1D4ED8"
PRIMARY_SOFT = "#E8F0FE"
SUCCESS = "#15803D"
SUCCESS_SOFT = "#EAF7EF"
WARNING = "#B45309"
WARNING_SOFT = "#FFF7E6"
DANGER = "#B42318"
DANGER_SOFT = "#FEECEB"
HEADER_BG = "#0F172A"
HEADER_BG_ALT = "#1E293B"
HEADER_TEXT = "#F8FAFC"
HEADER_MUTED = "#94A3B8"
WHITE = "#FFFFFF"
DISABLED = "#AAB4C3"

_SPI_GETWORKAREA = 0x0030
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

_user32.GetDC.argtypes = (wintypes.HWND,)
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
_user32.ReleaseDC.restype = ctypes.c_int
_gdi32.GetDeviceCaps.argtypes = (wintypes.HDC, ctypes.c_int)
_gdi32.GetDeviceCaps.restype = ctypes.c_int


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def enable_dpi_awareness() -> None:
    """Enable system DPI awareness before creating the Tk root."""

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass
    try:
        _user32.SetProcessDPIAware()
    except Exception:
        pass


def system_dpi() -> int:
    try:
        return int(_user32.GetDpiForSystem())
    except Exception:
        pass
    try:
        hdc = _user32.GetDC(None)
        # LOGPIXELSX
        dpi = _gdi32.GetDeviceCaps(hdc, 88)
        if hdc:
            _user32.ReleaseDC(None, hdc)
        if dpi:
            return int(dpi)
    except Exception:
        pass
    return 96


def work_area(root: tk.Misc) -> tuple[int, int, int, int]:
    rect = _RECT()
    try:
        ok = _user32.SystemParametersInfoW(
            _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        if ok and rect.right > rect.left and rect.bottom > rect.top:
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class Theme:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.dpi = system_dpi()
        self.scale = max(1.0, self.dpi / 96.0)
        self.width = int(round(430 * self.scale))
        try:
            root.tk.call("tk", "scaling", self.dpi / 72.0)
        except tk.TclError:
            pass
        try:
            families = set(tkfont.families(root))
        except tk.TclError:
            families = set()
        self.family = self._pick(
            families,
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Segoe UI",
            "Arial",
        )
        self.mono_family = self._pick(
            families,
            "Cascadia Mono",
            "Consolas",
            "Courier New",
        )
        self._configure_named_fonts()
        self.body_font = (self.family, 10)
        self.body_bold = (self.family, 10, "bold")
        self.small_font = (self.family, 9)
        self.small_bold = (self.family, 9, "bold")
        self.title_font = (self.family, 20, "bold")
        self.subtitle_font = (self.family, 10)
        self.section_font = (self.family, 11, "bold")
        self.timer_font = (self.family, 40, "bold")
        self.card_title_font = (self.family, 11, "bold")
        self.mono_small = (self.mono_family, 9)
        self._style = ttk.Style(root)
        self._configure_ttk()

    @staticmethod
    def _pick(families: set[str], *candidates: str) -> str:
        for candidate in candidates:
            if candidate in families:
                return candidate
        return candidates[-1]

    def px(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _configure_named_fonts(self) -> None:
        for name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkMenuFont",
            "TkHeadingFont",
        ):
            try:
                tkfont.nametofont(name).configure(
                    family=self.family, size=10
                )
            except tk.TclError:
                pass
        try:
            tkfont.nametofont("TkFixedFont").configure(
                family=self.mono_family, size=9
            )
        except tk.TclError:
            pass

    def _configure_ttk(self) -> None:
        style = self._style
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BG)
        style.configure(
            "TLabel",
            background=BG,
            foreground=TEXT,
            font=self.body_font,
        )

        button_common = {
            "borderwidth": 0,
            "relief": "flat",
            "focusthickness": 0,
            "font": self.body_bold,
            "padding": (self.px(13), self.px(7)),
        }
        style.configure(
            "Primary.TButton",
            background=PRIMARY,
            foreground=WHITE,
            **button_common,
        )
        style.map(
            "Primary.TButton",
            background=[
                ("disabled", "#AFC4E8"),
                ("pressed", PRIMARY_DARK),
                ("active", PRIMARY_DARK),
            ],
            foreground=[("disabled", "#F4F7FC")],
        )
        style.configure(
            "Secondary.TButton",
            background=SURFACE_SUNKEN,
            foreground=TEXT_SOFT,
            **button_common,
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("disabled", "#F1F4F8"),
                ("pressed", "#E6EBF2"),
                ("active", "#E9EEF5"),
            ],
            foreground=[("disabled", DISABLED)],
        )
        style.configure(
            "Danger.TButton",
            background=DANGER_SOFT,
            foreground=DANGER,
            **button_common,
        )
        style.map(
            "Danger.TButton",
            background=[
                ("disabled", "#F7F1F0"),
                ("pressed", "#FADBD8"),
                ("active", "#FBDDDA"),
            ],
            foreground=[("disabled", "#C9A5A1")],
        )
        style.configure(
            "Header.TButton",
            background=HEADER_BG_ALT,
            foreground=HEADER_TEXT,
            borderwidth=0,
            relief="flat",
            focusthickness=0,
            font=self.small_bold,
            padding=(self.px(12), self.px(6)),
        )
        style.map(
            "Header.TButton",
            background=[("active", "#334155"), ("pressed", "#0B1220")],
            foreground=[("active", WHITE)],
        )

        style.configure(
            "Treeview",
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=TEXT_SOFT,
            borderwidth=0,
            relief="flat",
            rowheight=self.px(31),
            font=self.body_font,
        )
        style.configure(
            "Treeview.Heading",
            background=SURFACE_ALT,
            foreground=MUTED,
            borderwidth=0,
            relief="flat",
            font=self.small_bold,
            padding=(self.px(8), self.px(8)),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", SURFACE_ALT)],
            foreground=[("active", TEXT_SOFT)],
        )
        style.map(
            "Treeview",
            background=[("selected", PRIMARY_SOFT)],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=SURFACE_SUNKEN,
            troughcolor=SURFACE,
            borderwidth=0,
            arrowsize=self.px(12),
            width=self.px(10),
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#CBD5E1"), ("pressed", "#B8C4D4")],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=SURFACE,
            background=SURFACE,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            arrowcolor=TEXT_SOFT,
            padding=(self.px(7), self.px(4)),
            font=self.body_font,
        )
    def center(
        self, window: tk.Misc, width: int, height: int, *, top_bias: float = 0.0
    ) -> None:
        left, top, right, bottom = work_area(self.root)
        available_width = right - left
        available_height = bottom - top
        width = min(width, max(self.px(320), available_width - self.px(24)))
        height = min(height, max(self.px(200), available_height - self.px(24)))
        x = left + max(0, (available_width - width) // 2)
        y = top + max(0, (available_height - height) // 2)
        y = int(y + height * top_bias)
        window.geometry(f"{width}x{height}+{x}+{y}")
