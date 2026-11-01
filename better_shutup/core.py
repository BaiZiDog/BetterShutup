"""Pure session registry and scheduled-shutdown state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
import time

from .protocol import Message, Status

MIN_COUNTDOWN_SECONDS = 5
MAX_COUNTDOWN_SECONDS = 3600
DEFAULT_COUNTDOWN_SECONDS = 60


class NoticeKind(str, Enum):
    COMPLETE = "complete"
    ACTION = "action"
    ERROR = "error"
    PROTOCOL_ERROR = "protocol_error"


@dataclass(slots=True)
class Session:
    session_id: str
    name: str
    completed: bool = False
    last_event: Status = Status.REGISTER
    last_text: str = ""
    updated_at: datetime = field(default_factory=datetime.now)


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

        session.last_event = message.status
        session.last_text = message.text
        session.updated_at = datetime.now()

        if message.status in (Status.ACTION, Status.ERROR) and session.completed:
            # Attention/error after completion means the session is no longer
            # safely finished.  Reopen it so planned shutdown cannot proceed
            # while a human decision or a fix is still outstanding.
            session.completed = False
            if self._deadline is not None:
                self._deadline = None
                transition.logs.append(
                    "已完成会话收到需要操作/错误消息，本次关机倒计时已取消。"
                )

        if message.status is Status.COMPLETE:
            session.completed = True
            transition.notices.append(
                Notice(
                    kind=NoticeKind.COMPLETE,
                    session_id=session.session_id,
                    session_name=session.name,
                    text=message.text,
                )
            )
            transition.logs.append(
                f"会话「{session.name}」完成任务。"
            )
            self._maybe_start_countdown(current, transition)
        elif message.status is Status.ACTION:
            transition.notices.append(
                Notice(
                    kind=NoticeKind.ACTION,
                    session_id=session.session_id,
                    session_name=session.name,
                    text=message.text,
                )
            )
            transition.logs.append(
                f"会话「{session.name}」需要操作。"
            )
        elif message.status is Status.ERROR:
            transition.notices.append(
                Notice(
                    kind=NoticeKind.ERROR,
                    session_id=session.session_id,
                    session_name=session.name,
                    text=message.text,
                )
            )
            transition.logs.append(
                f"会话「{session.name}」报告错误。"
            )

        return transition

    def _handle_register(self, message: Message, transition: Transition) -> None:
        existing = self._sessions.get(message.session_id)
        if existing is None:
            session = Session(
                session_id=message.session_id,
                name=message.session_name,
            )
            self._sessions[message.session_id] = session
            transition.logs.append(
                f"注册会话「{session.name}」 ({session.session_id})。"
            )
        else:
            was_completed = existing.completed
            existing.name = message.session_name
            existing.completed = False
            existing.last_event = Status.REGISTER
            existing.last_text = ""
            existing.updated_at = datetime.now()
            if was_completed:
                transition.logs.append(
                    f"会话「{existing.name}」重新注册，已重新打开。"
                )
            else:
                transition.logs.append(
                    f"会话「{existing.name}」更新注册信息。"
                )

        if self._deadline is not None:
            self._deadline = None
            transition.logs.append("新会话到达，本次关机倒计时已取消。")

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
            if self._deadline is not None:
                self._deadline = None
                transition.logs.append("本次关机倒计时已取消。")
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
        return transition

    def tick(self, now: float | None = None) -> Transition:
        current = time.monotonic() if now is None else now
        transition = Transition()
        if self._deadline is None or current < self._deadline:
            return transition

        if not self._planned:
            self._deadline = None
            return transition

        if any(not session.completed for session in self._sessions.values()):
            self._deadline = None
            transition.logs.append("仍有未完成会话，本次关机倒计时已取消。")
            return transition

        self._deadline = None
        self._planned = False
        transition.shutdown_due = True
        transition.logs.append("关机倒计时结束，正在请求系统关机。")
        return transition

    def _maybe_start_countdown(
        self, now: float, transition: Transition
    ) -> None:
        if (
            self._planned
            and self._deadline is None
            and self._sessions
            and self.all_complete
        ):
            self._deadline = now + self._countdown_seconds
            transition.logs.append(
                f"所有会话已完成，将在 {self._countdown_seconds} 秒后关机。"
            )

    @staticmethod
    def _clamp_countdown(seconds: int) -> int:
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            raise ValueError("倒计时必须是整数秒")
        return max(MIN_COUNTDOWN_SECONDS, min(MAX_COUNTDOWN_SECONDS, seconds))
