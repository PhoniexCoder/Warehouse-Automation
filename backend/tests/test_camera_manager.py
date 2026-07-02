import time

import pytest

from cv_engine.orchestration.camera_manager import CameraManager


@pytest.fixture
def manager():
    m = CameraManager()
    yield m
    try:
        m.stop_all()
    except Exception:
        pass


def test_add_camera(manager):
    manager.add_camera("cam_1", {
        "source_type": "simulated",
        "sim_scene": "entry",
        "line_y": 400,
    })
    status = manager.get_status()
    assert "cam_1" in status["cameras"]


def test_start_stop_cycle(manager):
    manager.add_camera("cam_test", {
        "source_type": "simulated",
        "sim_scene": "entry",
        "line_y": 400,
        "tracker": "bytetrack",
    })
    manager.start_all()
    assert manager._running is True

    status = manager.get_status()
    assert "cam_test" in status["cameras"]
    assert status["running"] is True

    manager.stop_all()
    assert manager._running is False


def test_multiple_cameras_launch_separate_processes(manager):
    for i in range(4):
        manager.add_camera(f"cam_{i}", {
            "source_type": "simulated",
            "sim_scene": "entry",
            "line_y": 400,
            "tracker": "bytetrack",
        })

    manager.start_all()

    status = manager.get_status()
    assert len(status["cameras"]) == 4

    for cam_id, info in status["cameras"].items():
        assert info["alive"] is True
        assert info["pid"] is not None
        assert isinstance(info["pid"], int)

    pids = [info["pid"] for info in status["cameras"].values()]
    assert len(set(pids)) == 4, "Each camera must have a unique PID"

    manager.stop_all()


def test_camera_crash_does_not_affect_others(manager):
    manager.add_camera("cam_a", {
        "source_type": "simulated",
        "sim_scene": "entry",
        "line_y": 400,
    })
    manager.add_camera("cam_b", {
        "source_type": "simulated",
        "sim_scene": "conveyor",
        "line_y": 400,
    })

    manager.start_all()
    time.sleep(1)

    worker_a = manager._workers.get("cam_a")
    assert worker_a is not None and worker_a.is_alive()

    worker_a.kill()
    worker_a.join(timeout=2)
    assert not worker_a.is_alive()

    time.sleep(3)

    status = manager.get_status()
    assert status["cameras"]["cam_a"]["alive"] is True
    assert status["cameras"]["cam_b"]["alive"] is True

    manager.stop_all()


def test_get_status_returns_all_fields(manager):
    manager.add_camera("cam_1", {
        "source_type": "simulated",
        "sim_scene": "entry",
        "line_y": 400,
        "display_name": "Entry Gate",
    })
    manager.start_all()
    time.sleep(1)

    status = manager.get_status()
    assert "cameras" in status
    assert "consumer" in status
    assert "running" in status
    assert "queue_size" in status

    cam = status["cameras"]["cam_1"]
    assert "pid" in cam
    assert "alive" in cam
    assert "health" in cam
    assert "config" in cam

    manager.stop_all()


def test_event_queue_created(manager):
    manager.add_camera("cam_1", {
        "source_type": "simulated",
        "sim_scene": "entry",
        "line_y": 400,
    })
    assert manager.event_queue is None

    manager.start_all()
    assert manager.event_queue is not None

    manager.stop_all()
