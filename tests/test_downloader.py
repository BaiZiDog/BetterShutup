from __future__ import annotations

import http.server
import re
import threading
import time
from pathlib import Path

import pytest

from better_shutup.downloader import DownloadManager, download_file


def make_handler(
    *,
    payload: bytes,
    support_ranges: bool = True,
    fail_status: int | None = None,
    truncate: bool = False,
):
    class Handler(http.server.BaseHTTPRequestHandler):
        range_requests = 0
        active = 0
        max_active = 0
        lock = threading.Lock()

        def log_message(self, _format, *args) -> None:
            pass

        def do_GET(self) -> None:
            cls = type(self)
            with cls.lock:
                cls.active += 1
                cls.max_active = max(cls.max_active, cls.active)
            try:
                if fail_status is not None:
                    self.send_response(fail_status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                range_header = self.headers.get("Range")
                if range_header:
                    with cls.lock:
                        cls.range_requests += 1
                if support_ranges and range_header:
                    match = re.fullmatch(
                        r"bytes=(\d+)-(\d+)", range_header.strip()
                    )
                    if match:
                        start = int(match.group(1))
                        end = int(match.group(2))
                        if start >= len(payload):
                            self.send_response(416)
                            self.send_header(
                                "Content-Range", f"bytes */{len(payload)}"
                            )
                            self.send_header("Content-Length", "0")
                            self.end_headers()
                            return
                        end = min(end, len(payload) - 1)
                        body = payload[start : end + 1]
                        self.send_response(206)
                        self.send_header(
                            "Content-Range",
                            f"bytes {start}-{end}/{len(payload)}",
                        )
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return

                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if truncate:
                    self.wfile.write(payload[: len(payload) // 2])
                else:
                    self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with cls.lock:
                    cls.active -= 1

    return Handler


@pytest.fixture
def server_factory():
    servers: list[tuple[http.server.ThreadingHTTPServer, threading.Thread]] = []

    def make(
        *,
        payload: bytes,
        support_ranges: bool = True,
        fail_status: int | None = None,
        truncate: bool = False,
    ):
        handler = make_handler(
            payload=payload,
            support_ranges=support_ranges,
            fail_status=fail_status,
            truncate=truncate,
        )
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        url = f"http://127.0.0.1:{server.server_address[1]}/file"
        return url, handler

    yield make

    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_range_download_writes_atomic_target(server_factory, tmp_path: Path) -> None:
    payload = bytes(range(256)) * 2048
    url, handler = server_factory(payload=payload, support_ranges=True)
    target = tmp_path / "nested" / "archive.bin"

    result = download_file(
        "s1",
        url,
        str(target),
        chunk_size=64 * 1024,
        start_workers=2,
        sample_seconds=0.05,
    )

    assert result.success, result.error
    assert result.bytes_written == len(payload)
    assert target.read_bytes() == payload
    assert not (target.parent / "err.err").exists()
    assert handler.range_requests > 1
    assert not list(target.parent.glob(".archive.bin.*.part"))


def test_range_unsupported_falls_back_to_single_stream(
    server_factory, tmp_path: Path
) -> None:
    payload = b"fallback-payload-" * 12_000
    url, _handler = server_factory(payload=payload, support_ranges=False)
    target = tmp_path / "fallback.bin"

    result = download_file(
        "s1",
        url,
        str(target),
        chunk_size=64 * 1024,
        start_workers=2,
        sample_seconds=0.05,
    )

    assert result.success, result.error
    assert target.read_bytes() == payload
    assert not (tmp_path / "err.err").exists()


def test_failure_writes_err_err_and_removes_temp(
    server_factory, tmp_path: Path
) -> None:
    url, _handler = server_factory(payload=b"x", fail_status=500)
    target = tmp_path / "failed.bin"

    result = download_file("s1", url, str(target))

    assert not result.success
    assert "HTTP 500" in result.error
    assert not target.exists()
    error_file = tmp_path / "err.err"
    assert error_file.is_file()
    error_text = error_file.read_text(encoding="utf-8")
    assert "url=" in error_text
    assert "path=" in error_text
    assert "HTTP 500" in error_text
    assert not list(tmp_path.glob(".failed.bin.*.part"))


def test_failure_preserves_existing_target_and_appends_errors(
    server_factory, tmp_path: Path
) -> None:
    url, _handler = server_factory(payload=b"x", fail_status=500)
    target = tmp_path / "existing.bin"
    target.write_bytes(b"old-content")
    error_file = tmp_path / "err.err"
    error_file.write_text("old error\n", encoding="utf-8")

    first = download_file("s1", url, str(target))
    second = download_file("s2", url, str(target))

    assert not first.success
    assert not second.success
    assert target.read_bytes() == b"old-content"
    text = error_file.read_text(encoding="utf-8")
    assert text.startswith("old error\n")
    assert text.count("url=") == 2
    assert "s1" not in text
    assert "s2" not in text


def test_success_does_not_delete_existing_err_err(
    server_factory, tmp_path: Path
) -> None:
    payload = b"ok" * 100
    url, _handler = server_factory(payload=payload, support_ranges=True)
    target = tmp_path / "ok.bin"
    error_file = tmp_path / "err.err"
    error_file.write_text("old error\n", encoding="utf-8")

    result = download_file("s1", url, str(target))

    assert result.success, result.error
    assert error_file.read_text(encoding="utf-8") == "old error\n"


def test_truncated_single_stream_is_failure(
    server_factory, tmp_path: Path
) -> None:
    payload = b"y" * 100_000
    url, _handler = server_factory(
        payload=payload,
        support_ranges=False,
        truncate=True,
    )
    target = tmp_path / "truncated.bin"

    result = download_file("s1", url, str(target))

    assert not result.success
    assert not target.exists()
    assert (tmp_path / "err.err").is_file()


def test_download_manager_runs_parallel_tasks(server_factory, tmp_path: Path) -> None:
    payload = b"parallel" * 20_000
    url, _handler = server_factory(payload=payload, support_ranges=True)
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    manager = DownloadManager()
    try:
        manager.start("s1", url, str(first))
        manager.start("s2", url, str(second))
        results = []
        deadline = time.monotonic() + 15
        while len(results) < 2 and time.monotonic() < deadline:
            results.extend(manager.drain())
            if len(results) < 2:
                time.sleep(0.02)
    finally:
        manager.close()

    assert len(results) == 2
    assert all(result.success for result in results)
    assert first.read_bytes() == payload
    assert second.read_bytes() == payload
