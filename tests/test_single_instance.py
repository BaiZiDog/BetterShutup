from __future__ import annotations

import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows named mutexes only"
)
if sys.platform != "win32":
    pytest.skip("Windows named mutexes only", allow_module_level=True)

from better_shutup.single_instance import SingleInstance


def test_mutex_is_exclusive() -> None:
    name = "Local\\BetterShutupTest-" + uuid.uuid4().hex
    first = SingleInstance(name)
    second = SingleInstance(name)
    third = SingleInstance(name)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        first.close()
        assert third.acquire() is True
    finally:
        first.close()
        second.close()
        third.close()
