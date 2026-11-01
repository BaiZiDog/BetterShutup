from __future__ import annotations

import queue
import sys
import threading
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows named pipes only"
)
if sys.platform != "win32":
    pytest.skip("Windows named pipes only", allow_module_level=True)

from better_shutup import DEFAULT_PIPE_NAME
from better_shutup.pipe_client import send_frame, send_message
from better_shutup.pipe_server import PipeServer
from better_shutup.protocol import Status, decode_frame, encode_message
from better_shutup.win32_pipe import (
    PipeError,
    PipeUnavailable,
    close_handle,
    connect_pipe,
    create_pipe_instance,
    disconnect_pipe,
    open_pipe_client,
    read_pipe_message,
    write_pipe_frame,
)


def unique_pipe() -> str:
    return DEFAULT_PIPE_NAME + "-test-" + uuid.uuid4().hex


@pytest.fixture
def server_factory():
    servers: list[PipeServer] = []

    def make(name: str, q: queue.Queue[bytes]) -> PipeServer:
        server = PipeServer(name, q.put, lambda message: q.put(b"ERROR:" + message.encode()))
        server.start()
        servers.append(server)
        return server

    try:
        yield make
    finally:
        for server in servers:
            server.stop()


def test_register_roundtrip(server_factory) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)

    send_message(
        name,
        Status.REGISTER,
        {"session_name": "Claude Code", "session_id": "abc"},
    )
    frame = q.get(timeout=3)
    message = decode_frame(frame)
    assert message.status is Status.REGISTER
    assert message.session_name == "Claude Code"
    assert message.session_id == "abc"


def test_sequential_messages_use_separate_connections(server_factory) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)

    send_message(
        name,
        Status.REGISTER,
        {"session_name": "Agent", "session_id": "s1"},
    )
    send_message(
        name,
        Status.COMPLETE,
        {"session_id": "s1", "message": "done"},
    )
    first = decode_frame(q.get(timeout=3))
    second = decode_frame(q.get(timeout=3))
    assert first.status is Status.REGISTER
    assert second.status is Status.COMPLETE


def test_large_message_over_64k(server_factory) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)

    text = "x" * 250_000
    send_message(
        name,
        Status.COMPLETE,
        {"session_id": "s1", "message": text},
        timeout_ms=10_000,
    )
    frame = q.get(timeout=10)
    message = decode_frame(frame)
    assert message.text == text


def test_rapid_sequential_messages_are_not_lost(server_factory) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)

    count = 30
    for index in range(count):
        send_message(
            name,
            Status.REGISTER,
            {"session_name": f"Rapid {index}", "session_id": f"rapid-{index}"},
        )

    received = [decode_frame(q.get(timeout=5)) for _ in range(count)]
    assert {message.session_id for message in received} == {
        f"rapid-{index}" for index in range(count)
    }


def test_concurrent_clients(server_factory) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)

    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            send_message(
                name,
                Status.REGISTER,
                {"session_name": f"Agent {index}", "session_id": f"s{index}"},
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    received = [decode_frame(q.get(timeout=5)) for _ in range(6)]
    assert {message.session_id for message in received} == {
        f"s{index}" for index in range(6)
    }


def test_raw_malformed_frame_is_forwarded_for_protocol_validation(
    server_factory,
) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)

    body = b"{}"
    raw = bytes([0x01]) + len(body).to_bytes(3, "big") + body
    send_frame(name, raw)
    frame = q.get(timeout=3)
    with pytest.raises(Exception):
        decode_frame(frame)


def test_empty_connection_is_ignored(server_factory) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)

    # open_pipe_probe connects and immediately closes, producing no message.
    from better_shutup.win32_pipe import open_pipe_probe

    assert open_pipe_probe(name)
    # A real message afterwards must still work.
    send_message(
        name,
        Status.REGISTER,
        {"session_name": "After probe", "session_id": "after"},
    )
    message = decode_frame(q.get(timeout=3))
    assert message.session_id == "after"


def test_message_is_readable_after_client_closes_before_accept() -> None:
    """ConnectNamedPipe may report ERROR_NO_DATA; buffered bytes remain."""

    name = unique_pipe()
    handle = create_pipe_instance(name, first=True)
    try:
        client = open_pipe_client(name, timeout_ms=1000)
        frame = encode_message(
            Status.REGISTER,
            {"session_name": "Early close", "session_id": "early-1"},
        )
        try:
            write_pipe_frame(client, frame)
        finally:
            close_handle(client)
        time.sleep(0.03)
        # True (ERROR_PIPE_CONNECTED) or False (ERROR_NO_DATA) are both
        # acceptable; neither may discard the buffered frame.
        connect_pipe(handle)
        received = read_pipe_message(handle)
        assert received is not None
        assert decode_frame(received).session_id == "early-1"
    finally:
        disconnect_pipe(handle)
        close_handle(handle)


def test_client_without_server_raises_unavailable() -> None:
    name = unique_pipe()
    with pytest.raises(PipeUnavailable, match="未运行"):
        send_message(
            name,
            Status.REGISTER,
            {"session_name": "Agent", "session_id": "abc"},
            timeout_ms=100,
        )


def test_second_server_on_same_pipe_fails(server_factory) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)
    second = PipeServer(name, q.put)
    with pytest.raises(PipeError):
        second.start()


def test_server_stop_is_prompt() -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server = PipeServer(name, q.put)
    server.start()
    started = time.monotonic()
    server.stop(timeout=2.0)
    elapsed = time.monotonic() - started
    assert elapsed < 2.5
    assert not server.is_running


def test_protocol_encode_decode_large_via_client(server_factory) -> None:
    name = unique_pipe()
    q: queue.Queue[bytes] = queue.Queue()
    server_factory(name, q)
    original = encode_message(
        Status.ACTION,
        {"session_id": "id", "instruction": "请检查 " + "a" * 100_000},
    )
    send_frame(name, original)
    assert decode_frame(q.get(timeout=5)) == decode_frame(original)
