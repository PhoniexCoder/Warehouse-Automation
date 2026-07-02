import tempfile
from pathlib import Path

import pytest

from cv_engine.database import (
    NO_QR,
    INVALID_QR,
    DAMAGED_QR,
    InvalidQrLog,
    create_tables,
    detection_exists,
    get_all_detections,
    get_all_events,
    get_detection_by_id,
    get_duplicate_events,
    get_invalid_qr_logs,
    get_total_count,
    get_total_invalid_qr_count,
    reset_database,
    save_detection,
    save_duplicate_event,
    save_invalid_qr,
)


@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    reset_database()
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr("cv_engine.config.settings.SETTINGS.data_dir", tmpdir)
        create_tables()
        yield


# ---------------------------------------------------------------------------
# save_detection
# ---------------------------------------------------------------------------


def test_save_and_get_by_id():
    record = save_detection(
        tracking_id=42,
        qr_data="BOX-042",
        camera_id="camera_01",
        counted_status=True,
        box_x=10,
        box_y=20,
        box_width=100,
        box_height=200,
    )
    assert record.id is not None
    assert record.tracking_id == 42
    assert record.qr_data == "BOX-042"
    assert record.camera_id == "camera_01"
    assert record.counted_status is True

    fetched = get_detection_by_id(record.id)
    assert fetched is not None
    assert fetched.tracking_id == 42
    assert fetched.qr_data == "BOX-042"
    assert fetched.camera_id == "camera_01"


def test_save_detection_default_camera():
    record = save_detection(tracking_id=1, qr_data="BOX-001", counted_status=True,
                            box_x=0, box_y=0, box_width=50, box_height=50)
    assert record.camera_id == "camera_01"


def test_save_detection_custom_camera():
    record = save_detection(tracking_id=2, qr_data="BOX-002", camera_id="rtsp_cam_3",
                            counted_status=True, box_x=0, box_y=0, box_width=50, box_height=50)
    assert record.camera_id == "rtsp_cam_3"


# ---------------------------------------------------------------------------
# save_invalid_qr
# ---------------------------------------------------------------------------


def test_save_invalid_qr():
    record = save_invalid_qr(
        tracking_id=55,
        error_type=INVALID_QR,
        camera_id="camera_02",
        box_x=10,
        box_y=20,
        box_width=100,
        box_height=200,
    )
    assert record.id is not None
    assert record.tracking_id == 55
    assert record.error_type == INVALID_QR
    assert record.camera_id == "camera_02"


def test_save_invalid_qr_defaults():
    record = save_invalid_qr(tracking_id=56, box_x=0, box_y=0, box_width=50, box_height=50)
    assert record.camera_id == "camera_01"
    assert record.error_type == NO_QR


def test_save_invalid_qr_unknown_type_falls_back():
    record = save_invalid_qr(tracking_id=57, error_type="UNKNOWN", box_x=0, box_y=0, box_width=10, box_height=10)
    assert record.error_type == NO_QR


def test_get_invalid_qr_logs():
    save_invalid_qr(tracking_id=1, error_type=NO_QR, camera_id="cam_a", box_x=0, box_y=0, box_width=10, box_height=10)
    save_invalid_qr(tracking_id=2, error_type=INVALID_QR, camera_id="cam_b", box_x=0, box_y=0, box_width=10, box_height=10)

    logs = get_invalid_qr_logs()
    assert len(logs) == 2
    assert logs[0].tracking_id == 2


def test_get_invalid_qr_logs_filter():
    save_invalid_qr(tracking_id=1, error_type=NO_QR, box_x=0, box_y=0, box_width=10, box_height=10)
    save_invalid_qr(tracking_id=2, error_type=INVALID_QR, box_x=0, box_y=0, box_width=10, box_height=10)

    filtered = get_invalid_qr_logs(error_type_filter=INVALID_QR)
    assert len(filtered) == 1
    assert filtered[0].tracking_id == 2


def test_get_invalid_qr_logs_pagination():
    for i in range(5):
        save_invalid_qr(tracking_id=i, box_x=0, box_y=0, box_width=10, box_height=10)

    page = get_invalid_qr_logs(limit=2, offset=0)
    assert len(page) == 2


def test_get_total_invalid_qr_count():
    assert get_total_invalid_qr_count() == 0
    save_invalid_qr(tracking_id=1, box_x=0, box_y=0, box_width=10, box_height=10)
    save_invalid_qr(tracking_id=2, box_x=0, box_y=0, box_width=10, box_height=10)
    assert get_total_invalid_qr_count() == 2


# ---------------------------------------------------------------------------
# save_duplicate_event
# ---------------------------------------------------------------------------


def test_save_duplicate_event():
    record = save_duplicate_event(
        tracking_id=99,
        qr_data="BOX-099",
        camera_id="cam_x",
        box_x=10,
        box_y=20,
        box_width=100,
        box_height=200,
    )
    assert record.id is not None
    assert record.tracking_id == 99
    assert record.qr_data == "BOX-099"
    assert record.camera_id == "cam_x"


def test_save_duplicate_event_no_qr():
    record = save_duplicate_event(tracking_id=100, box_x=0, box_y=0, box_width=50, box_height=50)
    assert record.id is not None
    assert record.qr_data is None


