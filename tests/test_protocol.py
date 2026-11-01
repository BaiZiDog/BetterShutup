from __future__ import annotations

import json

import pytest

from better_shutup.protocol import (
    HEADER_SIZE,
    MAX_BODY_SIZE,
    Message,
    ProtocolError,
    Status,
    build_message,
    decode_frame,
    encode_message,
)


def test_status_codes_are_binary() -> None:
    assert int(Status.REGISTER) == 0
    assert int(Status.COMPLETE) == 1
    assert int(Status.ACTION) == 2
    assert int(Status.ERROR) == 3
    assert Status.ACTION.binary == "10"
    assert Status.ERROR.binary == "11"


def test_register_frame_layout_and_roundtrip() -> None:
    frame = encode_message(
        Status.REGISTER,
        {"session_name": "Claude Code", "session_id": "abc"},
    )
    body = frame[HEADER_SIZE:]
    assert frame[0] == 0b00
    assert int.from_bytes(frame[1:4], "big") == len(body)
    payload = json.loads(body.decode("utf-8"))
    assert payload == {"session_name": "Claude Code", "session_id": "abc"}
    message = decode_frame(frame)
    assert message.status is Status.REGISTER
    assert message.session_id == "abc"
    assert message.session_name == "Claude Code"


@pytest.mark.parametrize("status", [Status.COMPLETE, Status.ACTION, Status.ERROR])
def test_non_register_status_codes(status: Status) -> None:
    field = {
        Status.COMPLETE: "message",
        Status.ACTION: "instruction",
        Status.ERROR: "error",
    }[status]
    frame = encode_message(status, {"session_id": "id-1", field: "内容"})
    assert frame[0] == int(status)
    assert int.from_bytes(frame[1:4], "big") == len(frame) - HEADER_SIZE
    decoded = decode_frame(frame)
    assert decoded.status is status
    assert decoded.text == "内容"
    assert decoded.text_field == field


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
    corrupted = bytes([frame[0] | 0x04]) + frame[1:]
    with pytest.raises(ProtocolError, match="保留位"):
        decode_frame(corrupted)


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


def test_encode_rejects_oversized_body() -> None:
    body = "x" * (MAX_BODY_SIZE + 1)
    with pytest.raises(ProtocolError, match="过大|超过"):
        encode_message(Status.COMPLETE, {"session_id": "id", "message": body})
