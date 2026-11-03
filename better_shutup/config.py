"""Persistent application settings and data-directory helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .core import (
    DEFAULT_COUNTDOWN_SECONDS,
    MAX_COUNTDOWN_SECONDS,
    MIN_COUNTDOWN_SECONDS,
)

CONFIG_VERSION = 1
SOUND_KINDS = ("complete", "action", "error", "notify")


def app_data_dir() -> Path:
    override = os.environ.get("BETTER_SHUTUP_DATA_DIR")
    if override:
        return Path(override).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BetterShutup"
    return Path.home() / ".better-shutup"


def config_path(data_dir: Path | None = None) -> Path:
    return (data_dir or app_data_dir()) / "config.json"


def log_path(data_dir: Path | None = None) -> Path:
    return (data_dir or app_data_dir()) / "better-shutup.log"


def sounds_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or app_data_dir()) / "sounds"


def ensure_data_dirs(data_dir: Path | None = None) -> Path:
    base = data_dir or app_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    sounds_dir(base).mkdir(parents=True, exist_ok=True)
    return base


@dataclass(slots=True)
class AppConfig:
    countdown_seconds: int = DEFAULT_COUNTDOWN_SECONDS
    sound_overrides: dict[str, str | None] = field(
        default_factory=lambda: {kind: None for kind in SOUND_KINDS}
    )

    def sound_for(self, kind: str) -> str | None:
        value = self.sound_overrides.get(kind)
        if isinstance(value, str) and value.strip():
            return value
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "countdown_seconds": self.countdown_seconds,
            "sounds": {
                kind: self.sound_for(kind) for kind in SOUND_KINDS
            },
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "AppConfig":
        config = cls()
        if not isinstance(raw, dict):
            return config

        seconds = raw.get("countdown_seconds", DEFAULT_COUNTDOWN_SECONDS)
        if isinstance(seconds, int) and not isinstance(seconds, bool):
            config.countdown_seconds = max(
                MIN_COUNTDOWN_SECONDS, min(MAX_COUNTDOWN_SECONDS, seconds)
            )

        sounds = raw.get("sounds")
        if isinstance(sounds, dict):
            for kind in SOUND_KINDS:
                value = sounds.get(kind)
                if isinstance(value, str) and value.strip():
                    config.sound_overrides[kind] = value
                else:
                    config.sound_overrides[kind] = None
        return config


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()

    def load(self) -> AppConfig:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return AppConfig()
        except (OSError, ValueError, TypeError):
            return AppConfig()
        return AppConfig.from_dict(raw)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix="config.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                json.dump(
                    config.to_dict(),
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
