import tempfile
from pathlib import Path

import numpy as np
import pytest

from cv_engine.orchestration.frame_store import FrameStore


def test_publish_and_read():
    with tempfile.TemporaryDirectory() as tmp:
        store = FrameStore(cache_dir=tmp)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        store.publish("cam_test", frame)
        data = store.latest_bytes("cam_test")

        assert data is not None
        assert len(data) > 0
        assert data[:2] == b"\xff\xd8"


def test_latest_mtime_increases():
    with tempfile.TemporaryDirectory() as tmp:
        store = FrameStore(cache_dir=tmp)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        t0 = store.latest_mtime("cam_test")
        assert t0 == 0.0

        store.publish("cam_test", frame)
        t1 = store.latest_mtime("cam_test")
        assert t1 > 0.0


def test_missing_camera_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        store = FrameStore(cache_dir=tmp)
        assert store.latest_bytes("nonexistent") is None


def test_publish_quality_affects_size():
    with tempfile.TemporaryDirectory() as tmp:
        store = FrameStore(cache_dir=tmp)
        rng = np.random.default_rng(42)
        frame = rng.integers(0, 256, (200, 200, 3), dtype=np.uint8)

        store.publish("cam_test", frame, quality=95)
        high = len(store.latest_bytes("cam_test"))

        store.publish("cam_test", frame, quality=10)
        low = len(store.latest_bytes("cam_test"))

        assert high > low
