import numpy as np

from cv_engine.services.box_processor import BoxProcessor
from cv_engine.services.line_counter import LineCounter


def test_empty_pipeline():
    processor = BoxProcessor()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = processor.process_detections(frame, [])
    assert result == []


def test_detection_gets_qr_fields():
    processor = BoxProcessor()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = [
        {"bbox": [0, 0, 100, 100], "confidence": 0.9},
    ]

    result = processor.process_detections(frame, detections)
    assert len(result) == 1
    assert "qr_data" in result[0]
    assert "has_qr" in result[0]
    assert "qr_status" in result[0]


def test_full_pipeline_simulated():
    processor = BoxProcessor()
    counter = LineCounter(line_y=400)

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = [
        {"bbox": [0, 0, 100, 100], "confidence": 0.9},
    ]

    processed = processor.process_detections(frame, detections)
    obj = processed[0]

    obj["track_id"] = 1
    obj_above = {"track_id": 1, "bbox": [0, 300, 100, 350], "qr_data": obj.get("qr_data")}
    counter.update([obj_above])

    obj_cross = {"track_id": 1, "bbox": [0, 300, 100, 550], "qr_data": obj.get("qr_data")}
    n = counter.update([obj_cross])
    assert n == 1
    assert counter.total_count == 1
    assert obj_cross["counted"] is True


def test_processor_clips_boundary_bbox():
    processor = BoxProcessor()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = [
        {"bbox": [-10, -20, 200, 300], "confidence": 0.9},
    ]

    result = processor.process_detections(frame, detections)
    assert len(result) == 1


def test_multiple_detections_all_get_qr_fields():
    processor = BoxProcessor()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = [
        {"bbox": [0, 0, 50, 50], "confidence": 0.9},
        {"bbox": [100, 100, 200, 200], "confidence": 0.85},
        {"bbox": [300, 300, 400, 400], "confidence": 0.75},
    ]

    result = processor.process_detections(frame, detections)
    assert len(result) == 3
    for det in result:
        assert "qr_data" in det
        assert "has_qr" in det
        assert "qr_status" in det
