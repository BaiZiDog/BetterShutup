from __future__ import annotations

import json

import pytest

from better_shutup.protocol import (
    HEADER_SIZE,
    MAX_BODY_SIZE,
    MAX_PLAN_INDEX,
    MAX_PLAN_STEPS_PER_MESSAGE,
    MAX_PLAN_STEP_TEXT_LENGTH,
    Message,
    ProtocolError,
    Status,
    build_message,
    decode_frame,
    encode_message,
)


def test_status_codes_are_four_bit_binary() -> None:
    expected = {
        Status.REGISTER: 0b0000,
        Status.COMPLETE: 0b0001,
        Status.ACTION: 0b0010,
        Status.ERROR: 0b0011,
        Status.RESUME: 0b0100,
        Status.NOTIFY: 0b0101,
        Status.PLAN: 0b0110,
        Status.STEP_COMPLETE: 0b0111,
    }
    for status, code in expected.items():
        assert int(status) == code
        assert status.binary == f"{code:04b}"


def test_register_frame_layout_and_roundtrip() -> None:
    frame = encode_message(
        Status.REGISTER,
        {"session_name": "Claude Code", "session_id": "abc"},
    )
    body = frame[HEADER_SIZE:]
    assert frame[0] == 0b0000
    assert int.from_bytes(frame[1:4], "big") == len(body)
    payload = json.loads(body.decode("utf-8"))
    assert payload == {"session_name": "Claude Code", "session_id": "abc"}
    message = decode_frame(frame)
    assert message.status is Status.REGISTER
    assert message.session_id == "abc"
    assert message.session_name == "Claude Code"


@pytest.mark.parametrize("status", [Status.COMPLETE, Status.ACTION, Status.ERROR, Status.NOTIFY])
def test_text_status_codes(status: Status) -> None:
    field = {
        Status.COMPLETE: "message",
        Status.ACTION: "instruction",
        Status.ERROR: "error",
        Status.NOTIFY: "message",
    }[status]
    frame = encode_message(status, {"session_id": "id-1", field: "内容"})
    assert frame[0] == int(status)
    assert int.from_bytes(frame[1:4], "big") == len(frame) - HEADER_SIZE
    decoded = decode_frame(frame)
    assert decoded.status is status
    assert decoded.text == "内容"
    assert decoded.text_field == field


def test_resume_and_step_complete_frames() -> None:
    resume = encode_message(
        Status.RESUME,
        {"session_id": "id-1", "message": "用户已回答"},
    )
    assert resume[0] == 0x04
    decoded_resume = decode_frame(resume)
    assert decoded_resume.status is Status.RESUME
    assert decoded_resume.text == "用户已回答"

    bare_resume = encode_message(Status.RESUME, {"session_id": "id-1"})
    assert bare_resume[0] == 0x04
    assert decode_frame(bare_resume).text == ""

    step = encode_message(
        Status.STEP_COMPLETE,
        {"session_id": "id-1", "step_index": "2", "message": "完成子任务"},
    )
    assert step[0] == 0x07
    decoded_step = decode_frame(step)
    assert decoded_step.status is Status.STEP_COMPLETE
    assert decoded_step.step_index == "2"
    assert decoded_step.text == "完成子任务"

    bare_step = encode_message(
        Status.STEP_COMPLETE,
        {"session_id": "id-1", "step_index": "1"},
    )
    assert decode_frame(bare_step).text == ""


def test_plan_frame_is_top_level_index_mapping() -> None:
    frame = encode_message(
        Status.PLAN,
        {"session_id": "id-1", "2": "修改实现", "1": "分析代码"},
    )
    assert frame[0] == 0x06
    payload = json.loads(frame[HEADER_SIZE:].decode("utf-8"))
    assert payload == {
        "session_id": "id-1",
        "1": "分析代码",
        "2": "修改实现",
    }
    decoded = decode_frame(frame)
    assert decoded.status is Status.PLAN
    assert decoded.steps == (("1", "分析代码"), ("2", "修改实现"))


def test_length_counts_utf8_bytes_not_characters() -> None:
    frame = encode_message(
        Status.COMPLETE,
        {"session_id": "会话-id", "message": "中文消息"},
    )
    body = frame[HEADER_SIZE:]
    assert int.from_bytes(frame[1:4], "big") == len(body)
    assert len(body) > len(body.decode("utf-8"))
    assert decode_frame(frame).text == "中文消息"


def test_rejects_reserved_header_bits() -> None:
    frame = encode_message(
        Status.COMPLETE,
        {"session_id": "id", "message": "x"},
    )
    for bit in (0x10, 0x20, 0x40, 0x80, 0xF0):
        corrupted = bytes([frame[0] | bit]) + frame[1:]
        with pytest.raises(ProtocolError, match="保留位"):
            decode_frame(corrupted)


def test_rejects_undefined_status_codes() -> None:
    body = b'{"session_id":"id","message":"x"}'
    for status in range(0x08, 0x10):
        frame = bytes([status]) + len(body).to_bytes(3, "big") + body
        with pytest.raises(ProtocolError, match="未定义"):
            decode_frame(frame)


def test_rejects_short_frame() -> None:
    with pytest.raises(ProtocolError, match="不足"):
        decode_frame(b"\x00\x00\x00")


def test_rejects_length_mismatch() -> None:
    frame = encode_message(
        Status.COMPLETE,
        {"session_id": "id", "message": "hello"},
    )
    bad = frame[:1] + (len(frame) - HEADER_SIZE + 1).to_bytes(3, "big") + frame[4:]
    with pytest.raises(ProtocolError, match="长度不符"):
        decode_frame(bad)


