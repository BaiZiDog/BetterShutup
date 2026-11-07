"""Settings dialog for sounds, data directory, and logs."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from ..config import AppConfig, SOUND_KINDS
from ..sounds import SoundPlayer, validate_wav_file
from . import theme as colors
from .animation import fade_in_window
from .theme import Theme

_DISPLAY_NAMES = {
    "complete": "任务完成（0001）",
    "action": "需要操作（0010）",
    "error": "错误（0011）",
    "notify": "消息 / 计划 / 步骤（0101 / 0110 / 0111）",
}


class SettingsDialog:
    def __init__(
        self,
        *,
        parent: tk.Tk,
        theme: Theme,
        config: AppConfig,
        default_sounds: dict[str, Path],
        sound_player: SoundPlayer | None,
        data_dir: Path,
        log_file: Path,
        on_open_path: Callable[[Path], None],
        on_save: Callable[[dict[str, str | None]], None],
    ) -> None:
        self.parent = parent
        self.theme = theme
        self.config = config
        self.default_sounds = default_sounds
        self.sound_player = sound_player
        self.data_dir = data_dir
        self.log_file = log_file
        self._on_open_path = on_open_path
        self._on_save = on_save
        self._closed = False
        self._vars: dict[str, tk.StringVar] = {}
        self._entries: dict[str, tk.Entry] = {}

        window = tk.Toplevel(parent)
        self.window = window
        window.title("BetterShutup · 设置")
        window.configure(bg=colors.BG)
        window.transient(parent)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _event: self.close())

        header = tk.Frame(window, bg=colors.SURFACE)
        header.pack(fill="x")
        title_label = tk.Label(
            header,
            text="设置",
            font=theme.title_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
            anchor="w",
        )
        title_label.pack(
            anchor="w", padx=theme.px(24), pady=(theme.px(18), theme.px(3))
        )
        subtitle_label = tk.Label(
            header,
            text="提示音、数据目录与日志位置。配置、日志和内置音效都保存在数据目录中。",
            font=theme.body_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
            anchor="w",
        )
        subtitle_label.pack(
            anchor="w", padx=theme.px(24), pady=(0, theme.px(16))
        )
        tk.Frame(window, bg=colors.BORDER, height=1).pack(fill="x")

        notebook = ttk.Notebook(window)
        notebook.pack(
            fill="both",
            expand=True,
            padx=theme.px(24),
            pady=(theme.px(16), theme.px(8)),
        )
        sound_tab = tk.Frame(notebook, bg=colors.BG)
        data_tab = tk.Frame(notebook, bg=colors.BG)
        notebook.add(sound_tab, text="提示音")
        notebook.add(data_tab, text="数据与日志")

        sound_content = tk.Frame(sound_tab, bg=colors.BG)
        sound_content.pack(
            fill="both",
            expand=True,
            padx=theme.px(10),
            pady=theme.px(12),
        )
        data_content = tk.Frame(data_tab, bg=colors.BG)
        data_content.pack(
            fill="both",
            expand=True,
            padx=theme.px(10),
            pady=theme.px(12),
        )

        for kind in SOUND_KINDS:
            self._build_row(sound_content, kind)
        self._build_data_section(data_content)

        buttons = tk.Frame(window, bg=colors.BG)
        buttons.pack(fill="x", padx=theme.px(24), pady=(0, theme.px(20)))
        ttk.Button(
            buttons,
            text="取消",
            style="Secondary.TButton",
            command=self.close,
        ).pack(side="right")
        ttk.Button(
            buttons,
            text="保存",
            style="Primary.TButton",
            command=self._save,
        ).pack(side="right", padx=(0, theme.px(10)))

        window.update_idletasks()
        theme.center(window, theme.px(760), window.winfo_reqheight() + theme.px(10))
        window.lift()
        window.focus_set()
        fade_in_window(window)

    def _build_data_section(self, parent: tk.Misc) -> None:
        theme = self.theme
        card = tk.Frame(
            parent,
            bg=colors.SURFACE,
            highlightbackground=colors.BORDER,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(0, theme.px(14)))
        card.grid_columnconfigure(1, weight=1)

        tk.Label(
            card,
            text="数据与日志",
            font=theme.section_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
            anchor="w",
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            padx=theme.px(14),
            pady=(theme.px(12), theme.px(7)),
        )

        rows = (
            ("数据目录", self.data_dir),
            ("日志文件", self.log_file),
        )
        for row, (label, path) in enumerate(rows, start=1):
            tk.Label(
                card,
                text=label,
                font=theme.small_bold,
                fg=colors.MUTED,
                bg=colors.SURFACE,
                anchor="nw",
            ).grid(
                row=row,
                column=0,
                sticky="nw",
                padx=(theme.px(14), theme.px(10)),
                pady=theme.px(2),
            )
            tk.Label(
                card,
                text=str(path),
                font=theme.mono_small,
                fg=colors.TEXT_SOFT,
                bg=colors.SURFACE,
                anchor="w",
                justify="left",
                wraplength=theme.px(600),
            ).grid(
                row=row,
                column=1,
                sticky="w",
                padx=(0, theme.px(14)),
                pady=theme.px(2),
            )

        actions = tk.Frame(card, bg=colors.SURFACE)
        actions.grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="w",
            padx=theme.px(14),
            pady=(theme.px(9), theme.px(8)),
        )
        self._small_button(
            actions,
            "打开数据目录",
            lambda: self._on_open_path(self.data_dir),
        ).pack(side="left")
        self._small_button(
            actions,
            "打开日志文件",
            lambda: self._on_open_path(self.log_file),
        ).pack(side="left", padx=(theme.px(6), 0))

        tk.Label(
            card,
            text="卸载应用不会删除数据目录。",
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
            anchor="w",
        ).grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="w",
            padx=theme.px(14),
            pady=(0, theme.px(10)),
        )

    def _build_row(self, parent: tk.Misc, kind: str) -> None:
        theme = self.theme
        card = tk.Frame(
            parent,
            bg=colors.SURFACE,
            highlightbackground=colors.BORDER,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(0, theme.px(10)))
        card.grid_columnconfigure(0, weight=1)

        label = tk.Label(
            card,
            text=_DISPLAY_NAMES[kind],
            font=theme.body_bold,
            fg=colors.TEXT,
            bg=colors.SURFACE,
            anchor="w",
        )
        label.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            padx=theme.px(14),
            pady=(theme.px(11), theme.px(6)),
        )

        variable = tk.StringVar(
            value=self.config.sound_for(kind) or ""
        )
        self._vars[kind] = variable
        field_frame = tk.Frame(
            card,
            bg=colors.SURFACE,
            highlightbackground=colors.BORDER,
            highlightthickness=1,
        )
        field_frame.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(theme.px(14), theme.px(8)),
            pady=(0, theme.px(8)),
        )
        entry = tk.Entry(
            field_frame,
            textvariable=variable,
            font=theme.body_font,
            fg=colors.TEXT,
            bg=colors.SURFACE,
            relief="flat",
            borderwidth=0,
            insertbackground=colors.TEXT,
        )
        entry.pack(fill="x", padx=theme.px(8), pady=theme.px(6))
        self._entries[kind] = entry

        actions = tk.Frame(card, bg=colors.SURFACE)
        actions.grid(
            row=1,
            column=1,
            sticky="e",
            padx=(0, theme.px(14)),
            pady=(0, theme.px(8)),
        )
        self._small_button(actions, "浏览", lambda: self._browse(kind)).pack(
            side="left"
        )
        self._small_button(actions, "试听", lambda: self._preview(kind)).pack(
            side="left", padx=(theme.px(6), 0)
        )
        self._small_button(
            actions,
            "恢复默认",
            lambda: self._restore_default(kind),
            color=colors.MUTED,
        ).pack(side="left", padx=(theme.px(6), 0))

        default_path = self.default_sounds.get(kind)
        default_text = (
            f"内置音效：{default_path.name}"
            if default_path is not None
            else "内置音效不可用"
        )
        tk.Label(
            card,
            text=default_text + ("（留空即使用内置）" if default_path else ""),
            font=theme.small_font,
            fg=colors.MUTED,
            bg=colors.SURFACE,
            anchor="w",
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="w",
            padx=theme.px(14),
            pady=(0, theme.px(9)),
        )

    def _small_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        color: str = colors.TEXT_SOFT,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=self.theme.small_font,
            fg=color,
            bg=colors.SURFACE_SUNKEN,
            activeforeground=color,
            activebackground="#E7ECF3",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=self.theme.px(9),
            pady=self.theme.px(4),
        )

    def _browse(self, kind: str) -> None:
        path = filedialog.askopenfilename(
            parent=self.window,
            title=f"选择{_DISPLAY_NAMES[kind]}音效",
            filetypes=(("WAV 音频", "*.wav"), ("所有文件", "*.*")),
        )
        if not path:
            return
        ok, error = validate_wav_file(Path(path))
        if not ok:
            messagebox.showerror(
                "无法使用该音频",
                f"{path}\n\n{error}",
                parent=self.window,
            )
            return
        self._vars[kind].set(str(Path(path).resolve()))
        self._entries[kind].icursor(tk.END)

    def _preview(self, kind: str) -> None:
        raw = self._vars[kind].get().strip()
        if raw:
            path = Path(raw).expanduser()
            ok, error = validate_wav_file(path)
            if not ok:
                messagebox.showerror(
                    "无法试听",
                    f"{raw}\n\n{error}",
                    parent=self.window,
                )
                return
            chosen: Path | None = path
        else:
            chosen = self.default_sounds.get(kind)
        if chosen is None:
            messagebox.showerror(
                "无法试听",
                "没有可用的内置音效文件。",
                parent=self.window,
            )
            return
        if self.sound_player is not None:
            self.sound_player.preview(chosen, kind)

    def _restore_default(self, kind: str) -> None:
        self._vars[kind].set("")

    def _save(self) -> None:
        overrides: dict[str, str | None] = {}
        for kind, variable in self._vars.items():
            raw = variable.get().strip()
            if not raw:
                overrides[kind] = None
                continue
            path = Path(raw).expanduser()
            ok, error = validate_wav_file(path)
            if not ok:
                messagebox.showerror(
                    "无法保存",
                    f"{_DISPLAY_NAMES[kind]}：{raw}\n\n{error}",
                    parent=self.window,
                )
                return
            overrides[kind] = str(path.resolve())
        try:
            self._on_save(overrides)
        except Exception as exc:  # App callback may fail to persist.
            messagebox.showerror(
                "保存失败",
                f"无法保存提示音设置：{exc}",
                parent=self.window,
            )
            return
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.window.destroy()
        except tk.TclError:
            pass
