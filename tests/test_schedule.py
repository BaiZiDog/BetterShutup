from __future__ import annotations

from datetime import datetime, timedelta

from better_shutup.core import Coordinator, ScheduleMode
from better_shutup.protocol import Message, Status


def register(session_id: str = "s1") -> Message:
    return Message(
        status=Status.REGISTER,
        session_id=session_id,
        session_name="Agent",
    )


def complete(session_id: str = "s1") -> Message:
    return Message(status=Status.COMPLETE, session_id=session_id, text="done")


def test_delay_schedule_with_no_sessions_starts_and_fires() -> None:
    coordinator = Coordinator(10)
    target = datetime.now() + timedelta(minutes=5)
    transition = coordinator.set_schedule(
        True,
        mode=ScheduleMode.DELAY,
        target_wall=target,
        delay_seconds=300,
        now=0.0,
    )
    assert coordinator.schedule_enabled is True
    assert coordinator.deadline is None
    assert any("已启用定时关机" in line for line in transition.logs)

    assert coordinator.check_schedule(299.9).logs == []
    started = coordinator.check_schedule(300.0)
    assert coordinator.deadline == 310.0
    assert coordinator.countdown_source == "schedule"
    assert any("没有已注册会话" in line for line in started.logs)

    assert coordinator.tick(309.9).shutdown_due is False
    due = coordinator.tick(310.0)
    assert due.shutdown_due is True
    assert coordinator.schedule_enabled is False
    assert coordinator.countdown_source is None


def test_schedule_waits_for_registered_sessions_then_starts() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register(), now=0.0)
    target = datetime.now() + timedelta(minutes=1)
    coordinator.set_schedule(
        True,
        mode=ScheduleMode.DELAY,
        target_wall=target,
        delay_seconds=60,
        now=0.0,
    )

    waiting = coordinator.check_schedule(60.0)
    assert coordinator.deadline is None
    assert coordinator.schedule_enabled is True
    assert coordinator.schedule_waiting_for_sessions(60.0) is True
    assert any("1 个会话未完成" in line for line in waiting.logs)

    # The waiting message is logged once, not on every poll.
    assert coordinator.check_schedule(61.0).logs == []

    coordinator.handle_message(complete(), now=62.0)
    started = coordinator.check_schedule(62.1)
    assert coordinator.deadline == 72.1
    assert coordinator.countdown_source == "schedule"
    assert any("所有会话已完成" in line for line in started.logs)


def test_time_schedule_waits_until_target_even_when_idle() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    target = datetime.now() + timedelta(hours=1)
    coordinator.set_schedule(
        True,
        mode=ScheduleMode.TIME,
        target_wall=target,
        delay_seconds=3600,
        now=2.0,
    )
    assert coordinator.deadline is None
    coordinator.check_schedule(3601.0)
    assert coordinator.deadline is None
    coordinator.check_schedule(3602.0)
    assert coordinator.deadline == 3612.0
    assert coordinator.countdown_source == "schedule"


def test_cancel_schedule_cancels_scheduled_countdown_only() -> None:
    coordinator = Coordinator(10)
    coordinator.set_schedule(
        True,
        mode=ScheduleMode.DELAY,
        target_wall=datetime.now(),
        delay_seconds=0,
        now=0.0,
    )
    assert coordinator.deadline == 10.0
    transition = coordinator.set_schedule(False)
    assert coordinator.deadline is None
    assert coordinator.schedule_enabled is False
    assert coordinator.countdown_source is None
    assert any("定时关机倒计时已取消" in line for line in transition.logs)


def test_disabling_plan_does_not_cancel_schedule_countdown() -> None:
    coordinator = Coordinator(10)
    coordinator.set_planned(True, now=0.0)
    coordinator.set_schedule(
        True,
        mode=ScheduleMode.DELAY,
        target_wall=datetime.now(),
        delay_seconds=0,
        now=0.0,
    )
    assert coordinator.deadline is not None
    assert coordinator.countdown_source == "schedule"

    coordinator.set_planned(False, now=1.0)
    assert coordinator.deadline is not None
    assert coordinator.countdown_source == "schedule"

    transition = coordinator.cancel_countdown(now=2.0)
    assert coordinator.deadline is None
    assert coordinator.schedule_enabled is False
    assert any("已取消定时关机倒计时" in line for line in transition.logs)


def test_cancel_plan_countdown_leaves_schedule_enabled() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.countdown_source == "plan"
    coordinator.set_schedule(
        True,
        mode=ScheduleMode.DELAY,
        target_wall=datetime.now() + timedelta(hours=1),
        delay_seconds=3600,
        now=2.0,
    )
    transition = coordinator.cancel_countdown(now=3.0)
    assert coordinator.deadline is None
    assert coordinator.planned is False
    assert coordinator.schedule_enabled is True
    assert any("取消计划关机" in line for line in transition.logs)


def test_plan_countdown_due_disarms_schedule() -> None:
    coordinator = Coordinator(10)
    coordinator.handle_message(register(), now=0.0)
    coordinator.handle_message(complete(), now=1.0)
    coordinator.set_planned(True, now=2.0)
    assert coordinator.deadline == 12.0
    coordinator.set_schedule(
        True,
        mode=ScheduleMode.DELAY,
        target_wall=datetime.now() + timedelta(hours=1),
        delay_seconds=3600,
        now=2.0,
    )
    due = coordinator.tick(12.0)
    assert due.shutdown_due is True
    assert coordinator.schedule_enabled is False


def test_new_session_cancels_scheduled_countdown_then_waits() -> None:
    coordinator = Coordinator(10)
    coordinator.set_schedule(
        True,
        mode=ScheduleMode.DELAY,
        target_wall=datetime.now(),
        delay_seconds=0,
        now=0.0,
    )
    assert coordinator.countdown_source == "schedule"

    coordinator.handle_message(register(), now=1.0)
    assert coordinator.deadline is None
    assert coordinator.schedule_enabled is True
    assert coordinator.schedule_waiting_for_sessions(1.0) is True

    coordinator.handle_message(complete(), now=2.0)
    coordinator.check_schedule(2.1)
    assert coordinator.deadline == 12.1
    assert coordinator.countdown_source == "schedule"
