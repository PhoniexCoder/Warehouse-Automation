import numpy as np
import pytest

from cv_engine.services.tracker import ObjectTracker


def test_tracker_empty_input():
    tracker = ObjectTracker()
    result = tracker.update([])
    assert result == []


def test_tracker_returns_correct_format():
    tracker = ObjectTracker()
    detections = [
        {"bbox": [10, 20, 110, 120], "confidence": 0.9},
        {"bbox": [200, 50, 300, 150], "confidence": 0.85},
    ]
    result = tracker.update(detections)
    for r in result:
        assert "track_id" in r
        assert "bbox" in r
        assert len(r["bbox"]) == 4
        assert isinstance(r["track_id"], int)
