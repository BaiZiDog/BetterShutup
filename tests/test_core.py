from __future__ import annotations

import pytest

from better_shutup.core import (
    Coordinator,
    MAX_COUNTDOWN_SECONDS,
    MIN_COUNTDOWN_SECONDS,
    NoticeKind,
)
from better_shutup.protocol import Message, Status


def register(session_id: str = "s1", name: str = "Agent") -> Message:
    return Message(
        status=Status.REGISTER,
        session_id=session_id,
        session_name=name,
    )


def complete(session_id: str = "s1", text: str = "done") -> Message:
    return Message(
        status=Status.COMPLETE,
        session_id=session_id,
        text=text,
    )


def action(session_id: str = "s1", text: str = "need input") -> Message:
    return Message(
        status=Status.ACTION,
        session_id=session_id,
        text=text,
    )


def error(session_id: str = "s1", text: str = "boom") -> Message:
    return Message(
        status=Status.ERROR,
        session_id=session_id,
        text=text,
    )


def test_register_adds_session_without_notification() -> None:
    coordinator = Coordinator()
    transition = coordinator.handle_message(register(), now=10.0)
    sessions = coordinator.sessions
    assert len(sessions) == 1
    assert sessions[0].session_id == "s1"
    assert sessions[0].name == "Agent"
    assert sessions[0].completed is False
    assert transition.notices == []
    assert "注册新会话" in transition.logs[0]


@pytest.mark.parametrize("attention_message", [action, error])
def test_reregister_existing_id_restores_normal_without_notification(
    attention_message,
) -> None:
    coordinator = Coordinator(30)
    coordinator.handle_message(register(), now=0.0)
    warned = coordinator.handle_message(attention_message(text="attention"), now=1.0)
    assert warned.notices

    transition = coordinator.handle_message(
        register("s1", "Restored Agent"), now=2.0
    )
    session = coordinator.sessions[0]
    assert len(coordinator.sessions) == 1
    assert session.name == "Restored Agent"
    assert session.completed is False
    assert session.last_event is Status.REGISTER
    assert session.last_text == ""
    assert transition.notices == []
    assert any("恢复正常状态" in log for log in transition.logs)


def test_complete_without_plan_only_marks_complete() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=10.0)
    transition = coordinator.handle_message(complete(text="finished"), now=20.0)
    assert coordinator.sessions[0].completed is True
    assert coordinator.deadline is None
    assert transition.notices[0].kind is NoticeKind.COMPLETE
    assert transition.notices[0].text == "finished"
    assert transition.shutdown_due is False


def test_complete_unknown_session_is_protocol_error() -> None:
    coordinator = Coordinator()
    transition = coordinator.handle_message(complete("missing"), now=1.0)
    assert not coordinator.has_sessions
    assert transition.notices[0].kind is NoticeKind.PROTOCOL_ERROR
    assert "未注册" in transition.notices[0].text


def test_action_and_error_do_not_complete() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=1.0)
    action_transition = coordinator.handle_message(action(text="pick one"), now=2.0)
    error_transition = coordinator.handle_message(error(text="bad"), now=3.0)
    assert coordinator.sessions[0].completed is False
    assert action_transition.notices[0].kind is NoticeKind.ACTION
    assert error_transition.notices[0].kind is NoticeKind.ERROR


@pytest.mark.parametrize("message_factory", [action, error])
def test_attention_after_completion_reopens_and_cancels_countdown(
    message_factory,
) -> None:
    coordinator = Coordinator(20)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline is not None

    transition = coordinator.handle_message(message_factory(text="late"), now=3.0)
    session = coordinator.sessions[0]
    assert session.completed is False
    assert coordinator.deadline is None
    assert coordinator.planned is True
    assert transition.notices
    assert any("取消" in log for log in transition.logs)

    coordinator.handle_message(complete(), now=4.0)
    assert coordinator.deadline == 24.0


def test_duplicate_registration_reopens_completed_session() -> None:
    coordinator = Coordinator(60)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline == 62.0

    transition = coordinator.handle_message(register("s1", "Agent v2"), now=3.0)
    session = coordinator.sessions[0]
    assert session.completed is False
    assert session.name == "Agent v2"
    assert session.last_event is Status.REGISTER
    assert coordinator.deadline is None
    assert coordinator.planned is True
    assert transition.notices == []
    assert any("正常状态" in log for log in transition.logs)
    assert any("取消" in log for log in transition.logs)


