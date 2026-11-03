"""Wire protocol for BetterShutup.

Frame layout (all integers are big-endian)::

    byte 0:  0 0 0 0 S S S S   (S = status, upper four bits must be zero)
    byte 1:  L23 ... L16
    byte 2:  L15 ... L8
    byte 3:  L7  ... L0

``L`` is the UTF-8 byte length of the JSON object that follows the header.

Status codes 0000-0111 are defined.  Codes 1000-1111 are reserved for future
use and must be rejected by the current application.
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
RESERVED_STATUS_MASK = 0xF0
STATUS_MASK = 0x0F
MAX_SESSION_ID_LENGTH = 128
MAX_SESSION_NAME_LENGTH = 256
MAX_PLAN_INDEX = 9999
MAX_PLAN_STEPS_PER_MESSAGE = 200
MAX_PLAN_STEP_TEXT_LENGTH = 2000


class ProtocolError(ValueError):
    """Raised when a frame or JSON payload violates the wire protocol."""


class Status(IntEnum):
    REGISTER = 0b0000
    COMPLETE = 0b0001
    ACTION = 0b0010
    ERROR = 0b0011
    RESUME = 0b0100
    NOTIFY = 0b0101
    PLAN = 0b0110
    STEP_COMPLETE = 0b0111

    @property
    def binary(self) -> str:
        return f"{int(self):04b}"


STATUS_NAMES: dict[Status, str] = {
    Status.REGISTER: "注册会话",
    Status.COMPLETE: "完成任务",
    Status.ACTION: "需要操作",
    Status.ERROR: "错误",
    Status.RESUME: "撤销需要操作",
    Status.NOTIFY: "普通通知",
    Status.PLAN: "更新计划",
    Status.STEP_COMPLETE: "步骤完成",
}

REQUIRED_FIELDS: dict[Status, tuple[str, ...]] = {
    Status.REGISTER: ("session_name", "session_id"),
    Status.COMPLETE: ("session_id", "message"),
    Status.ACTION: ("session_id", "instruction"),
    Status.ERROR: ("session_id", "error"),
    Status.RESUME: ("session_id",),
    Status.NOTIFY: ("session_id", "message"),
    Status.PLAN: ("session_id",),
    Status.STEP_COMPLETE: ("session_id", "step_index"),
}

TEXT_FIELDS: dict[Status, str] = {
    Status.REGISTER: "",
    Status.COMPLETE: "message",
    Status.ACTION: "instruction",
    Status.ERROR: "error",
    Status.RESUME: "message",
    Status.NOTIFY: "message",
    Status.PLAN: "",
    Status.STEP_COMPLETE: "message",
}


@dataclass(frozen=True, slots=True)
class Message:
    """A validated protocol message."""

    status: Status
    session_id: str
    text: str = ""
    session_name: str = ""
    steps: tuple[tuple[str, str], ...] = ()
    step_index: str = ""

    @property
    def status_name(self) -> str:
        return STATUS_NAMES[self.status]

    @property
    def text_field(self) -> str:
        return TEXT_FIELDS[self.status]

    def as_json_object(self) -> dict[str, Any]:
        if self.status is Status.REGISTER:
            return {
                "session_name": self.session_name,
                "session_id": self.session_id,
            }
        if self.status is Status.PLAN:
            payload: dict[str, Any] = {"session_id": self.session_id}
            for index, text in sorted(
                self.steps, key=lambda item: int(item[0])
            ):
                payload[index] = text
            return payload
        if self.status is Status.STEP_COMPLETE:
            payload = {
                "session_id": self.session_id,
                "step_index": self.step_index,
            }
            if self.text:
                payload["message"] = self.text
            return payload
        if self.status is Status.RESUME:
            payload = {"session_id": self.session_id}
            if self.text:
                payload["message"] = self.text
            return payload
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


def _validate_step_index(value: Any, field_name: str = "step_index") -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{field_name} 必须是字符串")
    if not value or not all("0" <= char <= "9" for char in value):
        raise ProtocolError(
            f"{field_name} 必须是 1–{MAX_PLAN_INDEX} 的正整数字符串"
        )
    if len(value) > len(str(MAX_PLAN_INDEX)):
        raise ProtocolError(
            f"{field_name} 必须在 1–{MAX_PLAN_INDEX} 范围内"
        )
    if value != str(int(value)):
        raise ProtocolError(f"{field_name} 不能有前导零")
    number = int(value)
    if number < 1 or number > MAX_PLAN_INDEX:
        raise ProtocolError(
            f"{field_name} 必须在 1–{MAX_PLAN_INDEX} 范围内"
        )
    return value


def _validate_step_text(value: Any, index: str) -> str:
    text = _validate_text(value, f"计划步骤 {index}")
    if not text.strip():
        raise ProtocolError(f"计划步骤 {index} 的内容不能为空")
    if len(text) > MAX_PLAN_STEP_TEXT_LENGTH:
        raise ProtocolError(
            f"计划步骤 {index} 不能超过 {MAX_PLAN_STEP_TEXT_LENGTH} 个字符"
        )
    return text


def _optional_text(fields: Mapping[str, Any], field_name: str) -> str:
    if field_name not in fields:
        return ""
    return _validate_text(fields[field_name], field_name)


def _build_plan_message(
    status: Status, fields: Mapping[str, Any]
) -> Message:
    session_id = _validate_session_id(fields["session_id"])
    steps: list[tuple[str, str]] = []
    for raw_index, raw_text in fields.items():
        if raw_index == "session_id":
            continue
        index = _validate_step_index(raw_index, "计划索引")
        steps.append((index, _validate_step_text(raw_text, index)))
    if not steps:
        raise ProtocolError("计划消息至少包含一个步骤")
    if len(steps) > MAX_PLAN_STEPS_PER_MESSAGE:
        raise ProtocolError(
            f"一条计划消息最多包含 {MAX_PLAN_STEPS_PER_MESSAGE} 个步骤"
        )
    steps.sort(key=lambda item: int(item[0]))
    return Message(
        status=status,
        session_id=session_id,
        steps=tuple(steps),
    )


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

    if status is Status.REGISTER:
        return Message(
            status=status,
            session_id=_validate_session_id(fields["session_id"]),
            session_name=_validate_session_name(fields["session_name"]),
        )

    if status is Status.PLAN:
        return _build_plan_message(status, fields)

    session_id = _validate_session_id(fields["session_id"])
    if status is Status.STEP_COMPLETE:
        return Message(
            status=status,
            session_id=session_id,
            step_index=_validate_step_index(fields["step_index"]),
            text=_optional_text(fields, "message"),
        )
    if status is Status.RESUME:
        return Message(
            status=status,
            session_id=session_id,
            text=_optional_text(fields, "message"),
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


def _encode_json_body(obj: Mapping[str, Any]) -> bytes:
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
        raise ProtocolError("状态码只能占低 4 位")
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
        raise ProtocolError("状态字节的高 4 个保留位必须为 0")
    raw_status = status_byte & STATUS_MASK
    try:
        status = Status(raw_status)
    except ValueError as exc:
        raise ProtocolError(f"未定义的状态码: 0b{raw_status:04b}") from exc

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


def coerce_fields(message: Message) -> dict[str, Any]:
    """Return the canonical JSON object for a message (useful for CLI/tests)."""

    return message.as_json_object()
