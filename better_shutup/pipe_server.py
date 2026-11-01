"""Message-mode named-pipe server for BetterShutup."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from .win32_pipe import (
    PipeError,
    PipeMessageTooLarge,
    close_handle,
    connect_pipe,
    create_pipe_instance,
    disconnect_pipe,
    open_pipe_probe,
    read_pipe_message,
)

FrameHandler = Callable[[bytes], None]
ErrorHandler = Callable[[str], None]


class PipeServer:
    """Accepts one complete frame per client connection.

    The callback is invoked from a worker thread and must not touch Tk.
    """

    def __init__(
        self,
        pipe_name: str,
        on_frame: FrameHandler,
        on_error: ErrorHandler | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.pipe_name = pipe_name
        self._on_frame = on_frame
        self._on_error = on_error or (lambda _message: None)
        self._logger = logger or logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("管道服务已经启动")
        # Create the first instance synchronously so startup failures (for
        # example, another instance already owns the pipe) are visible now.
        first_handle = create_pipe_instance(self.pipe_name, first=True)
        self._stop_event.clear()
        self._started = True
        self._thread = threading.Thread(
            target=self._accept_loop,
            args=(first_handle,),
            name="BetterShutupPipeAccept",
            daemon=True,
        )
        self._thread.start()
        self._logger.info("命名管道服务已启动: %s", self.pipe_name)

    def stop(self, timeout: float = 2.0) -> None:
        if not self._started:
            return
        self._stop_event.set()
        # Wake the blocking ConnectNamedPipe call with a harmless self-connect.
        try:
            open_pipe_probe(self.pipe_name, timeout_ms=300)
        except Exception:
            pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._started = False
        self._thread = None
        self._logger.info("命名管道服务已停止。")

    @property
    def is_running(self) -> bool:
        return self._started and self._thread is not None and self._thread.is_alive()

    def _accept_loop(self, pending_handle: int) -> None:
        handle: int | None = pending_handle
        try:
            while not self._stop_event.is_set():
                if handle is None:
                    try:
                        handle = create_pipe_instance(self.pipe_name, first=False)
                    except PipeError as exc:
                        if not self._stop_event.is_set():
                            self._report_error(f"无法创建新的管道实例: {exc}")
                        break

                try:
                    connect_pipe(handle)
                except PipeError as exc:
                    close_handle(handle)
                    handle = None
                    if self._stop_event.is_set():
                        break
                    self._report_error(f"接受管道连接失败: {exc}")
                    continue

                if self._stop_event.is_set():
                    close_handle(handle)
                    handle = None
                    break

                # A client may close immediately after writing.  In that case
                # ConnectNamedPipe returns ERROR_NO_DATA (connected=False),
                # but the message is still buffered and must be read.
                client_handle = handle
                handle = None
                # Create the next listening instance before dispatching the
                # connected one so there is no window during which the pipe
                # has no free instance.
                try:
                    handle = create_pipe_instance(self.pipe_name, first=False)
                except PipeError as exc:
                    self._report_error(f"无法创建新的管道实例: {exc}")
                threading.Thread(
                    target=self._handle_client,
                    args=(client_handle,),
                    name="BetterShutupPipeClient",
                    daemon=True,
                ).start()
                if handle is None and not self._stop_event.is_set():
                    break
        finally:
            if handle is not None:
                close_handle(handle)

    def _handle_client(self, handle: int) -> None:
        try:
            frame = read_pipe_message(handle)
            if frame is None:
                return
            self._on_frame(frame)
        except PipeMessageTooLarge as exc:
            if not self._stop_event.is_set():
                self._report_error(str(exc))
        except PipeError as exc:
            if not self._stop_event.is_set():
                self._report_error(str(exc))
        except Exception as exc:  # Defensive: never kill the listener silently.
            self._logger.exception("处理管道消息时发生未预期错误")
            if not self._stop_event.is_set():
                self._report_error(f"处理管道消息时发生错误: {exc}")
        finally:
            disconnect_pipe(handle)
            close_handle(handle)

    def _report_error(self, message: str) -> None:
        self._logger.warning(message)
        try:
            self._on_error(message)
        except Exception:
            self._logger.exception("错误回调执行失败")
