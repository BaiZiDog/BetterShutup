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


def resume(session_id: str = "s1", text: str = "") -> Message:
    return Message(
        status=Status.RESUME,
        session_id=session_id,
        text=text,
    )


def notify(session_id: str = "s1", text: str = "hello") -> Message:
    return Message(
        status=Status.NOTIFY,
        session_id=session_id,
        text=text,
    )


def plan(
    session_id: str = "s1",
    steps: tuple[tuple[str, str], ...] = (("1", "one"),),
) -> Message:
    return Message(
        status=Status.PLAN,
        session_id=session_id,
        steps=steps,
    )


def step_done(
    index: str = "1",
    session_id: str = "s1",
    text: str = "",
) -> Message:
    return Message(
        status=Status.STEP_COMPLETE,
        session_id=session_id,
        step_index=index,
        text=text,
    )


def download(
    session_id: str = "s1",
    url: str = "https://example.com/file.bin",
    path: str = r"C:\temp\file.bin",
) -> Message:
    return Message(
        status=Status.FILE_DOWNLOAD,
        session_id=session_id,
        url=url,
        path=path,
    )


def test_register_adds_session_without_notification() -> None:
    coordinator = Coordinator()
    transition = coordinator.handle_message(register(), now=10.0)
    sessions = coordinator.sessions
    assert len(sessions) == 1
    assert sessions[0].session_id == "s1"
    assert sessions[0].name == "Agent"
    assert sessions[0].completed is False
    assert sessions[0].action_needed is False
    assert sessions[0].has_error is False
    assert transition.notices == []
    assert "注册新会话" in transition.logs[0]


def test_reregister_after_action_preserves_action_state() -> None:
    coordinator = Coordinator(30)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(action(text="please answer"), now=1.0)

    transition = coordinator.handle_message(
        register("s1", "Restored Agent"), now=2.0
    )
    session = coordinator.sessions[0]
    assert len(coordinator.sessions) == 1
    assert session.name == "Restored Agent"
    assert session.completed is False
    assert session.action_needed is True
    assert session.last_event is Status.ACTION
    assert session.last_text == "please answer"
    assert transition.notices == []
    assert transition.dismiss_action_session_ids == []
    assert any("需要操作状态保留" in log for log in transition.logs)


def test_reregister_does_not_clear_error_state() -> None:
    coordinator = Coordinator(30)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(error(text="still broken"), now=1.0)

    transition = coordinator.handle_message(register("s1", "Updated"), now=2.0)
    session = coordinator.sessions[0]
    assert session.has_error is True
    assert session.action_needed is False
    assert session.last_event is Status.ERROR
    assert session.last_text == "still broken"
    assert transition.notices == []
    assert transition.dismiss_action_session_ids == []
    assert any("错误状态保留" in log for log in transition.logs)


def test_resume_clears_only_action_state() -> None:
    coordinator = Coordinator(30)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(action(text="please answer"), now=1.0)

    transition = coordinator.handle_message(
        resume(text="用户已回答"), now=2.0
    )
    session = coordinator.sessions[0]
    assert session.action_needed is False
    assert session.has_error is False
    assert session.completed is False
    assert session.last_event is Status.RESUME
    assert session.last_text == "用户已回答"
    assert transition.notices == []
    assert transition.dismiss_action_session_ids == ["s1"]
    assert any("需要操作状态已清除" in log for log in transition.logs)


def test_resume_does_not_clear_error_state() -> None:
    coordinator = Coordinator(30)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(error(text="still broken"), now=1.0)

    transition = coordinator.handle_message(resume(), now=2.0)
    session = coordinator.sessions[0]
    assert session.has_error is True
    assert session.action_needed is False
    assert session.last_text == "已确认用户操作"
    assert transition.notices == []
    assert any("错误状态保留" in log for log in transition.logs)


def test_resume_completed_session_preserves_completion_and_countdown() -> None:
    coordinator = Coordinator(60)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline == 62.0

    transition = coordinator.handle_message(resume(), now=3.0)
    session = coordinator.sessions[0]
    assert session.completed is True
    assert session.last_event is Status.RESUME
    assert coordinator.deadline == 62.0
    assert coordinator.planned is True
    assert transition.notices == []
    assert transition.dismiss_action_session_ids == ["s1"]
    assert any("不影响完成状态" in log for log in transition.logs)


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
    session = coordinator.sessions[0]
    assert session.completed is False
    assert session.action_needed is False
    assert session.has_error is True
    assert action_transition.notices[0].kind is NoticeKind.ACTION
    assert error_transition.notices[0].kind is NoticeKind.ERROR