def test_rejects_trailing_data() -> None:
    frame = encode_message(
        Status.COMPLETE,
        {"session_id": "id", "message": "hello"},
    )
    with pytest.raises(ProtocolError, match="长度不符"):
        decode_frame(frame + b"x")


def test_rejects_empty_body() -> None:
    frame = b"\x01\x00\x00\x00"
    with pytest.raises(ProtocolError, match="不能为空"):
        decode_frame(frame)


def test_rejects_invalid_utf8_and_json() -> None:
    body = b"\xff\xfe"
    frame = bytes([1]) + len(body).to_bytes(3, "big") + body
    with pytest.raises(ProtocolError, match="UTF-8"):
        decode_frame(frame)

    body = b"not json"
    frame = bytes([1]) + len(body).to_bytes(3, "big") + body
    with pytest.raises(ProtocolError, match="JSON"):
        decode_frame(frame)


def test_rejects_non_object_json() -> None:
    body = b"[1,2,3]"
    frame = bytes([1]) + len(body).to_bytes(3, "big") + body
    with pytest.raises(ProtocolError, match="对象"):
        decode_frame(frame)


def test_rejects_missing_or_wrong_field_types() -> None:
    with pytest.raises(ProtocolError, match="缺少字段"):
        build_message(Status.COMPLETE, {"session_id": "id"})
    with pytest.raises(ProtocolError, match="必须是字符串"):
        build_message(
            Status.COMPLETE,
            {"session_id": "id", "message": 123},
        )
    with pytest.raises(ProtocolError, match="session_name"):
        build_message(
            Status.REGISTER,
            {"session_name": "", "session_id": "id"},
        )
    with pytest.raises(ProtocolError, match="缺少字段"):
        build_message(Status.PLAN, {"1": "step"})
    with pytest.raises(ProtocolError, match="缺少字段"):
        build_message(Status.STEP_COMPLETE, {"session_id": "id"})


@pytest.mark.parametrize(
    "fields",
    [
        {"session_id": "id"},
        {"session_id": "id", "0": "zero"},
        {"session_id": "id", "01": "leading zero"},
        {"session_id": "id", "abc": "not numeric"},
        {"session_id": "id", str(MAX_PLAN_INDEX + 1): "too high"},
        {"session_id": "id", "1": ""},
        {"session_id": "id", "1": 123},
        {"session_id": "id", 1: "non-string key"},
        {"session_id": "id", "1": "x" * (MAX_PLAN_STEP_TEXT_LENGTH + 1)},
        {
            "session_id": "id",
            **{
                str(index): f"step {index}"
                for index in range(1, MAX_PLAN_STEPS_PER_MESSAGE + 2)
            },
        },
    ],
)
def test_rejects_invalid_plan_payloads(fields) -> None:
    with pytest.raises(ProtocolError):
        build_message(Status.PLAN, fields)


@pytest.mark.parametrize("index", ["0", "01", "abc", str(MAX_PLAN_INDEX + 1)])
def test_rejects_invalid_step_indices(index: str) -> None:
    with pytest.raises(ProtocolError):
        build_message(
            Status.STEP_COMPLETE,
            {"session_id": "id", "step_index": index},
        )


def test_rejects_non_string_optional_messages() -> None:
    with pytest.raises(ProtocolError, match="必须是字符串"):
        build_message(
            Status.RESUME,
            {"session_id": "id", "message": 123},
        )
    with pytest.raises(ProtocolError, match="必须是字符串"):
        build_message(
            Status.STEP_COMPLETE,
            {"session_id": "id", "step_index": "1", "message": 123},
        )


def test_rejects_bad_session_ids() -> None:
    for session_id in ("", "has space", "new\nline", "a" * 129):
        with pytest.raises(ProtocolError, match="session_id"):
            build_message(
                Status.COMPLETE,
                {"session_id": session_id, "message": "x"},
            )


def test_extra_keys_are_ignored() -> None:
    message = build_message(
        Status.COMPLETE,
        {"session_id": "id", "message": "x", "future": "value"},
    )
    assert message.text == "x"


def test_rejects_lone_surrogates_in_text_fields() -> None:
    with pytest.raises(ProtocolError, match="代理|UTF-8"):
        build_message(
            Status.COMPLETE,
            {"session_id": "id", "message": "\ud800"},
        )
    with pytest.raises(ProtocolError, match="代理|UTF-8"):
        build_message(
            Status.REGISTER,
            {"session_name": "bad\udfff", "session_id": "id"},
        )

    body = b'{"session_id":"id","message":"\\ud800"}'
    frame = bytes([1]) + len(body).to_bytes(3, "big") + body
    with pytest.raises(ProtocolError, match="代理|UTF-8"):
        decode_frame(frame)


def test_message_as_json_object_is_canonical() -> None:
    message = Message(status=Status.ACTION, session_id="id", text="please check")
    assert message.as_json_object() == {
        "session_id": "id",
        "instruction": "please check",
    }

    plan = Message(
        status=Status.PLAN,
        session_id="id",
        steps=(("1", "one"), ("2", "two")),
    )
    assert plan.as_json_object() == {
        "session_id": "id",
        "1": "one",
        "2": "two",
    }

    resume = Message(status=Status.RESUME, session_id="id")
    assert resume.as_json_object() == {"session_id": "id"}

    step = Message(
        status=Status.STEP_COMPLETE,
        session_id="id",
        step_index="2",
        text="done",
    )
    assert step.as_json_object() == {
        "session_id": "id",
        "step_index": "2",
        "message": "done",
    }


def test_encode_rejects_oversized_body() -> None:
    body = "x" * (MAX_BODY_SIZE + 1)
    with pytest.raises(ProtocolError, match="过大|超过"):
        encode_message(Status.COMPLETE, {"session_id": "id", "message": body})
