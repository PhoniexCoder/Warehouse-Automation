from cv_engine.services.association import AssociationEngine


def test_associate_qr_inside_box():
    engine = AssociationEngine()
    qr = [{"data": "BOX-001", "bbox": [40, 40, 60, 60]}]
    detections = [{"bbox": [0, 0, 100, 100], "confidence": 0.9, "track_id": 1}]

    result = engine.associate(qr, detections)
    assert result[0]["qr_data"] == "BOX-001"


def test_associate_qr_outside_box():
    engine = AssociationEngine()
    qr = [{"data": "BOX-001", "bbox": [200, 200, 220, 220]}]
    detections = [{"bbox": [0, 0, 100, 100], "confidence": 0.9, "track_id": 1}]

    result = engine.associate(qr, detections)
    assert "qr_data" not in result[0]


def test_associate_no_qr():
    engine = AssociationEngine()
    detections = [{"bbox": [0, 0, 100, 100], "confidence": 0.9, "track_id": 1}]

    result = engine.associate([], detections)
    assert "qr_data" not in result[0]


def test_associate_no_detections():
    engine = AssociationEngine()
    qr = [{"data": "BOX-001", "bbox": [40, 40, 60, 60]}]
    result = engine.associate(qr, [])
    assert result == []


def test_associate_multiple_boxes_correct_match():
    engine = AssociationEngine()
    qr = [{"data": "BOX-002", "bbox": [240, 240, 260, 260]}]
    detections = [
        {"bbox": [0, 0, 100, 100], "confidence": 0.9, "track_id": 1},
        {"bbox": [200, 200, 300, 300], "confidence": 0.85, "track_id": 2},
    ]

    result = engine.associate(qr, detections)
    assert "qr_data" not in result[0]
    assert result[1]["qr_data"] == "BOX-002"


def test_associate_prefers_nearest_box():
    engine = AssociationEngine()
    qr = [{"data": "BOX-003", "bbox": [145, 145, 155, 155]}]
    detections = [
        {"bbox": [0, 0, 100, 100], "confidence": 0.9, "track_id": 1},
        {"bbox": [100, 100, 200, 200], "confidence": 0.85, "track_id": 2},
    ]

    result = engine.associate(qr, detections)
    assert result[1]["qr_data"] == "BOX-003"


def test_associate_skips_counted():
    engine = AssociationEngine()
    qr = [{"data": "BOX-004", "bbox": [40, 40, 60, 60]}]
    detections = [
        {"bbox": [0, 0, 100, 100], "confidence": 0.9, "track_id": 1, "counted": True},
    ]

    result = engine.associate(qr, detections)
    assert "qr_data" not in result[0]
