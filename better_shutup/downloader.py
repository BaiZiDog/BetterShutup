"""Adaptive multi-threaded HTTP file downloader.

The app accepts download requests from agents and performs them in the
background.  It never sends progress or results back through the pipe; the
agent observes the target file (success) or ``err.err`` (failure).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import queue
import re
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import __version__

USER_AGENT = f"BetterShutup/{__version__}"
CONNECT_TIMEOUT = 30.0
READ_SIZE = 64 * 1024
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_START_WORKERS = 4
SAMPLE_SECONDS = 2.0
CHUNK_RETRIES = 3
ERROR_FILENAME = "err.err"

_ERR_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class DownloadResult:
    session_id: str
    url: str
    path: str
    success: bool
    bytes_written: int = 0
    error: str = ""
    elapsed: float = 0.0


class DownloadError(Exception):
    """A file download could not be completed."""


class RangeNotSupported(DownloadError):
    """The server does not honor byte-range requests."""


class DownloadCancelled(DownloadError):
    """The application is shutting down."""


class _Progress:
    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def add(self, amount: int) -> None:
        with self._lock:
            self._value += amount


def _content_range_total(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes\s+0-0/(\d+|\*)", value.strip(), re.IGNORECASE)
    if not match or match.group(1) == "*":
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _content_range_bounds(
    value: str | None,
) -> tuple[int, int, int | None] | None:
    if not value:
        return None
    match = re.fullmatch(
        r"bytes\s+(\d+)-(\d+)/(\d+|\*)",
        value.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        start = int(match.group(1))
        end = int(match.group(2))
        total = None if match.group(3) == "*" else int(match.group(3))
    except ValueError:
        return None
    return start, end, total


def _append_error_file(
    target: Path,
    url: str,
    error: str,
    bytes_written: int,
    logger: logging.Logger,
) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        error_path = target.parent / ERROR_FILENAME
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        block = (
            f"[{stamp}] url={url}\n"
            f"path={target}\n"
            f"downloaded={bytes_written}\n"
            f"error={error}\n\n"
        )
        with _ERR_LOCK:
            with error_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(block)
    except OSError as exc:
        logger.error("写入 err.err 失败: %s", exc)


def _probe(
    url: str, stop_event: threading.Event
) -> tuple[int | None, bool, str]:
    if urlsplit(url).scheme.lower() not in ("http", "https"):
        raise DownloadError("url 只支持 http/https")
    if stop_event.is_set():
        raise DownloadCancelled("下载已取消")
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"},
    )
    try:
        with urlopen(request, timeout=CONNECT_TIMEOUT) as response:
            status = response.getcode()
            final_url = response.geturl()
            content_range = response.headers.get("Content-Range")
            content_length = response.headers.get("Content-Length")
            response.read(1)
    except HTTPError as exc:
        if exc.code == 416:
            return 0, False, url
        raise DownloadError(f"探测下载时返回 HTTP {exc.code}") from exc
    if urlsplit(final_url).scheme.lower() not in ("http", "https"):
        raise DownloadError("重定向后的 URL 不是 http/https")
    if status == 206:
        total = _content_range_total(content_range)
        if total is None:
            return None, False, final_url
        return total, True, final_url
    if status == 200:
        try:
            total = int(content_length) if content_length is not None else None
        except ValueError:
            total = None
        return total, False, final_url
    raise DownloadError(f"探测下载时返回 HTTP {status}")


def _download_chunk(
    url: str,
    start: int,
    end: int,
    temp_path: Path,
    stop_event: threading.Event,
    progress: _Progress,
) -> None:
    expected = end - start + 1
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Range": f"bytes={start}-{end}",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, CHUNK_RETRIES + 1):
        if stop_event.is_set():
            raise DownloadCancelled("下载已取消")
        attempt_bytes = 0
        try:
            with urlopen(request, timeout=CONNECT_TIMEOUT) as response:
                status = response.getcode()
                if status == 200:
                    raise RangeNotSupported("服务器未按 Range 返回分片")
                if status != 206:
                    raise DownloadError(f"分片请求返回 HTTP {status}")
                bounds = _content_range_bounds(
                    response.headers.get("Content-Range")
                )
                if bounds is not None:
                    actual_start, actual_end, _total = bounds
                    if actual_start != start or actual_end != end:
                        raise DownloadError("服务器返回的分片范围不符")
                fd = os.open(
                    temp_path,
                    os.O_WRONLY | getattr(os, "O_BINARY", 0),
                )
                try:
                    os.lseek(fd, start, os.SEEK_SET)
                    remaining = expected
                    while remaining:
                        if stop_event.is_set():
                            raise DownloadCancelled("下载已取消")
                        data = response.read(min(READ_SIZE, remaining))
                        if not data:
                            raise DownloadError("连接在分片完成前结束")
                        view = memoryview(data)
                        while view:
                            written = os.write(fd, view)
                            if written <= 0:
                                raise DownloadError("写入目标临时文件失败")
                            view = view[written:]
                        attempt_bytes += len(data)
                        progress.add(len(data))
                        remaining -= len(data)
                finally:
                    os.close(fd)
            if remaining == 0:
                return
            raise DownloadError("分片长度不完整")
        except (RangeNotSupported, DownloadCancelled):
            if attempt_bytes:
                progress.add(-attempt_bytes)
            raise
        except (HTTPError, URLError, TimeoutError, OSError, DownloadError) as exc:
            if attempt_bytes:
                progress.add(-attempt_bytes)
            last_error = exc
            if attempt >= CHUNK_RETRIES:
                break
            if stop_event.wait(min(1.0, 0.2 * attempt)):
                raise DownloadCancelled("下载已取消") from exc
    raise DownloadError(
        f"分片 {start}-{end} 下载失败: {last_error}"
    ) from last_error


def _download_single(
    url: str,
    temp_path: Path,
    stop_event: threading.Event,
    progress: _Progress,
) -> int:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=CONNECT_TIMEOUT) as response:
        content_length = response.headers.get("Content-Length")
        try:
            expected = int(content_length) if content_length else None
        except ValueError:
            expected = None
        written = 0
        with temp_path.open("wb") as handle:
            while True:
                if stop_event.is_set():
                    raise DownloadCancelled("下载已取消")
                data = response.read(READ_SIZE)
                if not data:
                    break
                handle.write(data)
                written += len(data)
                progress.add(len(data))
        if expected is not None and written != expected:
            raise DownloadError(
                f"下载长度不符: 期望 {expected} 字节，实际 {written} 字节"
            )
        return written


def _range_download(
    url: str,
    total: int,
    temp_path: Path,
    stop_event: threading.Event,
    logger: logging.Logger,
    *,
    chunk_size: int,
    start_workers: int,
    sample_seconds: float,
    progress: _Progress,
) -> int:
    with temp_path.open("wb") as handle:
        handle.truncate(total)

    chunks = [
        (start, min(start + chunk_size - 1, total - 1))
        for start in range(0, total, chunk_size)
    ]
    tasks: queue.Queue[tuple[int, int]] = queue.Queue()
    for chunk in chunks:
        tasks.put(chunk)

    local_stop = threading.Event()
    completion_event = threading.Event()
    errors: list[BaseException] = []
    error_lock = threading.Lock()
    worker_lock = threading.Lock()
    active = [0]
    desired = [max(1, min(start_workers, len(chunks)))]
    remaining = [len(chunks)]
    remaining_lock = threading.Lock()
    threads: list[threading.Thread] = []

    def set_error(exc: BaseException) -> None:
        with error_lock:
            if not errors:
                errors.append(exc)
        local_stop.set()

    def add_worker() -> None:
        with worker_lock:
            if stop_event.is_set() or local_stop.is_set():
                return
            active[0] += 1
        thread = threading.Thread(
            target=worker,
            name="BetterShutupDownloadWorker",
            daemon=True,
        )
        threads.append(thread)
        thread.start()

    def worker() -> None:
        try:
            while not stop_event.is_set() and not local_stop.is_set():
                with worker_lock:
                    if active[0] > desired[0]:
                        return
                try:
                    start, end = tasks.get(timeout=0.2)
                except queue.Empty:
                    if stop_event.is_set() or local_stop.is_set():
                        return
                    continue
                try:
                    _download_chunk(
                        url,
                        start,
                        end,
                        temp_path,
                        stop_event,
                        progress,
                    )
                    with remaining_lock:
                        remaining[0] -= 1
                        if remaining[0] <= 0:
                            completion_event.set()
                except DownloadCancelled:
                    return
                except BaseException as exc:  # Keep worker failures in the result.
                    logger.debug("下载分片失败", exc_info=exc)
                    set_error(exc)
                    return
                finally:
                    tasks.task_done()
        finally:
            with worker_lock:
                active[0] -= 1

    for _ in range(desired[0]):
        add_worker()

    previous_bytes = progress.value
    previous_time = time.monotonic()
    previous_speed: float | None = None
    while not stop_event.is_set() and not local_stop.is_set():
        with remaining_lock:
            if remaining[0] <= 0:
                break
        completion_event.wait(sample_seconds)
        if completion_event.is_set():
            break
        if stop_event.is_set() or local_stop.is_set():
            break
        now = time.monotonic()
        current_bytes = progress.value
        interval = max(0.001, now - previous_time)
        speed = (current_bytes - previous_bytes) / interval
        with worker_lock:
            desired_now = desired[0]
        if previous_speed is not None and tasks.qsize() > 0:
            if speed > previous_speed * 1.10:
                with worker_lock:
                    desired[0] += 1
                add_worker()
            elif speed < previous_speed * 0.80 and desired_now > 1:
                with worker_lock:
                    desired[0] = max(1, desired[0] - 1)
        previous_bytes = current_bytes
        previous_time = now
        previous_speed = speed

    local_stop.set()
    for thread in threads:
        thread.join(timeout=CONNECT_TIMEOUT + 5.0)
    with error_lock:
        if errors:
            raise errors[0]
    with remaining_lock:
        if remaining[0] != 0:
            raise DownloadError("下载未完成")
    if progress.value != total:
        raise DownloadError(
            f"下载长度不符: 期望 {total} 字节，实际 {progress.value} 字节"
        )
    return progress.value


def download_file(
    session_id: str,
    url: str,
    path: str,
    *,
    logger: logging.Logger | None = None,
    stop_event: threading.Event | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    start_workers: int = DEFAULT_START_WORKERS,
    sample_seconds: float = SAMPLE_SECONDS,
) -> DownloadResult:
    """Download ``url`` to the absolute ``path``.

    The target is replaced atomically only after a complete download.  On any
    failure the temporary file is removed and an ``err.err`` entry is appended
    in the target directory.  The function never communicates with the agent
    through the pipe.
    """

    logger = logger or logging.getLogger(__name__)
    stop = stop_event or threading.Event()
    started = time.monotonic()
    target = Path(path)
    progress = _Progress()
    temp_path: Path | None = None
    try:
        if urlsplit(url).scheme.lower() not in ("http", "https"):
            raise DownloadError("url 只支持 http/https")
        if not target.is_absolute():
            raise DownloadError("下载路径必须是绝对路径")
        if not target.name or target.name in (".", ".."):
            raise DownloadError("下载路径最后一段必须是文件名")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.parent / (
            f".{target.name}.{uuid.uuid4().hex}.part"
        )

        total, supports_ranges, final_url = _probe(url, stop)
        if stop.is_set():
            raise DownloadCancelled("下载已取消")

        if total == 0:
            temp_path.write_bytes(b"")
            bytes_written = 0
        elif supports_ranges and total is not None and total > 0:
            try:
                bytes_written = _range_download(
                    final_url,
                    total,
                    temp_path,
                    stop,
                    logger,
                    chunk_size=max(1, chunk_size),
                    start_workers=max(1, start_workers),
                    sample_seconds=max(0.01, sample_seconds),
                    progress=progress,
                )
            except RangeNotSupported:
                if stop.is_set():
                    raise DownloadCancelled("下载已取消")
                progress = _Progress()
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                bytes_written = _download_single(
                    final_url, temp_path, stop, progress
                )
        else:
            bytes_written = _download_single(
                final_url, temp_path, stop, progress
            )

        if stop.is_set():
            raise DownloadCancelled("下载已取消")
        os.replace(temp_path, target)
        temp_path = None
        return DownloadResult(
            session_id=session_id,
            url=url,
            path=str(target),
            success=True,
            bytes_written=bytes_written,
            elapsed=time.monotonic() - started,
        )
    except Exception as exc:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("无法删除临时下载文件: %s", temp_path)
        error_text = str(exc) or exc.__class__.__name__
        if isinstance(exc, DownloadCancelled):
            error_text = "下载已取消（应用可能正在关闭）"
        _append_error_file(
            target,
            url,
            error_text,
            progress.value,
            logger,
        )
        return DownloadResult(
            session_id=session_id,
            url=url,
            path=str(target),
            success=False,
            bytes_written=progress.value,
            error=error_text,
            elapsed=time.monotonic() - started,
        )


class DownloadManager:
    """Runs independent downloads in the background and exposes results."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._results: queue.Queue[DownloadResult] = queue.Queue()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._threads: set[threading.Thread] = set()

    def start(self, session_id: str, url: str, path: str) -> None:
        if self._stop.is_set():
            return
        thread = threading.Thread(
            target=self._run,
            args=(session_id, url, path),
            name=f"BetterShutupDownload-{session_id[:12]}",
            daemon=True,
        )
        with self._lock:
            self._threads.add(thread)
        thread.start()

    def _run(self, session_id: str, url: str, path: str) -> None:
        try:
            result = download_file(
                session_id,
                url,
                path,
                logger=self._logger,
                stop_event=self._stop,
            )
        except Exception as exc:  # Defensive boundary for the worker thread.
            self._logger.exception("文件下载线程发生未预期错误")
            result = DownloadResult(
                session_id=session_id,
                url=url,
                path=path,
                success=False,
                error=str(exc),
            )
        finally:
            with self._lock:
                self._threads.discard(threading.current_thread())
        self._results.put(result)

    def drain(self) -> list[DownloadResult]:
        results: list[DownloadResult] = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                return results

    def close(self, timeout: float = 2.0) -> None:
        self._stop.set()
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join(timeout=timeout)