def test_notify_is_informational_and_does_not_clear_attention() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(action(text="pick one"), now=1.0)
    transition = coordinator.handle_message(notify(text="进度更新"), now=2.0)
    session = coordinator.sessions[0]
    assert session.completed is False
    assert session.action_needed is True
    assert session.last_event is Status.NOTIFY
    assert session.last_text == "进度更新"
    assert transition.notices[0].kind is NoticeKind.NOTIFY
    assert transition.notices[0].text == "进度更新"
    assert transition.dismiss_action_session_ids == []


def test_notify_does_not_clear_error_state() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(error(text="bad"), now=1.0)
    coordinator.handle_message(notify(text="still working"), now=2.0)
    session = coordinator.sessions[0]
    assert session.has_error is True
    assert session.action_needed is False
    assert session.last_event is Status.NOTIFY


@pytest.mark.parametrize("message_factory", [action, error, notify])
def test_new_work_after_completion_reopens_and_cancels_countdown(
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
    assert any("重新视为进行中" in log for log in transition.logs)
    assert any("倒计时已取消" in log for log in transition.logs)

    coordinator.handle_message(complete(), now=4.0)
    assert coordinator.deadline == 24.0


def test_plan_after_completion_reopens_and_cancels_countdown() -> None:
    coordinator = Coordinator(20)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline is not None

    transition = coordinator.handle_message(
        plan(steps=(("1", "new work"),)), now=3.0
    )
    session = coordinator.sessions[0]
    assert session.completed is False
    assert coordinator.deadline is None
    assert transition.notices[0].kind is NoticeKind.PLAN
    assert session.plan["1"].text == "new work"


def test_step_complete_after_completion_reopens_and_cancels_countdown() -> None:
    coordinator = Coordinator(20)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(plan(steps=(("1", "work"),)), now=0.5)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline is not None

    transition = coordinator.handle_message(step_done("1"), now=3.0)
    session = coordinator.sessions[0]
    assert session.completed is False
    assert coordinator.deadline is None
    assert transition.notices[0].kind is NoticeKind.STEP_COMPLETE


def test_plan_creates_and_upserts_steps() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=0.0)
    created = coordinator.handle_message(
        plan(steps=(("2", "two"), ("1", "one"))), now=1.0
    )
    session = coordinator.sessions[0]
    assert [step.index for step in session.plan_steps] == ["1", "2"]
    assert session.completed_step_count == 0
    assert session.plan_progress == (0, 2)
    assert created.notices[0].kind is NoticeKind.PLAN
    assert created.notices[0].text == "1. one；2. two"
    assert "计划已更新" in session.last_text

    coordinator.handle_message(step_done("2"), now=2.0)
    assert session.plan["2"].completed is True

    updated = coordinator.handle_message(
        plan(steps=(("2", "two v2"), ("3", "three"))), now=3.0
    )
    steps = {step.index: step for step in session.plan_steps}
    assert [step.index for step in session.plan_steps] == ["1", "2", "3"]
    assert steps["2"].text == "two v2"
    assert steps["2"].completed is False
    assert steps["3"].text == "three"
    assert updated.notices[0].kind is NoticeKind.PLAN


def test_plan_same_text_preserves_step_completion() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(plan(steps=(("1", "one"),)), now=1.0)
    coordinator.handle_message(step_done("1"), now=2.0)
    assert coordinator.sessions[0].plan["1"].completed is True

    transition = coordinator.handle_message(
        plan(steps=(("1", "one"),)), now=3.0
    )
    assert coordinator.sessions[0].plan["1"].completed is True
    assert any("未变化" in log for log in transition.logs)


def test_plan_update_preserves_action_state() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(action(text="pick one"), now=1.0)
    transition = coordinator.handle_message(
        plan(steps=(("1", "one"),)), now=2.0
    )
    session = coordinator.sessions[0]
    assert session.action_needed is True
    assert transition.dismiss_action_session_ids == []
    assert [notice.kind for notice in transition.notices] == [NoticeKind.PLAN]


