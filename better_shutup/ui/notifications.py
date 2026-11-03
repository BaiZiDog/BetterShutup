"""Topmost notification cards anchored to the bottom-right of the desktop."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import tkinter as tk
from typing import Callable

from ..core import NoticeKind
from ..sounds import SoundPlayer
from . import theme as colors
from .theme import Theme, work_area

_AUTO_CLOSE_MS = 10_000
_PREVIEW_LIMIT = 180
_DETAIL_LIMIT = 200_000


@dataclass(slots=True)
class NotificationItem:
    kind: NoticeKind
    session_id: str
    session_name: str
    text: str
    title: str | None = None


_INFO_CARD_STYLE = {
    "accent": colors.PRIMARY,
    "soft": colors.PRIMARY_SOFT,
    "sound": "notify",
    "auto": True,
    "button": "关闭",
}

_KIND_STYLE = {
    NoticeKind.COMPLETE: {
        "title": "任务完成",
        "icon": "✓",
        "accent": colors.SUCCESS,
        "soft": colors.SUCCESS_SOFT,
        "sound": "complete",
        "auto": True,
        "button": "关闭",
    },
    NoticeKind.ACTION: {
        "title": "需要操作",
        "icon": "!",
        "accent": colors.WARNING,
        "soft": colors.WARNING_SOFT,
        "sound": "action",
        "auto": False,
        "button": "知道了",
    },
    NoticeKind.ERROR: {
        "title": "错误",
        "icon": "×",
        "accent": colors.DANGER,
        "soft": colors.DANGER_SOFT,
        "sound": "error",
        "auto": False,
        "button": "关闭",
    },
    NoticeKind.NOTIFY: {
        **_INFO_CARD_STYLE,
        "title": "消息",
        "icon": "i",
    },
    NoticeKind.PLAN: {
        **_INFO_CARD_STYLE,
        "title": "计划更新",
        "icon": "≡",
    },
    NoticeKind.STEP_COMPLETE: {
        **_INFO_CARD_STYLE,
        "title": "步骤完成",
        "icon": "✓",
    },
    NoticeKind.PROTOCOL_ERROR: {
        "title": "协议错误",
        "icon": "×",
        "accent": colors.DANGER,
        "soft": colors.DANGER_SOFT,
        "sound": "error",
        "auto": False,
        "button": "关闭",
    },
}


def _short_id(session_id: str, limit: int = 26) -> str:
    if len(session_id) <= limit:
        return session_id
    head = max(6, limit // 2)
    tail = max(4, limit - head - 1)
    return f"{session_id[:head]}…{session_id[-tail:]}"


def _one_line(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


class NotificationManager:
    def __init__(
        self,
        root: tk.Tk,
        theme: Theme,
        sound_player: SoundPlayer | None = None,
        *,
        max_visible: int | None = None,
    ) -> None:
        self.root = root
        self.theme = theme
        self.sound_player = sound_player
        self._active: list[NotificationCard] = []
        self._pending: deque[NotificationItem] = deque()
        if max_visible is None:
            _, top, _, bottom = work_area(root)
            available = max(300, bottom - top)
            by_height = int(
                (available - theme.px(36)) / max(1, theme.px(200))
            )
            max_visible = max(1, min(4, by_height))
        self.max_visible = max_visible
        self._closed = False

    def push(self, item: NotificationItem) -> None:
        if self._closed:
            return
        self._pending.append(item)
        self._fill_slots()

    def close_all(self) -> None:
        self._closed = True
        self._pending.clear()
        for card in list(self._active):
            card.destroy()
        self._active.clear()

    def dismiss_session(
        self,
        session_id: str,
        kind: NoticeKind | None = None,
    ) -> None:
        """Silently close notifications for one session, optionally by kind."""

        if self._closed:
            return
        if self._pending:
            self._pending = deque(
                item
                for item in self._pending
                if not (
                    item.session_id == session_id
                    and (kind is None or item.kind is kind)
                )
            )
        for card in list(self._active):
            if card.item.session_id != session_id:
                continue
            if kind is not None and card.item.kind is not kind:
                continue
            card.close()
        self._layout()

    def _fill_slots(self) -> None:
        while self._pending and len(self._active) < self.max_visible:
            item = self._pending.popleft()
            card = NotificationCard(
                manager=self,
                theme=self.theme,
                item=item,
                on_closed=self._card_closed,
            )
            self._active.append(card)
            self._layout()
            card.show()
            if self.sound_player is not None:
                style = _KIND_STYLE[item.kind]
                self.sound_player.play_kind(str(style["sound"]))
        self._layout()

    def _card_closed(self, card: "NotificationCard") -> None:
        if card in self._active:
            self._active.remove(card)
        self._layout()
        if not self._closed:
            self._fill_slots()

    def _layout(self) -> None:
        if not self._active:
            return
        left, top, right, bottom = work_area(self.root)
        margin = self.theme.px(18)
        gap = self.theme.px(10)
        width = self.theme.width
        x = right - width - margin
        current_bottom = bottom - margin
        for card in reversed(self._active):
            height = card.height
            y = current_bottom - height
            card.set_position(x, max(top + margin, y))
            current_bottom = y - gap


class NotificationCard:
    def __init__(
        self,
        *,
        manager: NotificationManager,
        theme: Theme,
        item: NotificationItem,
        on_closed: Callable[["NotificationCard"], None],
    ) -> None:
        self.manager = manager
        self.theme = theme
        self.item = item
        self._on_closed = on_closed
        self._closed = False
        self._auto_after: str | None = None
        self._details_open = False
        style = _KIND_STYLE[item.kind]
        self._style = style
        self.width = theme.width
        self.height = theme.px(140)

        window = tk.Toplevel(manager.root)
        self.window = window
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=colors.BORDER)
        try:
            window.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        outer = tk.Frame(window, bg=colors.BORDER)
        outer.pack(fill="both", expand=True)
        surface = tk.Frame(outer, bg=colors.SURFACE)
        surface.pack(fill="both", expand=True, padx=1, pady=1)

        accent = tk.Frame(
            surface,
            bg=str(style["accent"]),
            width=self.theme.px(5),
        )
        accent.pack(side="left", fill="y")
        accent.pack_propagate(False)

        content = tk.Frame(surface, bg=colors.SURFACE)
        content.pack(
            side="left",
            fill="both",
            expand=True,
            padx=(self.theme.px(14), self.theme.px(12)),
            pady=(self.theme.px(11), self.theme.px(10)),
        )

        top_row = tk.Frame(content, bg=colors.SURFACE)
        top_row.pack(fill="x")

        icon = tk.Label(
            top_row,
            text=str(style["icon"]),
            font=(self.theme.family, 13, "bold"),
            fg=str(style["accent"]),
            bg=colors.SURFACE,
            width=2,
            anchor="w",
        )
        icon.pack(side="left")

        title = tk.Label(
            top_row,
            text=item.title or str(style["title"]),
            font=self.theme.card_title_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
            anchor="w",
        )
        title.pack(side="left", fill="x", expand=True)

        close = tk.Button(
            top_row,
            text="×",
            command=self.close,
            font=(self.theme.family, 13),
            fg=colors.MUTED,
            bg=colors.SURFACE,
            activeforeground=colors.TEXT,
            activebackground=colors.SURFACE_SUNKEN,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=self.theme.px(4),
            pady=0,
        )
        close.pack(side="right")

        meta_bits: list[str] = []
        if item.session_name:
            display_name = _one_line(item.session_name)
            if len(display_name) > 28:
                display_name = display_name[:27].rstrip() + "…"
            meta_bits.append(display_name)
        elif item.session_id:
            meta_bits.append(_short_id(item.session_id, 24))
        meta_bits.append(datetime.now().strftime("%H:%M"))
        meta = tk.Label(
            content,
            text="  ·  ".join(bit for bit in meta_bits if bit),
            font=self.theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
            anchor="w",
            justify="left",
        )
        meta.pack(fill="x", pady=(0, self.theme.px(6)))

        raw_text = item.text.strip()
        shown_text = raw_text if raw_text else "（无消息内容）"
        truncated = len(shown_text) > _PREVIEW_LIMIT
        if truncated:
            shown_text = shown_text[:_PREVIEW_LIMIT].rstrip() + "…"
        self._full_text = raw_text

        body = tk.Label(
            content,
            text=shown_text,
            font=self.theme.body_font,
            fg=colors.TEXT_SOFT,
            bg=colors.SURFACE,
            anchor="w",
            justify="left",
            wraplength=self.width - self.theme.px(68),
        )
        body.pack(fill="x")

        footer = tk.Frame(content, bg=colors.SURFACE)
        footer.pack(fill="x", pady=(self.theme.px(8), 0))

        if truncated:
            details = tk.Label(
                footer,
                text="查看完整内容",
                font=self.theme.small_font,
                fg=colors.PRIMARY,
                bg=colors.SURFACE,
                cursor="hand2",
            )
            details.pack(side="left")
            details.bind("<Button-1>", lambda _event: self.open_details())
        else:
            hint = tk.Label(
                footer,
                text="等待确认" if not bool(style["auto"]) else "稍后自动关闭",
                font=self.theme.small_font,
                fg=colors.MUTED,
                bg=colors.SURFACE,
            )
            hint.pack(side="left")

        action = tk.Button(
            footer,
            text=str(style["button"]),
            command=self.close,
            font=self.theme.small_bold,
            fg=str(style["accent"]),
            bg=colors.SURFACE,
            activeforeground=str(style["accent"]),
            activebackground=colors.SURFACE_SUNKEN,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=self.theme.px(7),
            pady=self.theme.px(3),
        )
        action.pack(side="right")

        window.bind("<Escape>", lambda _event: self.close())
        window.update_idletasks()
        self.height = max(self.theme.px(128), window.winfo_reqheight())

    def show(self) -> None:
        if self._closed:
            return
        self.window.deiconify()
        self.window.attributes("-topmost", True)
        self.window.lift()
        if bool(self._style["auto"]):
            self._schedule_auto_close(_AUTO_CLOSE_MS)

    def set_position(self, x: int, y: int) -> None:
        if self._closed:
            return
        self.window.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def _schedule_auto_close(self, delay_ms: int) -> None:
        self._cancel_auto_close()
        if self._closed or self._details_open:
            return
        self._auto_after = self.window.after(delay_ms, self.close)

    def _cancel_auto_close(self) -> None:
        if self._auto_after is not None:
            try:
                self.window.after_cancel(self._auto_after)
            except tk.TclError:
                pass
            self._auto_after = None

    def open_details(self) -> None:
        if self._closed:
            return
        self._cancel_auto_close()
        self._details_open = True

        def done() -> None:
            self._details_open = False
            if not self._closed and bool(self._style["auto"]):
                self._schedule_auto_close(5_000)

        DetailsWindow(
            parent=self.manager.root,
            theme=self.theme,
            title=self.item.title or str(self._style["title"]),
            text=self._full_text or "（无消息内容）",
            on_close=done,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_auto_close()
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        finally:
            self._on_closed(self)

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_auto_close()
        try:
            self.window.destroy()
        except tk.TclError:
            pass


class DetailsWindow:
    def __init__(
        self,
        *,
        parent: tk.Tk,
        theme: Theme,
        title: str,
        text: str,
        on_close: Callable[[], None],
    ) -> None:
        self.parent = parent
        self.theme = theme
        self._on_close = on_close

        window = tk.Toplevel(parent)
        self.window = window
        window.title(f"BetterShutup · {title}")
        window.configure(bg=colors.BG)
        window.attributes("-topmost", True)
        window.transient(parent)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _event: self.close())

        header = tk.Frame(window, bg=colors.SURFACE)
        header.pack(fill="x")
        tk.Label(
            header,
            text=title,
            font=theme.section_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
            anchor="w",
        ).pack(
            side="left",
            padx=(theme.px(18), theme.px(8)),
            pady=(theme.px(14), theme.px(10)),
        )
        tk.Frame(window, bg=colors.BORDER, height=1).pack(fill="x")

        body = tk.Frame(window, bg=colors.SURFACE)
        body.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(body, orient="vertical")
        text_widget = tk.Text(
            body,
            wrap="word",
            font=theme.body_font,
            fg=colors.TEXT_SOFT,
            bg=colors.SURFACE,
            relief="flat",
            borderwidth=0,
            padx=theme.px(18),
            pady=theme.px(12),
            yscrollcommand=scrollbar.set,
        )
        scrollbar.configure(command=text_widget.yview)
        scrollbar.pack(side="right", fill="y")
        text_widget.pack(side="left", fill="both", expand=True)
        display_text = text
        if len(display_text) > _DETAIL_LIMIT:
            display_text = (
                display_text[:_DETAIL_LIMIT]
                + f"\n\n[内容过长，仅显示前 {_DETAIL_LIMIT} 个字符]"
            )
        text_widget.insert("1.0", display_text)
        text_widget.configure(state="disabled")

        controls = tk.Frame(window, bg=colors.BG)
        controls.pack(fill="x")
        tk.Button(
            controls,
            text="关闭",
            command=self.close,
            font=theme.body_bold,
            fg=colors.WHITE,
            bg=colors.PRIMARY,
            activeforeground=colors.WHITE,
            activebackground=colors.PRIMARY_DARK,
            relief="flat",
            borderwidth=0,
            padx=theme.px(18),
            pady=theme.px(6),
            cursor="hand2",
        ).pack(side="right", padx=theme.px(18), pady=theme.px(12))

        width = theme.px(650)
        height = theme.px(430)
        theme.center(window, width, height)
        window.lift()
        window.focus_set()

    def close(self) -> None:
        try:
            self.window.destroy()
        finally:
            self._on_close()
