"""Wire protocol for BetterShutup.

Frame layout (all integers are big-endian)::

    byte 0:  0 0 0 0 0 0 SS   (SS = status, upper six bits must be zero)
    byte 1:  L23 ... L16
    byte 2:  L15 ... L8
    byte 3:  L7  ... L0

``L`` is the UTF-8 byte length of the JSON object that follows the header.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import json
import unicodedata
from typing import Any, Mapping

HEADER_SIZE = 4
MAX_BODY_SIZE = 0xFFFFFF
MAX_FRAME_SIZE = HEADER_SIZE + MAX_BODY_SIZE
RESERVED_STATUS_MASK = 0xFC
MAX_SESSION_ID_LENGTH = 128
MAX_SESSION_NAME_LENGTH = 256


class ProtocolError(ValueError):
    """Raised when a frame or JSON payload violates the wire protocol."""


class Status(IntEnum):
    REGISTER = 0b00
    COMPLETE = 0b01
    ACTION = 0b10
    ERROR = 0b11

    @property
    def binary(self) -> str:
        return f"{int(self):02b}"


STATUS_NAMES: dict[Status, str] = {
    Status.REGISTER: "注册会话",
    Status.COMPLETE: "完成任务",
    Status.ACTION: "需要操作",
    Status.ERROR: "错误",
}

REQUIRED_FIELDS: dict[Status, tuple[str, str]] = {
    Status.REGISTER: ("session_name", "session_id"),
    Status.COMPLETE: ("session_id", "message"),
    Status.ACTION: ("session_id", "instruction"),
    Status.ERROR: ("session_id", "error"),
}

TEXT_FIELDS: dict[Status, str] = {
    Status.REGISTER: "",
    Status.COMPLETE: "message",
    Status.ACTION: "instruction",
    Status.ERROR: "error",
}


@dataclass(frozen=True, slots=True)
class Message:
    """A validated protocol message."""

    status: Status
    session_id: str
    text: str = ""
    session_name: str = ""

    @property
    def status_name(self) -> str:
        return STATUS_NAMES[self.status]

    @property
    def text_field(self) -> str:
        return TEXT_FIELDS[self.status]

    def as_json_object(self) -> dict[str, str]:
        if self.status is Status.REGISTER:
            return {
                "session_name": self.session_name,
                "session_id": self.session_id,
            }
        return {
            "session_id": self.session_id,
            self.text_field: self.text,
        }


def _validate_session_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError("session_id 必须是非空字符串")
    if len(value) > MAX_SESSION_ID_LENGTH:
        raise ProtocolError(f"session_id 不能超过 {MAX_SESSION_ID_LENGTH} 个字符")
    for char in value:
        if char.isspace() or unicodedata.category(char).startswith("C"):
            raise ProtocolError("session_id 不能包含空白或控制字符")
    return value


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _validate_session_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("session_name 必须是非空字符串")
    if len(value) > MAX_SESSION_NAME_LENGTH:
        raise ProtocolError(f"session_name 不能超过 {MAX_SESSION_NAME_LENGTH} 个字符")
    if "\x00" in value:
        raise ProtocolError("session_name 不能包含 NUL 字符")
    if _contains_surrogate(value):
        raise ProtocolError("session_name 不能包含孤立的 Unicode 代理字符")
    return value


def _validate_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{field_name} 必须是字符串")
    if "\x00" in value:
        raise ProtocolError(f"{field_name} 不能包含 NUL 字符")
    if _contains_surrogate(value):
        raise ProtocolError(f"{field_name} 不能包含孤立的 Unicode 代理字符")
    return value


def build_message(status: Status, fields: Mapping[str, Any]) -> Message:
    """Validate raw fields and construct a typed message."""

    try:
        status = Status(status)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"未知状态码: {status!r}") from exc

    if not isinstance(fields, Mapping):
        raise ProtocolError("消息体字段必须是映射")

    for field_name in REQUIRED_FIELDS[status]:
        if field_name not in fields:
            raise ProtocolError(f"{status.binary} 消息缺少字段 {field_name}")
        if not isinstance(fields[field_name], str):
            raise ProtocolError(f"{status.binary} 消息的 {field_name} 必须是字符串")

    session_id = _validate_session_id(fields["session_id"])
    if status is Status.REGISTER:
        session_name = _validate_session_name(fields["session_name"])
        return Message(
            status=status,
            session_id=session_id,
            session_name=session_name,
        )

    text_field = TEXT_FIELDS[status]
    text = _validate_text(fields[text_field], text_field)
    return Message(status=status, session_id=session_id, text=text)


def encode_message(status: Status, fields: Mapping[str, Any]) -> bytes:
    """Encode a validated message into one complete pipe frame."""

    message = build_message(status, fields)
    body_bytes = _encode_json_body(message.as_json_object())
    if len(body_bytes) > MAX_BODY_SIZE:
        raise ProtocolError(
            f"消息体过大: {len(body_bytes)} 字节，最大 {MAX_BODY_SIZE} 字节"
        )
    return _build_frame(message.status, body_bytes)


def _encode_json_body(obj: Mapping[str, str]) -> bytes:
    try:
        text = json.dumps(
            obj,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"无法序列化 JSON: {exc}") from exc
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProtocolError(f"消息包含无法编码为 UTF-8 的字符: {exc}") from exc


def _build_frame(status: Status, body_bytes: bytes) -> bytes:
    status_code = int(status)
    if status_code & RESERVED_STATUS_MASK:
        raise ProtocolError("状态码只能占低 2 位")
    if len(body_bytes) > MAX_BODY_SIZE:
        raise ProtocolError("消息体超过 24 位长度上限")
    return (
        bytes((status_code,))
        + len(body_bytes).to_bytes(3, "big")
        + body_bytes
    )


def decode_frame(frame: bytes) -> Message:
    """Decode and strictly validate one complete pipe message."""

    if not isinstance(frame, (bytes, bytearray, memoryview)):
        raise ProtocolError("帧必须是 bytes")
    raw = bytes(frame)
    if len(raw) < HEADER_SIZE:
        raise ProtocolError(f"帧长度不足 {HEADER_SIZE} 字节")
    if len(raw) > MAX_FRAME_SIZE:
        raise ProtocolError("帧超过协议允许的最大长度")

    status_byte = raw[0]
    if status_byte & RESERVED_STATUS_MASK:
        raise ProtocolError("状态字节的高 6 个保留位必须为 0")
    status = Status(status_byte & 0x03)

    declared_length = int.from_bytes(raw[1:HEADER_SIZE], "big")
    body = raw[HEADER_SIZE:]
    if len(body) != declared_length:
        raise ProtocolError(
            f"消息体长度不符: 头部声明 {declared_length} 字节，实际 {len(body)} 字节"
        )
    if declared_length == 0:
        raise ProtocolError("消息体不能为空")

    try:
        body_text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"消息体不是合法的 UTF-8: {exc}") from exc

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"消息体不是合法 JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ProtocolError("JSON 消息体必须是对象")

    return build_message(status, payload)


def coerce_fields(message: Message) -> dict[str, str]:
    """Return the canonical JSON object for a message (useful for CLI/tests)."""

    return message.as_json_object()