def test_step_complete_requires_existing_plan_step() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=0.0)
    transition = coordinator.handle_message(step_done("1"), now=1.0)
    session = coordinator.sessions[0]
    assert session.last_event is Status.REGISTER
    assert session.plan == {}
    assert transition.notices[0].kind is NoticeKind.PROTOCOL_ERROR
    assert "尚未在计划中登记" in transition.notices[0].text


def test_step_complete_marks_step_but_does_not_complete_session() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(
        plan(steps=(("1", "one"), ("2", "two"))), now=1.0
    )

    first = coordinator.handle_message(
        step_done("1", text="细节完成"), now=2.0
    )
    session = coordinator.sessions[0]
    assert session.plan["1"].completed is True
    assert session.plan["2"].completed is False
    assert session.completed is False
    assert first.notices[0].kind is NoticeKind.STEP_COMPLETE
    assert "步骤 1 已完成" in first.notices[0].text
    assert "细节完成" in first.notices[0].text
    assert "所有计划步骤" not in " ".join(first.logs)

    second = coordinator.handle_message(step_done("2"), now=3.0)
    assert session.completed is False
    assert any("所有计划步骤已完成" in log for log in second.logs)


def test_file_download_starts_request_and_counts_as_new_work() -> None:
    coordinator = Coordinator(20)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline is not None

    transition = coordinator.handle_message(download(), now=3.0)
    session = coordinator.sessions[0]
    assert session.completed is False
    assert coordinator.deadline is None
    assert transition.notices == []
    assert len(transition.download_requests) == 1
    request = transition.download_requests[0]
    assert request.session_id == "s1"
    assert request.url == "https://example.com/file.bin"
    assert request.path == r"C:\temp\file.bin"
    assert session.last_event is Status.FILE_DOWNLOAD
    assert "开始下载文件" in session.last_text
    assert any("开始下载文件" in log for log in transition.logs)


def test_file_download_success_notice() -> None:
    coordinator = Coordinator()
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(download(), now=1.0)

    transition = coordinator.download_finished(
        session_id="s1",
        url="https://example.com/file.bin",
        path=r"C:\temp\file.bin",
        success=True,
        bytes_written=1234,
    )
    session = coordinator.sessions[0]
    assert session.completed is False
    assert session.has_error is False
    assert session.last_text == r"文件下载完成：C:\temp\file.bin"
    assert transition.notices[0].kind is NoticeKind.DOWNLOAD_SUCCESS
    assert "file.bin" in transition.notices[0].text
    assert any("1234" in log for log in transition.logs)


def test_file_download_failure_reopens_completed_session_and_cancels_countdown() -> None:
    coordinator = Coordinator(20)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(download(), now=1.0)
    coordinator.handle_message(complete(), now=2.0)
    coordinator.set_planned(True, now=3.0)
    assert coordinator.deadline is not None

    transition = coordinator.download_finished(
        session_id="s1",
        url="https://example.com/file.bin",
        path=r"C:\temp\file.bin",
        success=False,
        detail="HTTP 500",
        bytes_written=5,
    )
    session = coordinator.sessions[0]
    assert session.completed is False
    assert session.has_error is False
    assert coordinator.deadline is None
    assert transition.notices[0].kind is NoticeKind.DOWNLOAD_FAILURE
    assert "HTTP 500" in transition.notices[0].text
    assert any("重新视为进行中" in log for log in transition.logs)
    assert any("倒计时已取消" in log for log in transition.logs)


def test_file_download_result_for_unknown_session_only_logs() -> None:
    coordinator = Coordinator()
    transition = coordinator.download_finished(
        session_id="missing",
        url="https://example.com/file.bin",
        path=r"C:\temp\file.bin",
        success=True,
    )
    assert transition.notices == []
    assert any("已不在注册表" in log for log in transition.logs)


def test_reregister_completed_session_preserves_completion_and_countdown() -> None:
    coordinator = Coordinator(60)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline == 62.0

    transition = coordinator.handle_message(register("s1", "Agent v2"), now=3.0)
    session = coordinator.sessions[0]
    assert session.completed is True
    assert session.name == "Agent v2"
    assert coordinator.deadline == 62.0
    assert coordinator.planned is True
    assert transition.notices == []
    assert transition.dismiss_action_session_ids == []
    assert any("保持已完成状态" in log for log in transition.logs)
    assert not any("倒计时已取消" in log for log in transition.logs)


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
