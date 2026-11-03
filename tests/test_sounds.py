from __future__ import annotations

import hashlib
from pathlib import Path
import wave

from better_shutup.sounds import (
    SAMPLE_RATE,
    SOUND_FILENAMES,
    ensure_default_sounds,
    validate_wav_file,
)


def test_generates_four_distinct_valid_wavs(tmp_path: Path) -> None:
    paths = ensure_default_sounds(tmp_path)
    assert set(paths) == set(SOUND_FILENAMES)
    assert "notify" in paths
    hashes = set()
    for kind, path in paths.items():
        assert path.is_file()
        with wave.open(str(path), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getframerate() == SAMPLE_RATE
            duration = wav.getnframes() / wav.getframerate()
            assert 0.2 <= duration <= 2.0, (kind, duration)
        hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    assert len(hashes) == 4


def test_existing_valid_sound_is_not_overwritten(tmp_path: Path) -> None:
    paths = ensure_default_sounds(tmp_path)
    custom = paths["action"].read_bytes()
    paths["complete"].write_bytes(custom)
    ensure_default_sounds(tmp_path)
    assert paths["complete"].read_bytes() == custom


def test_corrupt_default_sound_is_repaired(tmp_path: Path) -> None:
    paths = ensure_default_sounds(tmp_path)
    paths["complete"].write_bytes(b"custom placeholder audio data" * 4)
    ensure_default_sounds(tmp_path)
    ok, error = validate_wav_file(paths["complete"])
    assert ok, error


def test_validate_wav(tmp_path: Path) -> None:
    paths = ensure_default_sounds(tmp_path)
    ok, error = validate_wav_file(paths["complete"])
    assert ok and error == ""

    missing = tmp_path / "missing.wav"
    ok, error = validate_wav_file(missing)
    assert not ok and "不存在" in error

    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not a wav")
    ok, error = validate_wav_file(broken)
    assert not ok and error
