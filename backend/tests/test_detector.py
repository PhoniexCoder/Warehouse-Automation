import pytest

from cv_engine.services.detector import BoxDetector, BoxDetectorError


def test_detector_init_no_model():
    with pytest.raises(BoxDetectorError, match="Model file not found"):
        BoxDetector(model_path="nonexistent.pt")


def test_detector_validate_frame():
    import numpy as np

    valid = np.zeros((480, 640, 3), dtype=np.uint8)
    assert BoxDetector.validate_frame(valid) is True

    assert BoxDetector.validate_frame(np.array([])) is False
    assert BoxDetector.validate_frame(None) is False


def test_detect_empty_frame():
    import numpy as np
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        fake_model = Path(tmp) / "fake.pt"
        fake_model.write_text("not a model")

        with pytest.raises(Exception):
            detector = BoxDetector(model_path=str(fake_model))
            detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))
