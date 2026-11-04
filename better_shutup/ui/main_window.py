"""Main BetterShutup window."""

from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import ttk
from typing import Callable, Sequence

from ..core import (
    MAX_COUNTDOWN_SECONDS,
    MIN_COUNTDOWN_SECONDS,
    Session,
)
from ..protocol import Status
from . import theme as colors
from .theme import Theme, work_area

_LEVEL_COLORS = {
    "info": colors.TEXT_SOFT,
    "success": colors.SUCCESS,
    "warning": colors.WARNING,
    "error": colors.DANGER,
}


def _single_line(value: str, limit: int = 90) -> str:
    text = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _clock_from_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes:02d}:{remainder:02d}"


class MainWindow:
    def __init__(
        self,
        root: tk.Tk,
        theme: Theme,
        *,
        pipe_name: str,
        dry_run: bool,
        countdown_seconds: int,
        on_toggle_plan: Callable[[], None],
        on_remove_selected: Callable[[str], None],
        on_clear_completed: Callable[[], None],
        on_settings: Callable[[], None],
        on_close: Callable[[], None],
        on_countdown_changed: Callable[[int], None],
    ) -> None:
        self.root = root
        self.theme = theme
        self.pipe_name = pipe_name
        self.dry_run = dry_run
        self._on_toggle_plan = on_toggle_plan
        self._on_remove_selected = on_remove_selected
        self._on_clear_completed = on_clear_completed
        self._on_settings = on_settings
        self._on_close = on_close
        self._on_countdown_changed = on_countdown_changed
        self._countdown_seconds = countdown_seconds
        self._selected_session_id: str | None = None
        self._agent_plan_session_id: str | None = None
        self._agent_plan_step_texts: dict[str, str] = {}
        self._tree_map: dict[str, str] = {}
        self._sessions: tuple[Session, ...] = ()
        self._planned = False
        self._remaining: int | None = None
        self._firing = False

        root.title("BetterShutup")
        root.configure(bg=colors.BG)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.option_add("*TCombobox*Listbox.font", theme.body_font)
        root.option_add("*tearOff", False)

        self._build()
        width = theme.px(1080)
        height = theme.px(760)
        left, top, right, bottom = work_area(root)
        available_w = max(theme.px(640), right - left - theme.px(32))
        available_h = max(theme.px(500), bottom - top - theme.px(32))
        width = min(width, available_w)
        height = min(height, available_h)
        root.minsize(
            min(theme.px(880), available_w),
            min(theme.px(580), available_h),
        )
        theme.center(root, width, height)

    # ------------------------------------------------------------------ build
    def _card(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=colors.SURFACE,
            highlightbackground=colors.BORDER,
            highlightthickness=1,
        )

    def _build(self) -> None:
        theme = self.theme
        self._build_header()

        body = tk.Frame(self.root, bg=colors.BG)
        body.pack(fill="both", expand=True, padx=theme.px(20), pady=theme.px(16))

        self._build_plan_card(body)
        self._build_sessions_card(body)
        self._build_log_card(body)

    def _build_header(self) -> None:
        theme = self.theme
        header = tk.Frame(self.root, bg=colors.HEADER_BG)
        header.pack(fill="x")

        left = tk.Frame(header, bg=colors.HEADER_BG)
        left.pack(side="left", padx=theme.px(24), pady=theme.px(16))
        tk.Label(
            left,
            text="BetterShutup",
            font=theme.title_font,
            fg=colors.HEADER_TEXT,
            bg=colors.HEADER_BG,
            anchor="w",
        ).pack(anchor="w")
        subtitle = tk.Frame(left, bg=colors.HEADER_BG)
        subtitle.pack(anchor="w", pady=(theme.px(2), 0))
        tk.Label(
            subtitle,
            text="多 Agent 关机协同",
            font=theme.subtitle_font,
            fg=colors.HEADER_MUTED,
            bg=colors.HEADER_BG,
        ).pack(side="left")
        if self.dry_run:
            tk.Label(
                subtitle,
                text="演练模式",
                font=theme.small_bold,
                fg="#FDE68A",
                bg="#3B2F14",
                padx=theme.px(7),
                pady=theme.px(1),
            ).pack(side="left", padx=(theme.px(10), 0))

        right = tk.Frame(header, bg=colors.HEADER_BG)
        right.pack(side="right", padx=theme.px(24), pady=theme.px(16))

        top_right = tk.Frame(right, bg=colors.HEADER_BG)
        top_right.pack(anchor="e")

        status = tk.Frame(top_right, bg=colors.HEADER_BG)
        status.pack(side="left")
        dot = tk.Canvas(
            status,
            width=theme.px(12),
            height=theme.px(12),
            bg=colors.HEADER_BG,
            highlightthickness=0,
        )
        dot.pack(side="left", padx=(0, theme.px(6)))
        self._status_dot = dot
        self._status_dot_id = dot.create_oval(
            theme.px(2),
            theme.px(2),
            theme.px(10),
            theme.px(10),
            fill=colors.SUCCESS,
            outline="",
        )
        self._status_label = tk.Label(
            status,
            text="监听中",
            font=theme.small_bold,
            fg=colors.HEADER_TEXT,
            bg=colors.HEADER_BG,
        )
        self._status_label.pack(side="left")

        settings_button = ttk.Button(
            top_right,
            text="提示音设置",
            style="Header.TButton",
            command=self._on_settings,
        )
        settings_button.pack(side="left", padx=(theme.px(16), 0))

        self._pipe_label = tk.Label(
            right,
            text=self.pipe_name,
            font=theme.mono_small,
            fg=colors.HEADER_MUTED,
            bg=colors.HEADER_BG,
            anchor="e",
        )
        self._pipe_label.pack(anchor="e", pady=(theme.px(4), 0))

    def _build_plan_card(self, parent: tk.Misc) -> None:
        theme = self.theme
        card = self._card(parent)
        card.pack(fill="x")

        inner = tk.Frame(card, bg=colors.SURFACE)
        inner.pack(fill="x", padx=theme.px(18), pady=theme.px(14))
        inner.grid_columnconfigure(0, weight=1)

        left = tk.Frame(inner, bg=colors.SURFACE)
        left.grid(row=0, column=0, sticky="nsew")
        tk.Label(
            left,
            text="计划关机",
            font=theme.section_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
            anchor="w",
        ).pack(anchor="w")
        self.plan_status = tk.Label(
            left,
            text="未开启",
            font=(theme.family, 13, "bold"),
            fg=colors.MUTED,
            bg=colors.SURFACE,
            anchor="w",
        )
        self.plan_status.pack(anchor="w", pady=(theme.px(3), theme.px(2)))
        self.plan_hint = tk.Label(
            left,
            text="开启后，全部已注册会话完成时自动关机。",
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
            anchor="w",
        )
        self.plan_hint.pack(anchor="w")

        controls = tk.Frame(inner, bg=colors.SURFACE)
        controls.grid(row=0, column=1, sticky="e", padx=(theme.px(20), 0))

        countdown_row = tk.Frame(controls, bg=colors.SURFACE)
        countdown_row.pack(anchor="e")
        tk.Label(
            countdown_row,
            text="倒计时",
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
        ).pack(side="left")
        self.countdown_var = tk.StringVar(value=str(self._countdown_seconds))
        self.countdown_spin = ttk.Spinbox(
            countdown_row,
            from_=MIN_COUNTDOWN_SECONDS,
            to=MAX_COUNTDOWN_SECONDS,
            increment=5,
            width=6,
            textvariable=self.countdown_var,
            font=theme.body_font,
            command=self._commit_countdown,
            justify="center",
        )
        self.countdown_spin.pack(side="left", padx=(theme.px(8), theme.px(6)))
        tk.Label(
            countdown_row,
            text="秒",
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
        ).pack(side="left")
        self.plan_button = ttk.Button(
            controls,
            text="开启计划关机",
            style="Primary.TButton",
            command=self._on_toggle_plan,
        )
        self.plan_button.pack(anchor="e", pady=(theme.px(9), 0))
        self.countdown_spin.bind("<Return>", self._commit_countdown_event)
        self.countdown_spin.bind("<FocusOut>", self._commit_countdown_event)

    def _build_sessions_card(self, parent: tk.Misc) -> None:
        theme = self.theme
        card = self._card(parent)
        card.pack(fill="both", expand=True, pady=(theme.px(14), 0))

        self._sessions_view = tk.Frame(card, bg=colors.SURFACE)
        self._sessions_view.pack(fill="both", expand=True)

        header = tk.Frame(self._sessions_view, bg=colors.SURFACE)
        header.pack(fill="x", padx=theme.px(16), pady=(theme.px(12), theme.px(8)))
        self.session_title = tk.Label(
            header,
            text="会话",
            font=theme.section_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
        )
        self.session_title.pack(side="left")
        self.session_count = tk.Label(
            header,
            text="0 个",
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
        )
        self.session_count.pack(side="left", padx=(theme.px(8), 0))
        tk.Label(
            header,
            text="单击会话查看计划",
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
        ).pack(side="left", padx=(theme.px(10), 0))

        self.remove_button = ttk.Button(
            header,
            text="移除选中",
            style="Secondary.TButton",
            command=self._remove_selected,
        )
        self.remove_button.pack(side="right")
        self.clear_button = ttk.Button(
            header,
            text="清除已完成",
            style="Secondary.TButton",
            command=self._on_clear_completed,
        )
        self.clear_button.pack(side="right", padx=(0, theme.px(8)))

        tree_wrap = tk.Frame(self._sessions_view, bg=colors.SURFACE)
        tree_wrap.pack(fill="both", expand=True, padx=theme.px(12), pady=(0, theme.px(12)))

        columns = ("name", "id", "state", "plan", "latest")
        self.tree = ttk.Treeview(
            tree_wrap,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=7,
        )
        self.tree.heading("name", text="会话名称", anchor="w")
        self.tree.heading("id", text="会话 ID", anchor="w")
        self.tree.heading("state", text="状态", anchor="w")
        self.tree.heading("plan", text="计划", anchor="center")
        self.tree.heading("latest", text="最近消息", anchor="w")
        self.tree.column("name", width=theme.px(170), minwidth=theme.px(100), stretch=False)
        self.tree.column("id", width=theme.px(210), minwidth=theme.px(120), stretch=False)
        self.tree.column("state", width=theme.px(140), minwidth=theme.px(95), stretch=False)
        self.tree.column("plan", width=theme.px(70), minwidth=theme.px(55), stretch=False, anchor="center")
        self.tree.column("latest", width=theme.px(300), minwidth=theme.px(160), stretch=True)
        self.tree.tag_configure("active", foreground=colors.TEXT_SOFT)
        self.tree.tag_configure("completed", foreground=colors.SUCCESS)
        self.tree.tag_configure("action", foreground=colors.WARNING)
        self.tree.tag_configure("error", foreground=colors.DANGER)
        scrollbar = ttk.Scrollbar(
            tree_wrap,
            orient="vertical",
            command=self.tree.yview,
            style="Vertical.TScrollbar",
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

        self.empty_label = tk.Label(
            tree_wrap,
            text="暂无会话。Agent 通过命名管道注册后会显示在这里。",
            font=theme.body_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
        )

        self._build_agent_plan_view(card)

    def _build_agent_plan_view(self, card: tk.Misc) -> None:
        theme = self.theme
        self._agent_plan_view = tk.Frame(card, bg=colors.SURFACE)

        header = tk.Frame(self._agent_plan_view, bg=colors.SURFACE)
        header.pack(fill="x", padx=theme.px(16), pady=(theme.px(12), theme.px(8)))
        ttk.Button(
            header,
            text="← 返回会话",
            style="Secondary.TButton",
            command=self._show_sessions_view,
        ).pack(side="left")
        self.agent_plan_title_label = tk.Label(
            header,
            text="执行计划",
            font=theme.section_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
        )
        self.agent_plan_title_label.pack(side="left", padx=(theme.px(12), 0))
        self.agent_plan_progress_label = tk.Label(
            header,
            text="",
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
        )
        self.agent_plan_progress_label.pack(side="left", padx=(theme.px(10), 0))
        self.agent_plan_session_label = tk.Label(
            header,
            text="",
            font=theme.mono_small,
            fg=colors.MUTED,
            bg=colors.SURFACE,
            anchor="e",
        )
        self.agent_plan_session_label.pack(side="right")

        plan_wrap = tk.Frame(self._agent_plan_view, bg=colors.SURFACE)
        plan_wrap.pack(
            fill="both",
            expand=True,
            padx=theme.px(12),
            pady=(0, theme.px(8)),
        )

        columns = ("index", "step", "state")
        self.agent_plan_tree = ttk.Treeview(
            plan_wrap,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=8,
        )
        self.agent_plan_tree.heading("index", text="索引", anchor="center")
        self.agent_plan_tree.heading("step", text="步骤内容", anchor="w")
        self.agent_plan_tree.heading("state", text="状态", anchor="w")
        self.agent_plan_tree.column(
            "index", width=theme.px(70), minwidth=theme.px(55), stretch=False, anchor="center"
        )
        self.agent_plan_tree.column(
            "step", width=theme.px(660), minwidth=theme.px(240), stretch=True
        )
        self.agent_plan_tree.column(
            "state", width=theme.px(100), minwidth=theme.px(80), stretch=False
        )
        self.agent_plan_tree.tag_configure("completed", foreground=colors.SUCCESS)
        self.agent_plan_tree.tag_configure("pending", foreground=colors.TEXT_SOFT)
        plan_scrollbar = ttk.Scrollbar(
            plan_wrap,
            orient="vertical",
            command=self.agent_plan_tree.yview,
            style="Vertical.TScrollbar",
        )
        self.agent_plan_tree.configure(yscrollcommand=plan_scrollbar.set)
        plan_scrollbar.pack(side="right", fill="y")
        self.agent_plan_tree.pack(side="left", fill="both", expand=True)
        self.agent_plan_tree.bind("<<TreeviewSelect>>", self._on_agent_plan_select)

        self.agent_plan_empty_label = tk.Label(
            plan_wrap,
            text="该会话尚未上报计划。Agent 可通过 0110 上报或更新计划。",
            font=theme.body_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
        )

        self.agent_plan_detail = tk.Label(
            self._agent_plan_view,
            text="选择步骤可查看完整内容。",
            font=theme.small_font,
            fg=colors.TEXT_SOFT,
            bg=colors.SURFACE_ALT,
            anchor="w",
            justify="left",
            wraplength=theme.px(820),
            padx=theme.px(10),
            pady=theme.px(7),
        )
        self.agent_plan_detail.pack(fill="x", padx=theme.px(12), pady=(0, theme.px(12)))

    def _build_log_card(self, parent: tk.Misc) -> None:
        theme = self.theme
        card = self._card(parent)
        card.pack(fill="x", pady=(theme.px(14), 0))

        header = tk.Frame(card, bg=colors.SURFACE)
        header.pack(fill="x", padx=theme.px(16), pady=(theme.px(10), theme.px(6)))
        tk.Label(
            header,
            text="事件日志",
            font=theme.section_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
        ).pack(side="left")
        clear_link = tk.Label(
            header,
            text="清空显示",
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
            cursor="hand2",
        )
        clear_link.pack(side="right")
        clear_link.bind("<Button-1>", lambda _event: self.clear_log())

        log_wrap = tk.Frame(card, bg=colors.SURFACE)
        log_wrap.pack(fill="x", padx=theme.px(12), pady=(0, theme.px(10)))
        scrollbar = ttk.Scrollbar(
            log_wrap,
            orient="vertical",
            style="Vertical.TScrollbar",
        )
        self.log_text = tk.Text(
            log_wrap,
            height=6,
            wrap="word",
            font=theme.small_font,
            fg=colors.TEXT_SOFT,
            bg=colors.SURFACE_ALT,
            relief="flat",
            borderwidth=0,
            padx=theme.px(10),
            pady=theme.px(7),
            spacing1=theme.px(1),
            spacing3=theme.px(1),
            yscrollcommand=scrollbar.set,
            state="disabled",
            cursor="arrow",
        )
        scrollbar.configure(command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="x", expand=True)
        self.log_text.tag_configure("time", foreground=colors.MUTED)
        for level, color in _LEVEL_COLORS.items():
            self.log_text.tag_configure(level, foreground=color)

    # ----------------------------------------------------------------- actions
    def _commit_countdown_event(self, _event=None):
        self._commit_countdown()
        return "break"

    def _commit_countdown(self) -> None:
        raw = self.countdown_var.get().strip()
        try:
            value = int(raw)
        except ValueError:
            self.countdown_var.set(str(self._countdown_seconds))
            return
        value = max(MIN_COUNTDOWN_SECONDS, min(MAX_COUNTDOWN_SECONDS, value))
        self.countdown_var.set(str(value))
        if value == self._countdown_seconds:
            return
        self._countdown_seconds = value
        self._on_countdown_changed(value)

    def _on_tree_select(self, _event=None) -> None:
        selection = self.tree.selection()
        self._selected_session_id = (
            self._tree_map.get(selection[0]) if selection else None
        )
        self._update_session_buttons()

    def _on_tree_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        session_id = self._tree_map.get(iid)
        if session_id:
            self._show_agent_plan_view(session_id)

    def _show_agent_plan_view(self, session_id: str) -> None:
        session = next(
            (item for item in self._sessions if item.session_id == session_id),
            None,
        )
        if session is None:
            return
        self._selected_session_id = session_id
        self._agent_plan_session_id = session_id
        self._sessions_view.pack_forget()
        self._agent_plan_view.pack(fill="both", expand=True)
        self._render_agent_plan_content(session)
        self._update_session_buttons()

    def _show_sessions_view(self) -> None:
        self._agent_plan_session_id = None
        self._agent_plan_view.pack_forget()
        self._sessions_view.pack(fill="both", expand=True)
        self._update_session_buttons()

    def _render_agent_plan_content(self, session: Session) -> None:
        completed, total = session.plan_progress
        self.agent_plan_title_label.configure(
            text=f"执行计划 · {_single_line(session.name, 40)}"
        )
        self.agent_plan_session_label.configure(
            text=_single_line(session.session_id, 44)
        )
        self.agent_plan_progress_label.configure(
            text=f"{completed}/{total} 已完成" if total else "尚未上报计划"
        )
        for item in self.agent_plan_tree.get_children():
            self.agent_plan_tree.delete(item)
        self._agent_plan_step_texts.clear()
        for step in session.plan_steps:
            iid = f"plan-step-{step.index}"
            self._agent_plan_step_texts[iid] = step.text
            self.agent_plan_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    step.index,
                    _single_line(step.text, 180),
                    "已完成" if step.completed else "待完成",
                ),
                tags=("completed" if step.completed else "pending",),
            )
        if session.plan_steps:
            self.agent_plan_empty_label.place_forget()
            self.agent_plan_detail.configure(text="选择步骤可查看完整内容。")
        else:
            self.agent_plan_empty_label.place(relx=0.5, rely=0.55, anchor="center")
            self.agent_plan_detail.configure(text="")

    def _on_agent_plan_select(self, _event=None) -> None:
        selection = self.agent_plan_tree.selection()
        if not selection:
            self.agent_plan_detail.configure(text="选择步骤可查看完整内容。")
            return
        text = self._agent_plan_step_texts.get(selection[0], "")
        self.agent_plan_detail.configure(text=text or "（空步骤）")

    def _remove_selected(self) -> None:
        if self._selected_session_id:
            self._on_remove_selected(self._selected_session_id)

    def _update_session_buttons(self) -> None:
        if self._selected_session_id:
            self.remove_button.state(["!disabled"])
        else:
            self.remove_button.state(["disabled"])
        if any(session.completed for session in self._sessions):
            self.clear_button.state(["!disabled"])
        else:
            self.clear_button.state(["disabled"])

    # -------------------------------------------------------------- rendering
    def set_pipe_status(self, ok: bool, text: str | None = None) -> None:
        color = colors.SUCCESS if ok else colors.DANGER
        label = text or ("监听中" if ok else "监听异常")
        self._status_dot.itemconfigure(self._status_dot_id, fill=color)
        self._status_label.configure(text=label)

    def set_countdown_value(self, seconds: int) -> None:
        self._countdown_seconds = max(
            MIN_COUNTDOWN_SECONDS, min(MAX_COUNTDOWN_SECONDS, int(seconds))
        )
        self.countdown_var.set(str(self._countdown_seconds))

    def render_sessions(self, sessions: Sequence[Session]) -> None:
        previous = self._selected_session_id
        previous_yview = self.tree.yview()
        self._sessions = tuple(sessions)
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._tree_map.clear()

        for index, session in enumerate(sessions):
            iid = f"row-{index}"
            self._tree_map[iid] = session.session_id
            if session.completed:
                status_text = "已完成"
                tag = "completed"
            elif session.action_needed:
                status_text = "进行中 · 需操作"
                tag = "action"
            elif session.has_error:
                status_text = "进行中 · 错误"
                tag = "error"
            else:
                status_text = "进行中"
                tag = "active"
            completed_steps, total_steps = session.plan_progress
            plan_text = (
                f"{completed_steps}/{total_steps}" if total_steps else "—"
            )
            latest = _single_line(session.last_text, 100)
            if not latest:
                latest = {
                    Status.REGISTER: "已注册",
                    Status.COMPLETE: "任务完成",
                    Status.ACTION: "需要操作",
                    Status.ERROR: "报告错误",
                    Status.RESUME: "已确认用户操作",
                    Status.NOTIFY: "消息",
                    Status.PLAN: "计划已更新",
                    Status.STEP_COMPLETE: "步骤完成",
                    Status.FILE_DOWNLOAD: "文件下载",
                }.get(session.last_event, "—")
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _single_line(session.name, 40),
                    _single_line(session.session_id, 36),
                    status_text,
                    plan_text,
                    latest,
                ),
                tags=(tag,),
            )
        completed = sum(1 for session in sessions if session.completed)
        pending = len(sessions) - completed
        self.session_count.configure(
            text=f"{len(sessions)} 个 · {pending} 个未完成"
            if sessions
            else "0 个"
        )
        if sessions:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.55, anchor="center")

        selected_iid = None
        if previous is not None:
            for iid, session_id in self._tree_map.items():
                if session_id == previous:
                    selected_iid = iid
                    break
        if selected_iid:
            self.tree.selection_set(selected_iid)
            self.tree.see(selected_iid)
            self._selected_session_id = previous
        else:
            self._selected_session_id = None
            if self.tree.selection():
                self.tree.selection_remove(self.tree.selection())
        if sessions and previous_yview:
            self.tree.yview_moveto(previous_yview[0])
        if self._agent_plan_session_id is not None:
            plan_session = next(
                (
                    session
                    for session in sessions
                    if session.session_id == self._agent_plan_session_id
                ),
                None,
            )
            if plan_session is None:
                self._show_sessions_view()
            else:
                self._render_agent_plan_content(plan_session)
        self._update_session_buttons()

    def render_plan(
        self,
        *,
        planned: bool,
        session_count: int,
        incomplete_count: int,
        remaining: int | None,
        firing: bool,
    ) -> None:
        self._planned = planned
        self._remaining = remaining
        self._firing = firing

        if firing:
            status_text = "正在发起系统关机…"
            status_color = colors.DANGER
            hint = "已向 Windows 发送关机请求。"
        elif planned and remaining is not None:
            status_text = f"倒计时 {_clock_from_seconds(remaining)} · 全部会话已完成"
            status_color = colors.WARNING
            hint = "可随时点击“取消计划关机”。倒计时结束将关闭电脑。"
        elif planned and session_count == 0:
            status_text = "已开启 · 等待会话注册"
            status_color = colors.PRIMARY
            hint = "Agent 注册并全部完成后开始倒计时。"
        elif planned and incomplete_count > 0:
            status_text = f"已开启 · 还有 {incomplete_count} 个会话未完成"
            status_color = colors.PRIMARY
            hint = "正在等待全部已注册会话完成任务。"
        elif planned:
            status_text = "已开启 · 即将关机"
            status_color = colors.WARNING
            hint = "全部已注册会话已完成。"
        elif session_count and incomplete_count == 0:
            status_text = "全部会话已完成 · 计划关机未开启"
            status_color = colors.MUTED
            hint = "开启计划关机后，将开始倒计时并关闭电脑。"
        else:
            status_text = "未开启"
            status_color = colors.MUTED
            hint = "开启后，全部已注册会话完成时自动关机。"

        self.plan_status.configure(text=status_text, fg=status_color)
        self.plan_hint.configure(text=hint)
        self.plan_button.configure(
            text="取消计划关机" if planned else "开启计划关机",
            style="Danger.TButton" if planned else "Primary.TButton",
        )
        if firing:
            self.plan_button.state(["disabled"])
        else:
            self.plan_button.state(["!disabled"])

        if remaining is not None or firing:
            self.countdown_spin.state(["disabled"])
        else:
            self.countdown_spin.state(["!disabled"])

    def append_log(self, level: str, message: str) -> None:
        if not message:
            return
        level = level if level in _LEVEL_COLORS else "info"
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", timestamp + "  ", ("time",))
        self.log_text.insert("end", message + "\n", (level,))
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 1_500:
            self.log_text.delete("1.0", "101.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
