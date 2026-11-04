"""BetterShutup application entry point and Tk controller."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import sys
import time
import tkinter as tk
from tkinter import messagebox
from typing import Sequence

from . import APP_NAME, DEFAULT_PIPE_NAME, __version__
from .config import (
    AppConfig,
    ConfigStore,
    app_data_dir,
    config_path,
    ensure_data_dirs,
    log_path,
    sounds_dir,
)
from .core import Coordinator, NoticeKind, Transition
from .downloader import DownloadManager
from .pipe_server import PipeServer
from .protocol import Message, ProtocolError, decode_frame
from .shutdown import perform_shutdown
from .single_instance import SingleInstance
from .sounds import SoundPlayer, ensure_default_sounds
from .ui.countdown import CountdownWindow
from .ui.main_window import MainWindow
from .ui.notifications import NotificationItem, NotificationManager
from .ui.settings import SettingsDialog
from .ui.theme import Theme, enable_dpi_awareness

LOGGER = logging.getLogger("better_shutup")


class _IncomingEvent:
    __slots__ = ("message", "error")

    def __init__(
        self,
        message: Message | None = None,
        error: str | None = None,
    ) -> None:
        self.message = message
        self.error = error


def _native_message(text: str, title: str = APP_NAME, flags: int = 0x10) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception:
        pass


def _normalize_pipe_name(value: str) -> str:
    value = value.strip()
    if not value:
        return DEFAULT_PIPE_NAME
    if not value.lower().startswith("\\\\.\\pipe\\"):
        value = "\\\\.\\pipe\\" + value.lstrip("\\")
    return value


def _configure_file_logging(path: Path) -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if any(getattr(handler, "_better_shutup_file", False) for handler in LOGGER.handlers):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler._better_shutup_file = True  # type: ignore[attr-defined]
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
        )
        LOGGER.addHandler(handler)
    except OSError:
        if sys.stderr is not None:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
            )
            LOGGER.addHandler(handler)


def _log_level_for_line(text: str) -> str:
    if any(token in text for token in ("失败", "错误", "无法")):
        return "error"
    if any(token in text for token in ("取消", "警告")):
        return "warning"
    if "完成" in text:
        return "success"
    return "info"


def _limit(text: str, limit: int = 1_200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class BetterShutupApp:
    def __init__(
        self,
        *,
        root: tk.Tk,
        config: AppConfig,
        config_store: ConfigStore,
        default_sounds: dict[str, Path],
        sound_player: SoundPlayer,
        pipe_name: str,
        dry_run: bool,
        data_dir: Path,
    ) -> None:
        self.root = root
        self.config = config
        self.config_store = config_store
        self.default_sounds = default_sounds
        self.sound_player = sound_player
        self.pipe_name = pipe_name
        self.dry_run = dry_run
        self.data_dir = data_dir
        self.coordinator = Coordinator(config.countdown_seconds)
        self.downloads = DownloadManager(
            logging.getLogger("better_shutup.downloader")
        )
        self.theme = Theme(root)
        self._incoming: queue.Queue[_IncomingEvent] = queue.Queue()
        self._server: PipeServer | None = None
        self._poll_after: str | None = None
        self._countdown_after: str | None = None
        self._shutdown_watchdog_after: str | None = None
        self._countdown_window: CountdownWindow | None = None
        self._firing = False
        self._closing = False
        self._started = False
        self._pipe_stopped_reported = False

        self.main = MainWindow(
            root,
            self.theme,
            pipe_name=pipe_name,
            dry_run=dry_run,
            countdown_seconds=self.coordinator.countdown_seconds,
            on_toggle_plan=self.toggle_plan,
            on_remove_selected=self.remove_session,
            on_clear_completed=self.clear_completed,
            on_settings=self.open_settings,
            on_close=self.request_close,
            on_countdown_changed=self.change_countdown,
        )
        self.notifications = NotificationManager(
            root,
            self.theme,
            sound_player,
        )
        root.report_callback_exception = self._report_callback_exception
        self._sync_state()
        self._log("info", f"BetterShutup v{__version__} 已启动。")
        if self.dry_run:
            self._log("warning", "当前为演练模式：倒计时结束后不会真正关机。")
        self._log("info", f"命名管道: {self.pipe_name}")

    # ------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        try:
            server = PipeServer(
                self.pipe_name,
                self._on_pipe_frame,
                self._on_pipe_error,
                logger=logging.getLogger("better_shutup.pipe_server"),
            )
            server.start()
        except Exception as exc:
            LOGGER.exception("命名管道启动失败")
            self.main.set_pipe_status(False, "启动失败")
            self._log("error", f"命名管道启动失败: {exc}")
            return False
        self._server = server
        self._started = True
        self._pipe_stopped_reported = False
        self.main.set_pipe_status(True, "监听中")
        self._log("info", "正在监听 Agent 消息。")
        self._schedule_poll()
        return True

    def run(self) -> None:
        self.root.mainloop()

    def _shutdown_app(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._poll_after is not None:
            try:
                self.root.after_cancel(self._poll_after)
            except tk.TclError:
                pass
            self._poll_after = None
        if self._countdown_after is not None:
            try:
                self.root.after_cancel(self._countdown_after)
            except tk.TclError:
                pass
            self._countdown_after = None
        if self._shutdown_watchdog_after is not None:
            try:
                self.root.after_cancel(self._shutdown_watchdog_after)
            except tk.TclError:
                pass
            self._shutdown_watchdog_after = None
        if self._countdown_window is not None:
            self._countdown_window.close()
            self._countdown_window = None
        try:
            self.notifications.close_all()
        except Exception:
            LOGGER.exception("关闭通知失败")
        try:
            self.downloads.close()
        except Exception:
            LOGGER.exception("关闭文件下载管理器失败")
        if self._server is not None:
            try:
                self._server.stop()
            except Exception:
                LOGGER.exception("停止命名管道失败")
            self._server = None
        try:
            self.sound_player.close()
        except Exception:
            LOGGER.exception("关闭音效播放器失败")
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def request_close(self) -> None:
        if self._closing:
            return
        had_plan = self.coordinator.planned
        if had_plan:
            transition = self.coordinator.set_planned(False)
            self._apply_transition(transition)
            self._sync_state(refresh_sessions=False)
        elif self.coordinator.deadline is not None:
            self._close_countdown_window()

        sessions = self.coordinator.sessions
        if self._firing:
            self._shutdown_app()
            return
        if had_plan or sessions:
            if had_plan:
                question = (
                    "已取消计划关机。退出后将停止监听，确定关闭 BetterShutup 吗？"
                )
            else:
                pending = self.coordinator.incomplete_count
                if pending:
                    question = (
                        f"仍有 {pending} 个会话未完成。退出后将停止监听，"
                        "确定关闭 BetterShutup 吗？"
                    )
                else:
                    question = (
                        "所有已注册会话均已完成。退出后将停止监听，"
                        "确定关闭 BetterShutup 吗？"
                    )
            if not messagebox.askyesno(
                "退出 BetterShutup",
                question,
                parent=self.root,
            ):
                self._log("info", "已取消退出。")
                return
        self._shutdown_app()

    # --------------------------------------------------------------- logging
    def _log(self, level: str, message: str) -> None:
        log_method = LOGGER.error if level == "error" else LOGGER.info
        log_method(message)
        if self._closing:
            return
        try:
            self.main.append_log(level, message)
        except Exception:
            LOGGER.exception("写入界面日志失败")

    # --------------------------------------------------------------- messages
    def _on_pipe_frame(self, frame: bytes) -> None:
        try:
            message = decode_frame(frame)
        except ProtocolError as exc:
            self._incoming.put(
                _IncomingEvent(error=f"收到无法解析的管道消息: {exc}")
            )
        except Exception as exc:  # Defensive worker-thread boundary.
            self._incoming.put(
                _IncomingEvent(error=f"处理管道消息时发生异常: {exc}")
            )
        else:
            self._incoming.put(_IncomingEvent(message=message))

    def _on_pipe_error(self, message: str) -> None:
        self._incoming.put(_IncomingEvent(error=message))

    def _schedule_poll(self) -> None:
        if self._closing:
            return
        self._poll_after = self.root.after(60, self._poll_events)

    def _poll_events(self) -> None:
        self._poll_after = None
        if self._closing:
            return
        try:
            changed = self._drain_events()
            if self._drain_downloads():
                changed = True
            if changed:
                self._sync_state()
            self._check_pipe_listener()
        except Exception as exc:
            LOGGER.exception("轮询消息失败")
            try:
                self.main.append_log("error", f"消息轮询异常：{exc}")
            except Exception:
                pass
            self._notify_system_error("消息处理异常", str(exc))
        finally:
            self._schedule_poll()

    def _check_pipe_listener(self) -> None:
        if (
            self._closing
            or not self._started
            or self._server is None
            or self._server.is_running
            or self._pipe_stopped_reported
        ):
            return
        self._pipe_stopped_reported = True
        self.main.set_pipe_status(False, "监听已停止")
        message = "命名管道监听线程已停止。请重启 BetterShutup。"
        self._log("error", message)
        self._notify_system_error("监听已停止", message)

    def _drain_events(self, limit: int | None = 200) -> bool:
        processed = False
        count = 0
        while limit is None or count < limit:
            try:
                event = self._incoming.get_nowait()
            except queue.Empty:
                break
            count += 1
            processed = True
            if event.error is not None:
                self._handle_pipe_error(event.error)
            elif event.message is not None:
                try:
                    transition = self.coordinator.handle_message(
                        event.message,
                        now=time.monotonic(),
                    )
                except Exception as exc:
                    LOGGER.exception("处理协议消息失败")
                    self._notify_system_error(
                        "协议处理错误",
                        f"处理 {event.message.status.binary} 消息时发生异常: {exc}",
                    )
                else:
                    self._apply_transition(transition)
        return processed

    def _drain_downloads(self) -> bool:
        processed = False
        for result in self.downloads.drain():
            processed = True
            try:
                transition = self.coordinator.download_finished(
                    session_id=result.session_id,
                    url=result.url,
                    path=result.path,
                    success=result.success,
                    detail=result.error,
                    bytes_written=result.bytes_written,
                )
            except Exception:
                LOGGER.exception("处理文件下载结果失败")
                self._notify_system_error(
                    "文件下载结果处理失败",
                    result.path,
                )
                continue
            self._apply_transition(transition)
        return processed

    def _apply_transition(self, transition: Transition) -> None:
        for line in transition.logs:
            self._log(_log_level_for_line(line), line)
        for session_id in transition.dismiss_action_session_ids:
            try:
                self.notifications.dismiss_session(session_id, NoticeKind.ACTION)
            except Exception:
                LOGGER.exception("关闭已恢复会话的操作通知失败")
        for notice in transition.notices:
            if notice.kind is not NoticeKind.PROTOCOL_ERROR and notice.text.strip():
                prefix = {
                    NoticeKind.COMPLETE: "完成消息",
                    NoticeKind.ACTION: "操作指令",
                    NoticeKind.ERROR: "错误信息",
                    NoticeKind.NOTIFY: "消息",
                    NoticeKind.PLAN: "计划更新",
                    NoticeKind.STEP_COMPLETE: "步骤完成",
                    NoticeKind.DOWNLOAD_SUCCESS: "文件下载完成",
                    NoticeKind.DOWNLOAD_FAILURE: "文件下载失败",
                }.get(notice.kind, "消息")
                level = {
                    NoticeKind.COMPLETE: "success",
                    NoticeKind.ACTION: "warning",
                    NoticeKind.ERROR: "error",
                    NoticeKind.STEP_COMPLETE: "success",
                    NoticeKind.DOWNLOAD_SUCCESS: "success",
                    NoticeKind.DOWNLOAD_FAILURE: "error",
                }.get(notice.kind, "info")
                self._log(level, f"{prefix}：{_limit(notice.text)}")
            try:
                self.notifications.push(
                    NotificationItem(
                        kind=notice.kind,
                        session_id=notice.session_id,
                        session_name=notice.session_name,
                        text=notice.text,
                    )
                )
            except Exception:
                LOGGER.exception("显示通知失败")
        for request in transition.download_requests:
            if self._closing:
                break
            try:
                self.downloads.start(
                    request.session_id,
                    request.url,
                    request.path,
                )
            except Exception as exc:
                LOGGER.exception("启动文件下载失败")
                failed = self.coordinator.download_finished(
                    session_id=request.session_id,
                    url=request.url,
                    path=request.path,
                    success=False,
                    detail=f"启动下载失败: {exc}",
                )
                self._apply_transition(failed)

    def _handle_pipe_error(self, message: str) -> None:
        self._log("error", message)
        self._notify_system_error("管道错误", message)

    def _notify_system_error(self, title: str, message: str) -> None:
        if self._closing:
            return
        try:
            self.notifications.push(
                NotificationItem(
                    kind=NoticeKind.ERROR,
                    session_id="",
                    session_name="",
                    title=title,
                    text=message,
                )
            )
        except Exception:
            LOGGER.exception("显示错误通知失败")

    # ------------------------------------------------------------ state sync
    def _sync_state(self, *, refresh_sessions: bool = True) -> None:
        if self._closing:
            return
        if refresh_sessions:
            self.main.render_sessions(self.coordinator.sessions)
        self._render_plan_and_countdown()
        self._ensure_countdown_tick()

    def _render_plan_and_countdown(self) -> None:
        if self._closing:
            return
        coordinator = self.coordinator
        remaining = coordinator.seconds_remaining(time.monotonic())
        self.main.render_plan(
            planned=coordinator.planned,
            session_count=len(coordinator.sessions),
            incomplete_count=coordinator.incomplete_count,
            remaining=remaining,
            firing=self._firing,
        )
        if self._firing:
            if self._countdown_window is not None:
                self._countdown_window.set_firing()
            return
        if coordinator.deadline is not None:
            if self._countdown_window is None:
                self._countdown_window = CountdownWindow(
                    parent=self.root,
                    theme=self.theme,
                    on_cancel=self.cancel_plan_from_countdown,
                    dry_run=self.dry_run,
                )
            self._countdown_window.update_remaining(remaining or 0)
        else:
            self._close_countdown_window()

    def _close_countdown_window(self) -> None:
        if self._countdown_window is not None:
            self._countdown_window.close()
            self._countdown_window = None

    def _ensure_countdown_tick(self) -> None:
        if (
            self._closing
            or self._firing
            or self.coordinator.deadline is None
        ):
            if self._countdown_after is not None:
                try:
                    self.root.after_cancel(self._countdown_after)
                except tk.TclError:
                    pass
                self._countdown_after = None
            return
        if self._countdown_after is None:
            self._countdown_after = self.root.after(
                200, self._on_countdown_tick
            )

    def _on_countdown_tick(self) -> None:
        self._countdown_after = None
        if self._closing or self._firing:
            return
        try:
            # Before deciding to shut down, drain everything that has already
            # arrived.  A 200-item poll cap is fine for UI responsiveness, but
            # it must not hide a late action/error at the shutdown boundary.
            changed = self._drain_events(limit=None)
            if self._drain_downloads():
                changed = True
            if changed:
                self._sync_state()
            if self._closing or self._firing:
                return
            if self.coordinator.deadline is None:
                return

            now = time.monotonic()
            remaining = self.coordinator.seconds_remaining(now)
            if remaining is None:
                self._close_countdown_window()
                return
            if remaining > 0:
                self._render_plan_and_countdown()
                return

            transition = self.coordinator.tick(now)
            self._apply_transition(transition)
            if transition.shutdown_due:
                self._firing = True
                try:
                    self._render_plan_and_countdown()
                except Exception:
                    LOGGER.exception("更新关机界面失败")
                self._perform_shutdown()
            else:
                self._sync_state()
        except Exception as exc:
            LOGGER.exception("倒计时处理失败")
            self._notify_system_error("倒计时处理失败", str(exc))
        finally:
            self._ensure_countdown_tick()

    def _perform_shutdown(self) -> None:
        try:
            result = perform_shutdown(dry_run=self.dry_run)
        except Exception as exc:
            LOGGER.exception("发起关机时发生异常")
            result = None
            detail = f"发起关机时发生异常: {exc}"
        if result is not None and result.ok:
            self._log("info", result.detail)
            if self.dry_run:
                self._firing = False
                self._log("info", "演练结束，应用继续运行。")
                self._sync_state(refresh_sessions=False)
            else:
                self._schedule_shutdown_watchdog()
            return
        detail = result.detail if result is not None else detail
        self._firing = False
        self._log("error", detail)
        self._notify_system_error("关机失败", detail)
        self._sync_state(refresh_sessions=False)

    def _schedule_shutdown_watchdog(self) -> None:
        if self._shutdown_watchdog_after is not None:
            try:
                self.root.after_cancel(self._shutdown_watchdog_after)
            except tk.TclError:
                pass
        self._shutdown_watchdog_after = self.root.after(
            60_000, self._shutdown_watchdog
        )

    def _shutdown_watchdog(self) -> None:
        self._shutdown_watchdog_after = None
        if self._closing or not self._firing:
            return
        self._firing = False
        message = (
            "Windows 在 60 秒内没有完成关机，关机请求可能已被取消或被应用阻止。"
        )
        self._log("error", message)
        self._notify_system_error("关机未完成", message)
        self._sync_state(refresh_sessions=False)

    # --------------------------------------------------------------- actions
    def toggle_plan(self) -> None:
        if self._closing or self._firing:
            return
        transition = self.coordinator.set_planned(
            not self.coordinator.planned,
            now=time.monotonic(),
        )
        self._apply_transition(transition)
        self._sync_state(refresh_sessions=False)

    def cancel_plan_from_countdown(self) -> None:
        if self._closing or self._firing:
            return
        transition = self.coordinator.set_planned(
            False, now=time.monotonic()
        )
        self._apply_transition(transition)
        self._sync_state(refresh_sessions=False)

    def change_countdown(self, value: int) -> None:
        try:
            transition = self.coordinator.set_countdown_seconds(value)
        except ValueError as exc:
            self._notify_system_error("倒计时设置无效", str(exc))
            self.main.set_countdown_value(self.coordinator.countdown_seconds)
            return
        self._apply_transition(transition)
        self.config.countdown_seconds = self.coordinator.countdown_seconds
        try:
            self.config_store.save(self.config)
        except Exception as exc:
            LOGGER.exception("保存倒计时设置失败")
            self._notify_system_error("保存设置失败", str(exc))
        self.main.set_countdown_value(self.coordinator.countdown_seconds)
        self._sync_state(refresh_sessions=False)

    def remove_session(self, session_id: str) -> None:
        session = self.coordinator.get_session(session_id)
        if session is None:
            return
        if not messagebox.askyesno(
            "移除会话",
            f"确定移除会话「{session.name}」？\n"
            "移除后它不再参与计划关机判断。",
            parent=self.root,
        ):
            return
        transition = self.coordinator.remove_session(
            session_id, now=time.monotonic()
        )
        self._apply_transition(transition)
        self._sync_state()

    def clear_completed(self) -> None:
        transition = self.coordinator.clear_completed(
            now=time.monotonic()
        )
        self._apply_transition(transition)
        self._sync_state()

    def open_settings(self) -> None:
        if self._closing:
            return
        SettingsDialog(
            parent=self.root,
            theme=self.theme,
            config=self.config,
            default_sounds=self.default_sounds,
            sound_player=self.sound_player,
            on_save=self.save_sound_settings,
        )

    def save_sound_settings(
        self, overrides: dict[str, str | None]
    ) -> None:
        previous = dict(self.config.sound_overrides)
        self.config.sound_overrides = dict(overrides)
        try:
            self.config_store.save(self.config)
        except Exception:
            self.config.sound_overrides = previous
            raise
        self.sound_player.set_overrides(self.config.sound_overrides)
        self._log("info", "提示音设置已保存。")

    # -------------------------------------------------------------- Tk errors
    def _report_callback_exception(
        self, exc_type, exc_value, exc_tb
    ) -> None:
        LOGGER.error(
            "界面回调发生未捕获异常",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        if self._closing:
            return
        try:
            self.main.append_log("error", f"界面异常：{exc_value}")
        except Exception:
            pass
        self._notify_system_error("界面异常", str(exc_value))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="better-shutup",
        description="Coordinate agent sessions and scheduled shutdown on Windows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="演练模式：走完整倒计时流程，但不真正关机。",
    )
    parser.add_argument(
        "--pipe",
        default=None,
        help="覆盖命名管道名（默认 \\\\.\\pipe\\BetterShutup）。",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="覆盖配置/日志/音效所在目录。",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    pipe_name = _normalize_pipe_name(
        args.pipe
        or os.environ.get("BETTER_SHUTUP_PIPE")
        or DEFAULT_PIPE_NAME
    )
    base_dir = (
        args.data_dir.expanduser().resolve()
        if args.data_dir is not None
        else app_data_dir()
    )
    try:
        ensure_data_dirs(base_dir)
    except OSError as exc:
        _native_message(
            f"无法创建数据目录：\n{base_dir}\n\n{exc}",
            APP_NAME,
            0x10,
        )
        return 1

    _configure_file_logging(log_path(base_dir))
    LOGGER.info("参数: dry_run=%s pipe=%s data_dir=%s", args.dry_run, pipe_name, base_dir)
    enable_dpi_awareness()

    mutex_hash = hashlib.sha1(
        pipe_name.casefold().encode("utf-8")
    ).hexdigest()[:16]
    instance = SingleInstance(f"Local\\BetterShutup-{mutex_hash}")
    try:
        acquired = instance.acquire()
    except OSError as exc:
        LOGGER.exception("创建单实例互斥体失败")
        _native_message(f"无法启动 BetterShutup：\n{exc}", APP_NAME, 0x10)
        return 1
    if not acquired:
        _native_message(
            "BetterShutup 已在运行。\n"
            "请切换到已打开的窗口。",
            APP_NAME,
            0x40,
        )
        return 0

    config_store = ConfigStore(config_path(base_dir))
    config = config_store.load()
    try:
        default_sounds = ensure_default_sounds(sounds_dir(base_dir))
    except Exception:
        LOGGER.exception("生成默认音效失败")
        default_sounds = {}

    sound_player: SoundPlayer | None = None
    app: BetterShutupApp | None = None
    exit_code = 0
    try:
        sound_player = SoundPlayer(
            default_sounds,
            config.sound_overrides,
            logger=logging.getLogger("better_shutup.sounds"),
        )
        root = tk.Tk()
        root.withdraw()
        app = BetterShutupApp(
            root=root,
            config=config,
            config_store=config_store,
            default_sounds=default_sounds,
            sound_player=sound_player,
            pipe_name=pipe_name,
            dry_run=args.dry_run,
            data_dir=base_dir,
        )
        if not app.start():
            messagebox.showerror(
                "BetterShutup 启动失败",
                "无法启动命名管道监听。请查看日志后重试。",
                parent=root,
            )
            app._shutdown_app()
            exit_code = 1
        else:
            root.deiconify()
            app.run()
    except Exception as exc:
        LOGGER.exception("BetterShutup 发生致命错误")
        try:
            messagebox.showerror(
                "BetterShutup 发生错误",
                f"程序发生未处理异常：\n{exc}\n\n详细信息已写入日志。",
            )
        except Exception:
            _native_message(
                f"BetterShutup 发生未处理异常：\n{exc}",
                APP_NAME,
                0x10,
            )
        if app is not None:
            try:
                app._shutdown_app()
            except Exception:
                LOGGER.exception("关闭应用失败")
        exit_code = 1
    finally:
        if app is None and sound_player is not None:
            try:
                sound_player.close()
            except Exception:
                pass
        instance.close()
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
