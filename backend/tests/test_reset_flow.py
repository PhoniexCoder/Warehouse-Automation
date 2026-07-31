"""Reset flow tests: manager flag wiring + worker reset semantics."""

import pytest

from cv_engine.orchestration.camera_manager import CameraManager
from cv_engine.orchestration.camera_worker import CameraWorker
from cv_engine.services.duplicate_guard import DuplicateGuard
from cv_engine.services.line_counter import LineCounter


def _make_worker(**overrides) -> CameraWorker:
    config = {
        "source_type": "simulated",
        "sim_scene": "entry",
        "line_y": 400,
        "detection_conf": 0.55,
        "count_conf": 0.65,
    }
    config.update(overrides)
    w = CameraWorker(
        camera_id="cam_test",
        config=config,
        event_queue=None,
        health_dict={},
        stop_event=None,
    )
    w._counter = LineCounter(line_y=w._line_y)
    w._line_counter = LineCounter()
    w._duplicate_guard = DuplicateGuard()
    return w


# ── _parse_count_line ────────────────────────────────────────────────────

def test_parse_count_line_dict_points():
    w = _make_worker(count_line={"points": [{"x": 0.1, "y": 0.2}, {"x": 0.8, "y": 0.9}]})
    assert w._count_line_points == [(0.1, 0.2), (0.8, 0.9)]


def test_parse_count_line_list_form():
    w = _make_worker(count_line=[[0.1, 0.2], [0.8, 0.9]])
    assert w._count_line_points == [(0.1, 0.2), (0.8, 0.9)]


def test_parse_count_line_invalid_returns_empty():
    assert _make_worker(count_line=None)._count_line_points == []
    assert _make_worker(count_line={"points": [{"x": 0.1}]})._count_line_points == []
    assert _make_worker(count_line=[{"x": 0.1, "y": 0.2}])._count_line_points == []
    assert _make_worker(count_line=[{"x": "bad", "y": 0.2}, {"x": 0.8, "y": 0.9}])._count_line_points == []


def test_parse_count_line_truncates_to_two_points():
    w = _make_worker(count_line=[[0.1, 0.2], [0.8, 0.9], [0.5, 0.5]])
    assert w._count_line_points == [(0.1, 0.2), (0.8, 0.9)]


# ── reset_state ──────────────────────────────────────────────────────────

def test_reset_state_zeroes_counters_and_health():
    w = _make_worker(count_line=[[0.1, 0.2], [0.8, 0.9]])
    w._counter.total_count = 5
    w._line_counter._segment_count = 3
    w._seen_tracks = {1, 2, 3}
    w._health["cam_test"] = {
        "status": "running",
        "counted": 5,
        "line_count": 3,
    }

    w.reset_state()

    assert w._counter.total_count == 0
    assert w._line_counter.line_count == 0
    assert w._seen_tracks == set()
    assert w._health["cam_test"]["counted"] == 0
    assert w._health["cam_test"]["line_count"] == 0


def test_reset_state_survives_missing_counters():
    w = _make_worker()
    w._counter = None
    w._line_counter = None
    w.reset_state()
    assert w._seen_tracks == set()


# ── _check_reset_flag ────────────────────────────────────────────────────

def test_check_reset_flag_triggers_and_consumes_flag():
    w = _make_worker(count_line=[[0.1, 0.2], [0.8, 0.9]])
    w._counter.total_count = 7
    w._line_counter._segment_count = 2
    w._reset_flags = {"cam_test": 12345.0}

    w._check_reset_flag()

    assert w._counter.total_count == 0
    assert w._line_counter.line_count == 0
    assert "cam_test" not in w._reset_flags


def test_check_reset_flag_noop_without_flags():
    w = _make_worker()
    w._counter.total_count = 4
    w._reset_flags = None
    w._check_reset_flag()
    assert w._counter.total_count == 4

    w._reset_flags = {}
    w._check_reset_flag()
    assert w._counter.total_count == 4


# ── CameraManager.reset_camera ───────────────────────────────────────────

def test_manager_reset_camera_unknown_camera_returns_false():
    m = CameraManager()
    m._reset_flags = {}
    assert m.reset_camera("nope") is False


def test_manager_reset_camera_sets_flag_for_known_camera():
    m = CameraManager()
    m._reset_flags = {}
    m.add_camera("cam_test", {"source_type": "simulated"})
    assert m.reset_camera("cam_test") is True
    assert "cam_test" in m._reset_flags


def test_manager_reset_camera_without_manager_returns_false():
    m = CameraManager()
    m.add_camera("cam_test", {"source_type": "simulated"})
    assert m.reset_camera("cam_test") is False


# ── detection_skip ───────────────────────────────────────────────────────

def _run_worker(w, min_reads: int = 10):
    """Run the worker loop in a thread until the fake source read enough frames."""
    import queue
    import threading
    import time

    import numpy as np

    class FakeSource:
        def __init__(self):
            self.frame = np.full((240, 320, 3), 128, dtype=np.uint8)
            self.read_count = 0

        def read(self):
            self.read_count += 1
            return True, self.frame, None

        def release(self):
            pass

    fake = FakeSource()
    w._frame_source = fake
    w._publish_frame = lambda frame: None
    w._event_queue = queue.Queue()
    w._stop = threading.Event()

    det_calls = {"n": 0}

    def counting_process(frame, pre_dets):
        det_calls["n"] += 1
        return [], [{"x1": 0, "y1": 0, "x2": 10, "y2": 10, "label": "x", "confidence": 0.9}]

    w._process_frame = counting_process

    thread = threading.Thread(target=w.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline and fake.read_count < min_reads:
        time.sleep(0.01)
    w._stop.set()
    thread.join(timeout=3)

    return fake.read_count, det_calls["n"]


def test_detection_skip_throttles_detection_calls():
    w = _make_worker(source_type="simulated", detection_skip=2, target_fps=1000)
    w._init_components = lambda: None

    reads, dets = _run_worker(w)

    assert reads >= 10
    assert dets >= 3
    assert dets < reads
    assert dets * 2 >= reads - 1


def test_detection_skip_default_runs_every_frame():
    w = _make_worker(source_type="simulated", target_fps=1000)
    w._init_components = lambda: None

    reads, dets = _run_worker(w)

    assert reads >= 10
    assert dets == reads