def test_get_duplicate_events():
    save_duplicate_event(tracking_id=1, camera_id="cam_a", box_x=0, box_y=0, box_width=10, box_height=10)
    save_duplicate_event(tracking_id=1, camera_id="cam_a", box_x=0, box_y=0, box_width=10, box_height=10)
    save_duplicate_event(tracking_id=2, camera_id="cam_b", box_x=0, box_y=0, box_width=10, box_height=10)

    events = get_duplicate_events()
    assert len(events) == 3


# ---------------------------------------------------------------------------
# get_all_detections / get_total_count / detection_exists
# ---------------------------------------------------------------------------


def test_get_all_detections():
    save_detection(tracking_id=1, qr_data="BOX-001", counted_status=True, box_x=0, box_y=0, box_width=50, box_height=50)
    save_detection(tracking_id=2, qr_data="BOX-002", counted_status=True, box_x=0, box_y=0, box_width=50, box_height=50)

    all_dets = get_all_detections()
    assert len(all_dets) == 2


def test_detection_exists_returns_true_for_logged():
    save_detection(tracking_id=1, qr_data="BOX-001", counted_status=True, box_x=0, box_y=0, box_width=50, box_height=50)
    assert detection_exists(1) is True


def test_detection_exists_returns_false_for_unlogged():
    assert detection_exists(999) is False


def test_get_total_count():
    assert get_total_count() == 0

    save_detection(tracking_id=1, counted_status=True, box_x=0, box_y=0, box_width=50, box_height=50)
    save_detection(tracking_id=2, counted_status=True, box_x=0, box_y=0, box_width=50, box_height=50)
    assert get_total_count() == 2

    save_detection(tracking_id=1, counted_status=False, box_x=0, box_y=0, box_width=50, box_height=50)
    assert get_total_count() == 2


def test_counted_only_filter():
    save_detection(tracking_id=1, counted_status=True, box_x=0, box_y=0, box_width=50, box_height=50)
    save_detection(tracking_id=2, counted_status=False, box_x=0, box_y=0, box_width=50, box_height=50)

    counted = get_all_detections(counted_only=True)
    not_counted = get_all_detections(counted_only=False)

    assert len(counted) == 1
    assert len(not_counted) == 1


def test_to_dict():
    record = save_detection(tracking_id=5, qr_data="BOX-005", camera_id="cam_1",
                            counted_status=True, box_x=10, box_y=20, box_width=100, box_height=200)
    d = record.to_dict()
    assert d["tracking_id"] == 5
    assert d["qr_data"] == "BOX-005"
    assert d["camera_id"] == "cam_1"
    assert d["counted_status"] is True
    assert d["box_x"] == 10
    assert d["box_y"] == 20
    assert d["box_width"] == 100
    assert d["box_height"] == 200
    assert "id" in d
    assert "timestamp" in d


def test_get_detection_by_id_nonexistent():
    assert get_detection_by_id(9999) is None


def test_save_multiple_then_query():
    for i in range(5):
        save_detection(tracking_id=i, counted_status=True, box_x=0, box_y=0, box_width=10, box_height=10)

    results = get_all_detections(limit=3, offset=0)
    assert len(results) == 3

    results_page2 = get_all_detections(limit=3, offset=3)
    assert len(results_page2) == 2


def test_repr():
    record = save_detection(tracking_id=10, qr_data="BOX-010", counted_status=True, box_x=0, box_y=0, box_width=10, box_height=10)
    rep = repr(record)
    assert "Detection" in rep
    assert "tracking_id=10" in rep
    assert "BOX-010" in rep


# ---------------------------------------------------------------------------
# get_all_events — unified feed
# ---------------------------------------------------------------------------


def test_get_all_events_empty():
    events = get_all_events()
    assert events == []


def test_get_all_events_contains_all_types():
    save_detection(tracking_id=1, qr_data="BOX-001", counted_status=True, box_x=0, box_y=0, box_width=10, box_height=10)
    save_invalid_qr(tracking_id=2, error_type=NO_QR, box_x=0, box_y=0, box_width=10, box_height=10)
    save_duplicate_event(tracking_id=1, qr_data="BOX-001", box_x=0, box_y=0, box_width=10, box_height=10)

    events = get_all_events(limit=10)
    assert len(events) == 3

    event_types = {e["event_type"] for e in events}
    assert event_types == {"detection", "invalid_qr", "duplicate"}


def test_get_all_events_respects_limit():
    for i in range(5):
        save_detection(tracking_id=i, counted_status=True, box_x=0, box_y=0, box_width=10, box_height=10)

    events = get_all_events(limit=3)
    assert len(events) == 3


def test_get_all_events_sorted_by_timestamp():
    save_detection(tracking_id=1, counted_status=True, box_x=0, box_y=0, box_width=10, box_height=10)
    save_invalid_qr(tracking_id=2, error_type=INVALID_QR, box_x=0, box_y=0, box_width=10, box_height=10)

    events = get_all_events(limit=10)
    assert len(events) == 2
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# Event isolation: tables don't leak
# ---------------------------------------------------------------------------


def test_tables_are_independent():
    save_detection(tracking_id=1, counted_status=True, box_x=0, box_y=0, box_width=10, box_height=10)
    save_invalid_qr(tracking_id=1, box_x=0, box_y=0, box_width=10, box_height=10)
    save_duplicate_event(tracking_id=1, box_x=0, box_y=0, box_width=10, box_height=10)

    assert len(get_all_detections()) == 1
    assert len(get_invalid_qr_logs()) == 1
    assert len(get_duplicate_events()) == 1
