from __future__ import annotations

import json
from pathlib import Path

from better_shutup.config import (
    AppConfig,
    ConfigStore,
    DEFAULT_COUNTDOWN_SECONDS,
    SOUND_KINDS,
    config_path,
    ensure_data_dirs,
)
from better_shutup.core import MAX_COUNTDOWN_SECONDS, MIN_COUNTDOWN_SECONDS


def test_defaults() -> None:
    config = AppConfig()
    assert config.countdown_seconds == DEFAULT_COUNTDOWN_SECONDS
    assert SOUND_KINDS == ("complete", "action", "error", "notify")
    assert config.sound_for("complete") is None
    assert all(config.sound_for(kind) is None for kind in config.sound_overrides)


def test_from_dict_clamps_and_ignores_bad_values() -> None:
    config = AppConfig.from_dict(
        {
            "countdown_seconds": 999_999,
            "sounds": {
                "complete": "  ",
                "action": 123,
                "error": "C:/x.wav",
                "notify": "C:/n.wav",
            },
        }
    )
    assert config.countdown_seconds == MAX_COUNTDOWN_SECONDS
    assert config.sound_for("complete") is None
    assert config.sound_for("action") is None
    assert config.sound_for("error") == "C:/x.wav"
    assert config.sound_for("notify") == "C:/n.wav"

    low = AppConfig.from_dict({"countdown_seconds": 1})
    assert low.countdown_seconds == MIN_COUNTDOWN_SECONDS

    bad = AppConfig.from_dict([])
    assert bad.countdown_seconds == DEFAULT_COUNTDOWN_SECONDS


def test_store_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.json"
    store = ConfigStore(path)
    assert store.load().countdown_seconds == DEFAULT_COUNTDOWN_SECONDS

    config = AppConfig(
        countdown_seconds=15,
        sound_overrides={
            "complete": "C:/sounds/complete.wav",
            "action": None,
            "error": None,
            "notify": "C:/sounds/notify.wav",
        },
    )
    store.save(config)
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["countdown_seconds"] == 15
    assert raw["sounds"]["complete"] == "C:/sounds/complete.wav"
    assert raw["sounds"]["notify"] == "C:/sounds/notify.wav"

    loaded = store.load()
    assert loaded.countdown_seconds == 15
    assert loaded.sound_for("complete") == "C:/sounds/complete.wav"
    assert loaded.sound_for("action") is None
    assert loaded.sound_for("notify") == "C:/sounds/notify.wav"


def test_corrupt_config_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert ConfigStore(path).load().countdown_seconds == DEFAULT_COUNTDOWN_SECONDS

    path.write_text("null", encoding="utf-8")
    assert ConfigStore(path).load().countdown_seconds == DEFAULT_COUNTDOWN_SECONDS


def test_ensure_data_dirs(tmp_path: Path) -> None:
    base = ensure_data_dirs(tmp_path / "data")
    assert base.is_dir()
    assert (base / "sounds").is_dir()
    assert config_path(base) == base / "config.json"
