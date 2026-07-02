import numpy as np

from cv_engine.services.qr_reader import QRReader


def test_detect_qr_empty_frame():
    reader = QRReader()
    result = reader.detect_qr(np.zeros((100, 100, 3), dtype=np.uint8))
    assert isinstance(result, dict)
    assert "success" in result
    assert "qr_data" in result


def test_detect_qr_none_frame():
    reader = QRReader()
    result = reader.detect_qr(np.array([]))
    assert result == {"success": False, "qr_data": None}


def test_detect_qr_returns_correct_format():
    reader = QRReader()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = reader.detect_qr(frame)
    assert "success" in result
    assert "qr_data" in result
    assert isinstance(result["success"], bool)


def test_preprocess_for_blurry():
    frame = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    variations = QRReader._preprocess_for_blurry(frame)
    assert len(variations) >= 1
    for v in variations:
        assert v.shape == (100, 100, 3)


def test_rotate_image():
    frame = np.random.randint(0, 255, (200, 300, 3), dtype=np.uint8)
    rotations = QRReader._rotate_image(frame)
    assert len(rotations) == 3
    for r in rotations:
        assert r.shape == (200, 300, 3)
