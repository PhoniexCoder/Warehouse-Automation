import pytest

from cv_engine.services.detector import BoxDetector, BoxDetectorError


def test_detector_init_no_model():
    with pytest.raises(BoxDetectorError, match="Model file not found"):
        BoxDetector(model_path="nonexistent.pt")


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
