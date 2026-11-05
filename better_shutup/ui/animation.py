"""Small, dependency-free Tk animation helpers."""

from __future__ import annotations

import time
import tkinter as tk

FRAME_MS = 16


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def fade_in_window(window: tk.Misc, duration_ms: int = 220) -> None:
    """Fade a mapped top-level window in using an ease-out curve."""

    try:
        window.attributes("-alpha", 0.0)
    except tk.TclError:
        return
    started = time.monotonic()
    duration = max(1, duration_ms) / 1000.0

    def frame() -> None:
        try:
            progress = min(1.0, (time.monotonic() - started) / duration)
            window.attributes("-alpha", ease_out_cubic(progress))
            if progress < 1.0:
                window.after(FRAME_MS, frame)
            else:
                window.attributes("-alpha", 1.0)
        except tk.TclError:
            return

    window.after(FRAME_MS, frame)