def test_plan_arm_without_sessions_waits() -> None:
    coordinator = Coordinator(30)
    transition = coordinator.set_planned(True, now=100.0)
    assert coordinator.planned is True
    assert coordinator.deadline is None
    assert any("开启" in log for log in transition.logs)

    coordinator.handle_message(register(), now=101.0)
    assert coordinator.deadline is None
    coordinator.handle_message(complete(), now=102.0)
    assert coordinator.deadline == 132.0


def test_plan_arm_with_all_complete_starts_countdown() -> None:
    coordinator = Coordinator(25)
    coordinator.handle_message(register(), now=1.0)
    coordinator.handle_message(complete(), now=2.0)
    transition = coordinator.set_planned(True, now=3.0)
    assert coordinator.deadline == 28.0
    assert any("25 秒" in log for log in transition.logs)


def test_countdown_cancelled_by_disarm() -> None:
    coordinator = Coordinator(25)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    transition = coordinator.set_planned(False, now=3.0)
    assert coordinator.deadline is None
    assert coordinator.planned is False
    assert any("取消" in log for log in transition.logs)


def test_new_session_cancels_countdown_but_plan_stays_armed() -> None:
    coordinator = Coordinator(20)
    coordinator.handle_message(register("s1"), now=0.0)
    coordinator.handle_message(complete("s1"), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline is not None

    coordinator.handle_message(register("s2", "Second"), now=3.0)
    assert coordinator.deadline is None
    assert coordinator.planned is True
    assert coordinator.incomplete_count == 1

    coordinator.handle_message(complete("s2"), now=4.0)
    assert coordinator.deadline == 24.0


def test_tick_fires_once_and_disarms() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline == 12.0

    assert coordinator.tick(11.999).shutdown_due is False
    due = coordinator.tick(12.0)
    assert due.shutdown_due is True
    assert coordinator.deadline is None
    assert coordinator.planned is False

    again = coordinator.tick(13.0)
    assert again.shutdown_due is False


def test_tick_cancels_if_session_reopened() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    # Simulate a reopened active session while leaving the deadline alive.
    coordinator._deadline = 2.0  # type: ignore[attr-defined]
    coordinator.sessions[0].completed = False
    transition = coordinator.tick(100.0)
    assert transition.shutdown_due is False
    assert coordinator.deadline is None
    assert any("未完成" in log for log in transition.logs)


def test_no_sessions_never_starts_countdown() -> None:
    coordinator = Coordinator(10)
    coordinator.set_planned(True, now=0.0)
    assert coordinator.deadline is None


def test_removing_active_session_can_satisfy_condition() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register("s1", "Done"), now=0.0)
    coordinator.handle_message(register("s2", "Stale"), now=0.0)
    coordinator.handle_message(complete("s1"), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline is None
    coordinator.remove_session("s2", now=3.0)
    assert coordinator.deadline == 13.0


def test_removing_sessions_does_not_cancel_active_countdown() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    deadline = coordinator.deadline
    coordinator.remove_session("s1", now=3.0)
    assert coordinator.deadline == deadline
    assert coordinator.tick(12.0).shutdown_due is True


def test_clear_completed_can_start_countdown() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register("s1"), now=0.0)
    coordinator.handle_message(register("s2"), now=0.0)
    coordinator.handle_message(complete("s1"), now=1.0)
    coordinator.handle_message(complete("s2"), now=2.0)
    coordinator.clear_completed(now=3.0)
    assert not coordinator.has_sessions
    coordinator.set_planned(True, now=4.0)
    assert coordinator.deadline is None


def test_seconds_remaining() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=0.0)
    coordinator.set_planned(True, now=0.0)
    assert coordinator.seconds_remaining(0.0) == 10
    assert coordinator.seconds_remaining(9.2) == 1
    assert coordinator.seconds_remaining(10.0) == 0
    assert coordinator.seconds_remaining(20.0) == 0


def test_countdown_seconds_clamped() -> None:
    coordinator = Coordinator(1)
    assert coordinator.countdown_seconds == MIN_COUNTDOWN_SECONDS
    coordinator.set_countdown_seconds(99_999)
    assert coordinator.countdown_seconds == MAX_COUNTDOWN_SECONDS
    coordinator.set_countdown_seconds(30)
    assert coordinator.countdown_seconds == 30


def test_invalid_countdown_rejected() -> None:
    coordinator = Coordinator()
    with pytest.raises(ValueError):
        coordinator.set_countdown_seconds("abc")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        coordinator.set_countdown_seconds("30")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        coordinator.set_countdown_seconds(7.9)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        coordinator.set_countdown_seconds(True)  # type: ignore[arg-type]
