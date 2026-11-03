"""Built-in notification sounds and non-blocking playback."""

from __future__ import annotations

import array
import logging
import math
from pathlib import Path
import queue
import sys
import threading
import wave

try:
    import winsound
except ImportError:  # pragma: no cover - BetterShutup is Windows-only
    winsound = None  # type: ignore[assignment]

SAMPLE_RATE = 44_100
SOUND_FILENAMES = {
    "complete": "complete.wav",
    "action": "action.wav",
    "error": "error.wav",
    "notify": "notify.wav",
}


def _smooth_envelope(index: int, count: int, attack: float, release: float) -> float:
    if count <= 1:
        return 0.0
    t = index / count
    attack_fraction = max(attack, 1.0 / count)
    release_fraction = max(release, 1.0 / count)
    if t < attack_fraction:
        x = t / attack_fraction
        return x * x * (3.0 - 2.0 * x)
    if t > 1.0 - release_fraction:
        x = (1.0 - t) / release_fraction
        return x * x * (3.0 - 2.0 * x)
    return 1.0


def _tone(
    frequency: float,
    duration: float,
    *,
    amplitude: float = 0.35,
    partials: tuple[float, ...] = (1.0,),
    attack: float = 0.012,
    release: float = 0.055,
) -> list[float]:
    count = max(1, int(SAMPLE_RATE * duration))
    samples: list[float] = []
    for index in range(count):
        t = index / SAMPLE_RATE
        envelope = _smooth_envelope(
            index, count, attack / duration, release / duration
        )
        value = 0.0
        for harmonic, weight in enumerate(partials, start=1):
            value += weight * math.sin(
                2.0 * math.pi * frequency * harmonic * t
            )
        samples.append(amplitude * envelope * value)
    return samples


def _silence(duration: float) -> list[float]:
    return [0.0] * max(0, int(SAMPLE_RATE * duration))


def _normalize(samples: list[float], peak: float = 0.88) -> list[float]:
    highest = max((abs(value) for value in samples), default=0.0)
    if highest <= peak or highest == 0.0:
        return samples
    factor = peak / highest
    return [value * factor for value in samples]


def _render_complete() -> list[float]:
    samples: list[float] = []
    for frequency in (523.25, 659.25, 783.99):
        samples.extend(
            _tone(
                frequency,
                0.14,
                amplitude=0.36,
                partials=(1.0, 0.18, 0.06),
                attack=0.010,
                release=0.075,
            )
        )
        samples.extend(_silence(0.018))
    return _normalize(samples)


def _render_action() -> list[float]:
    samples: list[float] = []
    for frequency in (987.77, 987.77):
        samples.extend(
            _tone(
                frequency,
                0.13,
                amplitude=0.34,
                partials=(1.0, 0.28, 0.10),
                attack=0.008,
                release=0.060,
            )
        )
        samples.extend(_silence(0.115))
    return _normalize(samples)


def _render_notify() -> list[float]:
    samples: list[float] = []
    for frequency, duration in ((659.25, 0.16), (880.0, 0.22)):
        samples.extend(
            _tone(
                frequency,
                duration,
                amplitude=0.30,
                partials=(1.0, 0.12, 0.04),
                attack=0.012,
                release=0.090,
            )
        )
        samples.extend(_silence(0.035))
    return _normalize(samples, peak=0.78)


def _render_error() -> list[float]:
    samples: list[float] = []
    for frequency in (220.0, 164.81):
        samples.extend(
            _tone(
                frequency,
                0.30,
                amplitude=0.40,
                partials=(1.0, 0.42, 0.22, 0.10),
                attack=0.015,
                release=0.110,
            )
        )
        samples.extend(_silence(0.045))
    return _normalize(samples)


_RENDERERS = {
    "complete": _render_complete,
    "action": _render_action,
    "error": _render_error,
    "notify": _render_notify,
}


def _write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array.array(
        "h",
        (
            max(-32768, min(32767, int(round(value * 32767.0))))
            for value in samples
        ),
    )
    if pcm.itemsize != 2:  # pragma: no cover - all supported Python builds
        raise RuntimeError("当前平台的 array('h') 不是 16 位")
    if sys.byteorder != "little":
        pcm.byteswap()

    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with wave.open(str(temporary), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm.tobytes())
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def ensure_default_sounds(directory: Path) -> dict[str, Path]:
    """Create any missing built-in WAVs and return their paths."""

    paths: dict[str, Path] = {}
    for kind, filename in SOUND_FILENAMES.items():
        path = directory / filename
        if not path.is_file() or not validate_wav_file(path)[0]:
            _write_wav(path, _RENDERERS[kind]())
        paths[kind] = path
    return paths


def validate_wav_file(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "文件不存在"
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getnchannels() not in (1, 2):
                return False, "仅支持单声道或双声道 WAV"
            if wav.getsampwidth() not in (1, 2, 3, 4):
                return False, "不支持的 WAV 采样位深"
            if wav.getnframes() <= 0:
                return False, "WAV 文件没有音频数据"
    except (OSError, EOFError, wave.Error) as exc:
        return False, f"无法解析 WAV 文件: {exc}"
    return True, ""


class SoundPlayer:
    """Serializes playback in a daemon worker so sounds are not cut off."""

    def __init__(
        self,
        defaults: dict[str, Path],
        overrides: dict[str, str | None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._defaults = dict(defaults)
        self._overrides = dict(overrides or {})
        self._logger = logger or logging.getLogger(__name__)
        self._queue: queue.Queue[tuple[str, str | None] | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._worker,
            name="BetterShutupSounds",
            daemon=True,
        )
        self._thread.start()

    def set_overrides(self, overrides: dict[str, str | None]) -> None:
        self._overrides = dict(overrides)

    def play_kind(self, kind: str) -> None:
        if kind in SOUND_FILENAMES:
            self._queue.put((kind, None))

    def preview(self, path: str | Path | None, kind: str = "complete") -> None:
        self._queue.put((kind, str(path) if path else None))

    def close(self, timeout: float = 1.5) -> None:
        self._queue.put(None)
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _resolve_path(self, kind: str, explicit: str | None) -> Path | None:
        candidates: list[Path] = []
        if explicit:
            candidates.append(Path(explicit))
        override = self._overrides.get(kind)
        if override:
            candidates.append(Path(override))
        default = self._defaults.get(kind)
        if default:
            candidates.append(default)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            kind, explicit = item
            path = self._resolve_path(kind, explicit)
            if path is None:
                self._logger.warning("找不到可用音效文件（类型=%s）", kind)
                self._fallback_beep()
                continue
            if not self._play_file(path):
                default = self._defaults.get(kind)
                if default and default != path and self._play_file(default):
                    continue
                self._fallback_beep()

    def _play_file(self, path: Path) -> bool:
        if winsound is None:
            return False
        try:
            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_NODEFAULT,
            )
            return True
        except RuntimeError as exc:
            self._logger.warning("播放音效失败 %s: %s", path, exc)
            return False

    def _fallback_beep(self) -> None:
        if winsound is None:
            return
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except RuntimeError:
            pass
