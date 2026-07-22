import logging
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from cv_engine.config.inference_config import InferenceConfig

LOGGER = logging.getLogger(__name__)


class BoxDetectorError(Exception):
    pass


class BoxDetector:
    _ALLOWED_MODEL_DIRS = {Path("/app/models").resolve(), Path("models").resolve()}

    def __init__(
        self,
        model_path: str | None = None,
        conf_threshold: float | None = None,
        iou_threshold: float = 0.7,
        device: str = "cpu",
        input_size: int | None = None,
    ) -> None:
        self._conf = conf_threshold if conf_threshold is not None else InferenceConfig.CONFIDENCE_THRESHOLD
        self._iou = iou_threshold
        self._device = device
        self._input_size = input_size if input_size is not None else InferenceConfig.INPUT_SIZE

        resolved = Path(model_path if model_path is not None else InferenceConfig.MODEL_PATH)
        if not resolved.is_absolute():
            resolved = (Path.cwd() / resolved).resolve()
        if not resolved.exists():
            alt = Path("/app/models") / Path(model_path).name
            if alt.exists():
                resolved = alt
            else:
                raise BoxDetectorError(f"Model file not found: {resolved}")

        is_allowed = any(
            str(resolved).startswith(str(d)) for d in self._ALLOWED_MODEL_DIRS
        )
        if not is_allowed:
            raise BoxDetectorError(
                f"Model path not in allowed directories: {resolved}. "
                f"Allowed: {self._ALLOWED_MODEL_DIRS}"
            )
        self._model_path = str(resolved)
        LOGGER.info("Loading YOLO model from %s", self._model_path)
        self._model = YOLO(self._model_path)
        self._class_name = self._model.names.get(0, "box")
        LOGGER.info("Model loaded. Task=%s, Classes=%s", self._model.task, self._model.names)

    def detect(self, frame: np.ndarray) -> list[dict]:
        if frame is None or frame.size == 0:
            return []

        results = self._model(
            frame,
            conf=self._conf,
            iou=self._iou,
            device=self._device,
            verbose=False,
        )

        detections: list[dict] = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                confidence = float(box.conf[0])
                cls_id = int(box.cls[0]) if box.cls is not None else 0
                class_name = self._model.names.get(cls_id, self._class_name)
                detections.append(
                    {
                        "bbox": [x1, y1, x2, y2],
                        "confidence": round(confidence, 4),
                        "class": class_name,
                    }
                )

        return detections


def create_video_capture(source: str) -> cv2.VideoCapture:
    if source.isdigit():
        return cv2.VideoCapture(int(source))
    rtsp_prefixes = ("rtsp://", "rtmp://", "http://", "https://")
    if source.lower().startswith(rtsp_prefixes):
        import os
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000|rw_timeout;5000000|timeout;5000000"
        return cv2.VideoCapture(source)
    path = Path(source)
    return cv2.VideoCapture(str(path))
