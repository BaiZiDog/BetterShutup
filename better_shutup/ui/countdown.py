"""Topmost shutdown countdown window."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from . import theme as colors
from .theme import Theme


class CountdownWindow:
    def __init__(
        self,
        *,
        parent: tk.Tk,
        theme: Theme,
        on_cancel: Callable[[], None],
        dry_run: bool,
    ) -> None:
        self.parent = parent
        self.theme = theme
        self._on_cancel = on_cancel
        self._closed = False

        window = tk.Toplevel(parent)
        self.window = window
        window.title("BetterShutup · 计划关机")
        window.configure(bg=colors.BG)
        window.attributes("-topmost", True)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self._cancel)

        card = tk.Frame(
            window,
            bg=colors.SURFACE,
            highlightbackground=colors.BORDER,
            highlightthickness=1,
        )
        card.pack(fill="both", expand=True, padx=theme.px(16), pady=theme.px(16))

        header = tk.Frame(card, bg=colors.DANGER_SOFT)
        header.pack(fill="x")
        badge = tk.Label(
            header,
            text="计划关机",
            font=theme.small_bold,
            fg=colors.DANGER,
            bg=colors.DANGER_SOFT,
            padx=theme.px(14),
            pady=theme.px(6),
        )
        badge.pack(side="left")
        if dry_run:
            tk.Label(
                header,
                text="演练模式 · 不会真正关机",
                font=theme.small_font,
                fg=colors.WARNING,
                bg=colors.DANGER_SOFT,
                padx=theme.px(14),
            ).pack(side="right")

        content = tk.Frame(card, bg=colors.SURFACE)
        content.pack(fill="both", expand=True, padx=theme.px(24), pady=(theme.px(16), theme.px(18)))

        tk.Label(
            content,
            text="全部已注册会话均已完成",
            font=theme.section_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
            anchor="w",
        ).pack(fill="x")

        self.time_label = tk.Label(
            content,
            text="00:00",
            font=theme.timer_font,
            fg=colors.DANGER,
            bg=colors.SURFACE,
            anchor="w",
        )
        self.time_label.pack(fill="x", pady=(theme.px(2), theme.px(2)))

        self.detail_label = tk.Label(
            content,
            text="倒计时结束后将关闭电脑，期间可随时取消。",
            font=theme.body_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
            anchor="w",
            justify="left",
            wraplength=theme.px(380),
        )
        self.detail_label.pack(fill="x")

        buttons = tk.Frame(content, bg=colors.SURFACE)
        buttons.pack(fill="x", pady=(theme.px(16), 0))
        self.cancel_button = tk.Button(
            buttons,
            text="取消计划关机",
            command=self._cancel,
            font=theme.body_bold,
            fg=colors.DANGER,
            bg=colors.DANGER_SOFT,
            activeforeground=colors.DANGER,
            activebackground="#FADBD8",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=theme.px(18),
            pady=theme.px(9),
        )
        self.cancel_button.pack(side="left")

        theme.center(window, theme.px(470), theme.px(290), top_bias=-0.10)
        window.lift()
        window.attributes("-topmost", True)

    def update_remaining(self, seconds: int) -> None:
        if self._closed:
            return
        seconds = max(0, int(seconds))
        minutes, remainder = divmod(seconds, 60)
        self.time_label.configure(text=f"{minutes:02d}:{remainder:02d}")
        if seconds <= 10:
            self.time_label.configure(fg=colors.DANGER)
            self.detail_label.configure(
                text="即将关机。点击下方按钮可取消。",
                fg=colors.DANGER,
            )
        else:
            self.time_label.configure(fg=colors.WARNING)
            self.detail_label.configure(
                text="倒计时结束后将关闭电脑，期间可随时取消。",
                fg=colors.MUTED,
            )

    def set_firing(self) -> None:
        if self._closed:
            return
        self.time_label.configure(text="关机中", fg=colors.DANGER)
        self.detail_label.configure(
            text="正在向 Windows 发送关机请求…", fg=colors.DANGER
        )
        self.cancel_button.configure(
            state="disabled",
            fg=colors.DISABLED,
            activeforeground=colors.DISABLED,
            disabledforeground=colors.DISABLED,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def _cancel(self) -> None:
        if self._closed:
            return
        self._on_cancel()
