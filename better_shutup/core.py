"""Pure session registry and scheduled-shutdown state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
from pathlib import PureWindowsPath
import time

from .protocol import Message, Status

MIN_COUNTDOWN_SECONDS = 5
MAX_COUNTDOWN_SECONDS = 3600
DEFAULT_COUNTDOWN_SECONDS = 60
MIN_SCHEDULE_SECONDS = 1
MAX_SCHEDULE_SECONDS = 7 * 24 * 60 * 60


class ScheduleMode(str, Enum):
    TIME = "time"
    DELAY = "delay"


class NoticeKind(str, Enum):
    COMPLETE = "complete"
    ACTION = "action"
    ERROR = "error"
    NOTIFY = "notify"
    PLAN = "plan"
    STEP_COMPLETE = "step_complete"
    DOWNLOAD_SUCCESS = "download_success"
    DOWNLOAD_FAILURE = "download_failure"
    PROTOCOL_ERROR = "protocol_error"


@dataclass(slots=True)
class PlanStep:
    index: str
    text: str
    completed: bool = False


@dataclass(slots=True)
class Session:
    session_id: str
    name: str
    completed: bool = False
    action_needed: bool = False
    has_error: bool = False
    last_event: Status = Status.REGISTER
    last_text: str = ""
    plan: dict[str, PlanStep] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def plan_steps(self) -> tuple[PlanStep, ...]:
        """Plan steps ordered by their numeric index."""

        return tuple(sorted(self.plan.values(), key=lambda step: int(step.index)))

    @property
    def completed_step_count(self) -> int:
        return sum(1 for step in self.plan.values() if step.completed)

    @property
    def plan_progress(self) -> tuple[int, int]:
        return self.completed_step_count, len(self.plan)


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    session_id: str
    session_name: str
    url: str
    path: str


@dataclass(frozen=True, slots=True)
class Notice:
    kind: NoticeKind
    session_id: str
    session_name: str
    text: str


@dataclass(slots=True)
class Transition:
    notices: list[Notice] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    shutdown_due: bool = False
    dismiss_action_session_ids: list[str] = field(default_factory=list)
    download_requests: list[DownloadRequest] = field(default_factory=list)


def _summarize_steps(steps: tuple[tuple[str, str], ...], limit: int = 500) -> str:
    summary = "；".join(f"{index}. {text}" for index, text in steps)
    if len(summary) > limit:
        summary = summary[: limit - 1].rstrip() + "…"
    return summary


class Coordinator:
    """Tracks sessions and the optional planned shutdown.

    All time-based decisions use a caller-supplied monotonic timestamp so the
    state machine can be tested without sleeping.  Wall-clock timestamps are
    only stored for display.
    """

    def __init__(self, countdown_seconds: int = DEFAULT_COUNTDOWN_SECONDS) -> None:
        self._sessions: dict[str, Session] = {}
        self._planned = False
        self._deadline: float | None = None
        self._countdown_source: str | None = None
        self._schedule_enabled = False
        self._schedule_mode: ScheduleMode | None = None
        self._schedule_target_wall: datetime | None = None
        self._schedule_target: float | None = None
        self._schedule_wait_logged = False
        self._countdown_seconds = self._clamp_countdown(countdown_seconds)

    @property
    def sessions(self) -> tuple[Session, ...]:
        return tuple(self._sessions.values())

    @property
    def planned(self) -> bool:
        return self._planned

    @property
    def deadline(self) -> float | None:
        return self._deadline

    @property
    def countdown_seconds(self) -> int:
        return self._countdown_seconds

    @property
    def countdown_source(self) -> str | None:
        """Return ``"plan"`` or ``"schedule"`` while a countdown is active."""

        return self._countdown_source

    @property
    def schedule_enabled(self) -> bool:
        return self._schedule_enabled

    @property
    def schedule_mode(self) -> ScheduleMode | None:
        return self._schedule_mode

    @property
    def schedule_target_wall(self) -> datetime | None:
        return self._schedule_target_wall

    def schedule_seconds_remaining(self, now: float | None = None) -> int | None:
        if not self._schedule_enabled or self._schedule_target is None:
            return None
        current = time.monotonic() if now is None else now
        return max(0, math.ceil(self._schedule_target - current))

    def schedule_waiting_for_sessions(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return (
            self._schedule_enabled
            and self._schedule_target is not None
            and current >= self._schedule_target
            and self._deadline is None
            and self.has_sessions
            and not self.all_complete
        )

    @property
    def has_sessions(self) -> bool:
        return bool(self._sessions)

    @property
    def incomplete_count(self) -> int:
        return sum(1 for session in self._sessions.values() if not session.completed)

    @property
    def all_complete(self) -> bool:
        return all(session.completed for session in self._sessions.values())

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def seconds_remaining(self, now: float | None = None) -> int | None:
        if self._deadline is None:
            return None
        current = time.monotonic() if now is None else now
        return max(0, math.ceil(self._deadline - current))

    def handle_message(
        self, message: Message, now: float | None = None
    ) -> Transition:
        current = time.monotonic() if now is None else now
        transition = Transition()

        if message.status is Status.REGISTER:
            self._handle_register(message, transition)
            return transition

        session = self._sessions.get(message.session_id)
        if session is None:
            text = (
                f"收到 {message.status.binary}（{message.status_name}）消息，"
                f"但会话 ID「{message.session_id}」尚未注册。"
            )
            return self._protocol_error(message, transition, text)

        if message.status is Status.PLAN:
            return self._handle_plan(session, message, transition)
        if message.status is Status.STEP_COMPLETE:
            return self._handle_step_complete(session, message, transition)
        if message.status is Status.FILE_DOWNLOAD:
            return self._handle_file_download(session, message, transition)

        if message.status in (
            Status.ACTION,
            Status.ERROR,
            Status.NOTIFY,
        ):
            self._note_new_work(session, message, transition)

        self._touch(session, message)

        if message.status is Status.COMPLETE:
            session.completed = True
            session.action_needed = False
            session.has_error = False
            transition.notices.append(
                Notice(
                    kind=NoticeKind.COMPLETE,
                    session_id=session.session_id,
                    session_name=session.name,
                    text=message.text,
                )
            )
            transition.logs.append(f"会话「{session.name}」完成任务。")
            self._maybe_start_countdown(current, transition)
        elif message.status is Status.ACTION:
            session.action_needed = True
            session.has_error = False
            transition.notices.append(
                Notice(
                    kind=NoticeKind.ACTION,
                    session_id=session.session_id,
                    session_name=session.name,
                    text=message.text,
                )
            )
            transition.logs.append(f"会话「{session.name}」需要操作。")
        elif message.status is Status.ERROR:
            session.has_error = True
            session.action_needed = False
            transition.notices.append(
                Notice(
                    kind=NoticeKind.ERROR,
                    session_id=session.session_id,
                    session_name=session.name,
                    text=message.text,
                )
            )
            transition.logs.append(f"会话「{session.name}」报告错误。")
        elif message.status is Status.RESUME:
            self._handle_resume(session, transition)
        elif message.status is Status.NOTIFY:
            if not session.last_text:
                session.last_text = "（无消息内容）"
            transition.notices.append(
                Notice(
                    kind=NoticeKind.NOTIFY,
                    session_id=session.session_id,
                    session_name=session.name,
                    text=message.text,
                )
            )
            transition.logs.append(f"会话「{session.name}」发送了一条消息。")

        return transition

    # ------------------------------------------------------------------ status
    def _handle_register(self, message: Message, transition: Transition) -> None:
        """Status 0000 only registers a session or updates its display name."""

        existing = self._sessions.get(message.session_id)
        if existing is None:
            session = Session(
                session_id=message.session_id,
                name=message.session_name,
            )
            self._sessions[message.session_id] = session
            transition.logs.append(
                f"注册新会话「{session.name}」 ({session.session_id})。"
            )
            if self._deadline is not None:
                self._deadline = None
                self._countdown_source = None
                self._schedule_wait_logged = False
                transition.logs.append("新会话到达，本次关机倒计时已取消。")
            return

        existing.name = message.session_name
        existing.updated_at = datetime.now()
        if existing.completed:
            transition.logs.append(
                f"会话「{existing.name}」注册信息已更新，保持已完成状态。"
            )
        elif existing.action_needed:
            transition.logs.append(
                f"会话「{existing.name}」注册信息已更新，需要操作状态保留；"
                "如需撤销请发送 0100（resume）。"
            )
        elif existing.has_error:
            transition.logs.append(
                f"会话「{existing.name}」注册信息已更新，错误状态保留。"
            )
        else:
            transition.logs.append(
                f"会话「{existing.name}」注册信息已更新，状态正常。"
            )

    def _handle_resume(self, session: Session, transition: Transition) -> None:
        """Status 0100 acknowledges the user's response to an action request."""

        was_action = session.action_needed
        session.action_needed = False
        # Always ask the UI to close action cards for this session.  There may
        # be a card left over from an ACTION that was followed by COMPLETE.
        transition.dismiss_action_session_ids.append(session.session_id)
        if not session.last_text:
            session.last_text = "已确认用户操作"
        if was_action:
            transition.logs.append(
                f"会话「{session.name}」已确认用户操作，需要操作状态已清除。"
            )
        elif session.has_error:
            transition.logs.append(
                f"会话「{session.name}」未处于需要操作状态，错误状态保留。"
            )
        elif session.completed:
            transition.logs.append(
                f"会话「{session.name}」已完成，确认信号不影响完成状态。"
            )
        else:
            transition.logs.append(
                f"会话「{session.name}」未处于需要操作状态，确认信号已记录。"
            )

    def _handle_plan(
        self,
        session: Session,
        message: Message,
        transition: Transition,
    ) -> Transition:
        self._note_new_work(session, message, transition)
        steps = tuple(
            sorted(message.steps, key=lambda item: int(item[0]))
        )
        changes: list[str] = []
        for index, text in steps:
            existing = session.plan.get(index)
            if existing is None:
                session.plan[index] = PlanStep(index=index, text=text)
                changes.append(f"新增步骤 {index}")
                continue
            if existing.text == text:
                changes.append(f"步骤 {index} 未变化")
            else:
                existing.text = text
                existing.completed = False
                changes.append(f"更新步骤 {index}（完成状态已重置）")

        summary = _summarize_steps(steps)
        self._touch(session, message, f"计划已更新：{summary}")
        transition.notices.append(
            Notice(
                kind=NoticeKind.PLAN,
                session_id=session.session_id,
                session_name=session.name,
                text=summary,
            )
        )
        transition.logs.append(
            f"会话「{session.name}」计划已更新：{'，'.join(changes)}。"
        )
        return transition

    def _handle_step_complete(
        self,
        session: Session,
        message: Message,
        transition: Transition,
    ) -> Transition:
        step = session.plan.get(message.step_index)
        if step is None:
            text = (
                f"会话「{session.name}」上报步骤 {message.step_index} 完成，"
                "但该步骤尚未在计划中登记。"
            )
            return self._protocol_error(message, transition, text)

        self._note_new_work(session, message, transition)
        step.completed = True
        detail = message.text.strip()
        if detail:
            last_text = f"步骤 {message.step_index} 已完成：{detail}"
        else:
            last_text = f"步骤 {message.step_index} 已完成：{step.text}"
        self._touch(session, message, last_text)

        notice_text = f"步骤 {message.step_index} 已完成：{step.text}"
        if detail:
            notice_text += f"\n{detail}"
        transition.notices.append(
            Notice(
                kind=NoticeKind.STEP_COMPLETE,
                session_id=session.session_id,
                session_name=session.name,
                text=notice_text,
            )
        )
        log = f"会话「{session.name}」步骤 {message.step_index} 已完成。"
        if all(item.completed for item in session.plan.values()):
            log += " 所有计划步骤已完成，等待 Agent 上报任务完成。"
        transition.logs.append(log)
        return transition

    def _handle_file_download(
        self,
        session: Session,
        message: Message,
        transition: Transition,
    ) -> Transition:
        self._note_new_work(session, message, transition)
        filename = PureWindowsPath(message.path).name
        self._touch(session, message, f"开始下载文件：{filename}")
        transition.download_requests.append(
            DownloadRequest(
                session_id=session.session_id,
                session_name=session.name,
                url=message.url,
                path=message.path,
            )
        )
        transition.logs.append(
            f"会话「{session.name}」开始下载文件：{message.url} -> "
            f"{message.path}。"
        )
        return transition

    def download_finished(
        self,
        *,
        session_id: str,
        url: str,
        path: str,
        success: bool,
        detail: str = "",
        bytes_written: int = 0,
    ) -> Transition:
        """Record a background file-download result on the UI thread."""

        transition = Transition()
        session = self._sessions.get(session_id)
        if session is None:
            transition.logs.append(
                f"文件下载{'完成' if success else '失败'}，但会话 "
                f"「{session_id}」已不在注册表中：{path}。"
            )
            return transition

        if success:
            text = f"文件下载完成：{path}"
            notice_kind = NoticeKind.DOWNLOAD_SUCCESS
            transition.logs.append(
                f"会话「{session.name}」文件下载完成：{path}"
                f"（{bytes_written} 字节）。"
            )
        else:
            text = f"文件下载失败：{path}"
            if detail:
                text += f"\n{detail}"
            notice_kind = NoticeKind.DOWNLOAD_FAILURE
            transition.logs.append(
                f"会话「{session.name}」文件下载失败：{url} -> {path}；{detail}"
            )
            if session.completed:
                session.completed = False
                transition.logs.append(
                    "已完成会话收到文件下载失败结果，已重新视为进行中。"
                )
                if self._deadline is not None:
                    self._deadline = None
                    self._countdown_source = None
                    self._schedule_wait_logged = False
                    transition.logs.append(
                        "文件下载失败，本次关机倒计时已取消。"
                    )

        session.last_text = text
        session.updated_at = datetime.now()
        transition.notices.append(
            Notice(
                kind=notice_kind,
                session_id=session.session_id,
                session_name=session.name,
                text=text,
            )
        )
        return transition

    def _note_new_work(
        self,
        session: Session,
        message: Message,
        transition: Transition,
    ) -> None:
        """Reopen a completed session and cancel a running countdown.

        The user explicitly chose that NOTIFY, PLAN, and STEP_COMPLETE also
        count as new work, in addition to ACTION and ERROR.  This keeps a
        chatty or still-working agent from being shut down mid-task.
        """

        reopened = session.completed
        if reopened:
            session.completed = False
            transition.logs.append(
                f"已完成会话收到{message.status_name}消息，已重新视为进行中。"
            )
        if self._deadline is not None:
            self._deadline = None
            self._countdown_source = None
            self._schedule_wait_logged = False
            transition.logs.append(
                f"收到{message.status_name}消息，本次关机倒计时已取消。"
            )

    def _touch(self, session: Session, message: Message, text: str | None = None) -> None:
        session.last_event = message.status
        session.last_text = message.text if text is None else text
        session.updated_at = datetime.now()

    @staticmethod
    def _protocol_error(
        message: Message,
        transition: Transition,
        text: str,
    ) -> Transition:
        transition.notices.append(
            Notice(
                kind=NoticeKind.PROTOCOL_ERROR,
                session_id=message.session_id,
                session_name="",
                text=text,
            )
        )
        transition.logs.append(text)
        return transition

    # ------------------------------------------------------------------- plan
    def set_planned(self, enabled: bool, now: float | None = None) -> Transition:
        current = time.monotonic() if now is None else now
        transition = Transition()
        if enabled == self._planned:
            return transition

        self._planned = enabled
        if enabled:
            transition.logs.append("已开启计划关机。")
            self._maybe_start_countdown(current, transition)
        else:
            transition.logs.append("已关闭计划关机。")
            if (
                self._deadline is not None
                and self._countdown_source == "plan"
            ):
                self._deadline = None
                self._countdown_source = None
                transition.logs.append("本次计划关机倒计时已取消。")
        return transition

    def set_countdown_seconds(self, seconds: int) -> Transition:
        transition = Transition()
        clamped = self._clamp_countdown(seconds)
        if clamped != seconds:
            transition.logs.append(
                f"倒计时已限制在 {MIN_COUNTDOWN_SECONDS}–"
                f"{MAX_COUNTDOWN_SECONDS} 秒范围内。"
            )
        if clamped != self._countdown_seconds:
            self._countdown_seconds = clamped
            transition.logs.append(f"关机倒计时设置为 {clamped} 秒（下次生效）。")
        return transition

    def remove_session(
        self, session_id: str, now: float | None = None
    ) -> Transition:
        current = time.monotonic() if now is None else now
        transition = Transition()
        session = self._sessions.pop(session_id, None)
        if session is None:
            return transition
        transition.logs.append(
            f"已移除会话「{session.name}」 ({session.session_id})。"
        )
        if self._deadline is None:
            self._maybe_start_countdown(current, transition)
            self._maybe_start_scheduled_countdown(current, transition)
        return transition

    def clear_completed(self, now: float | None = None) -> Transition:
        current = time.monotonic() if now is None else now
        transition = Transition()
        completed = [
            session_id
            for session_id, session in self._sessions.items()
            if session.completed
        ]
        for session_id in completed:
            session = self._sessions.pop(session_id)
            transition.logs.append(
                f"已清除已完成会话「{session.name}」 ({session.session_id})。"
            )
        if self._deadline is None:
            self._maybe_start_countdown(current, transition)
            self._maybe_start_scheduled_countdown(current, transition)
        return transition

    # --------------------------------------------------------------- schedule
    def set_schedule(
        self,
        enabled: bool,
        *,
        mode: ScheduleMode | str | None = None,
        target_wall: datetime | None = None,
        delay_seconds: float = 0,
        now: float | None = None,
    ) -> Transition:
        current = time.monotonic() if now is None else now
        transition = Transition()

        if not enabled:
            if not self._schedule_enabled:
                return transition
            self._clear_schedule()
            if self._countdown_source == "schedule":
                self._deadline = None
                self._countdown_source = None
                transition.logs.append("定时关机倒计时已取消。")
            transition.logs.append("已关闭定时关机。")
            return transition

        if mode is None or target_wall is None:
            raise ValueError("启用定时关机需要 mode 和 target_wall")
        try:
            schedule_mode = ScheduleMode(mode)
        except ValueError as exc:
            raise ValueError(f"未知的定时关机模式: {mode}") from exc
        if isinstance(delay_seconds, bool) or not isinstance(
            delay_seconds, (int, float)
        ):
            raise ValueError("定时关机延迟必须是数字秒")
        if not isinstance(target_wall, datetime):
            raise ValueError("定时关机目标必须是 datetime")

        delay = max(
            0,
            min(MAX_SCHEDULE_SECONDS, int(math.ceil(delay_seconds))),
        )
        if self._countdown_source == "schedule":
            self._deadline = None
            self._countdown_source = None
            transition.logs.append("原定时关机倒计时已取消。")

        self._schedule_enabled = True
        self._schedule_mode = schedule_mode
        self._schedule_target_wall = target_wall
        self._schedule_target = current + delay
        self._schedule_wait_logged = False
        mode_label = "指定时间" if schedule_mode is ScheduleMode.TIME else "延时"
        transition.logs.append(
            f"已启用定时关机（{mode_label}）："
            f"{target_wall:%Y-%m-%d %H:%M}。"
        )
        if delay <= 0:
            self._maybe_start_scheduled_countdown(current, transition)
        return transition

    def check_schedule(self, now: float | None = None) -> Transition:
        """Start the countdown when the target time is due and work is idle."""

        current = time.monotonic() if now is None else now
        transition = Transition()
        self._maybe_start_scheduled_countdown(current, transition)
        return transition

    def cancel_countdown(self, now: float | None = None) -> Transition:
        """Cancel whichever countdown is currently running."""

        if self._deadline is None:
            return Transition()

        source = self._countdown_source
        self._deadline = None
        self._countdown_source = None
        transition = Transition()
        if source == "plan":
            self._planned = False
            transition.logs.append("已取消计划关机倒计时。")
        elif source == "schedule":
            self._clear_schedule()
            transition.logs.append("已取消定时关机倒计时。")
        else:
            transition.logs.append("已取消关机倒计时。")
        return transition

    def _clear_schedule(self) -> None:
        self._schedule_enabled = False
        self._schedule_mode = None
        self._schedule_target_wall = None
        self._schedule_target = None
        self._schedule_wait_logged = False

    def _maybe_start_scheduled_countdown(
        self, now: float, transition: Transition
    ) -> None:
        if (
            not self._schedule_enabled
            or self._schedule_target is None
            or now < self._schedule_target
            or self._deadline is not None
        ):
            return
        if self._sessions and not self.all_complete:
            if not self._schedule_wait_logged:
                self._schedule_wait_logged = True
                transition.logs.append(
                    "定时关机时间已到，但仍有 "
                    f"{self.incomplete_count} 个会话未完成，"
                    "将等待会话完成后关机。"
                )
            return
        self._schedule_wait_logged = False
        self._start_countdown(
            now, "schedule", transition, allow_empty=True
        )

    def tick(self, now: float | None = None) -> Transition:
        current = time.monotonic() if now is None else now
        transition = Transition()
        if self._deadline is None or current < self._deadline:
            return transition

        source = self._countdown_source
        if any(not session.completed for session in self._sessions.values()):
            self._deadline = None
            self._countdown_source = None
            self._schedule_wait_logged = False
            transition.logs.append("仍有未完成会话，本次关机倒计时已取消。")
            return transition

        self._deadline = None
        self._countdown_source = None
        self._clear_schedule()
        if source == "plan":
            self._planned = False
            transition.logs.append("关机倒计时结束，正在请求系统关机。")
        elif source == "schedule":
            transition.logs.append(
                "定时关机倒计时结束，正在请求系统关机。"
            )
        else:
            transition.logs.append("关机倒计时结束，正在请求系统关机。")
        transition.shutdown_due = True
        return transition

    def _start_countdown(
        self,
        now: float,
        source: str,
        transition: Transition,
        *,
        allow_empty: bool = False,
    ) -> None:
        if self._deadline is not None:
            return
        if not allow_empty and not self._sessions:
            return
        if self._sessions and not self.all_complete:
            return

        self._deadline = now + self._countdown_seconds
        self._countdown_source = source
        if source == "schedule":
            if self._sessions:
                transition.logs.append(
                    "定时关机时间已到，所有会话已完成，将在 "
                    f"{self._countdown_seconds} 秒后关机。"
                )
            else:
                transition.logs.append(
                    "定时关机时间已到，当前没有已注册会话，将在 "
                    f"{self._countdown_seconds} 秒后关机。"
                )
        else:
            transition.logs.append(
                f"所有会话已完成，将在 {self._countdown_seconds} 秒后关机。"
            )

    def _maybe_start_countdown(
        self, now: float, transition: Transition
    ) -> None:
        if (
            self._planned
            and self._deadline is None
            and self._sessions
            and self.all_complete
        ):
            self._start_countdown(now, "plan", transition)

    @staticmethod
    def _clamp_countdown(seconds: int) -> int:
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise ValueError("倒计时必须是整数秒")
        return max(MIN_COUNTDOWN_SECONDS, min(MAX_COUNTDOWN_SECONDS, seconds))
