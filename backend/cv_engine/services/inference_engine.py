import logging
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from cv_engine.services.detector import BoxDetector, create_video_capture
from cv_engine.services.performance_optimizer import PerformanceOptimizer

LOGGER = logging.getLogger(__name__)


class InferenceEngine:
    def __init__(
        self,
        source: str = "0",
        model_path: str | None = None,
        conf_threshold: float | None = None,
        device: str = "cpu",
        input_size: int | None = None,
        frame_skip: int | None = None,
    ) -> None:
        self._source = source
        self._cap: Optional[cv2.VideoCapture] = None

        self.optimizer = PerformanceOptimizer(
            input_size=input_size,
            frame_skip=frame_skip,
        )

        self.detector = BoxDetector(
            model_path=model_path,
            conf_threshold=conf_threshold,
            device=device,
            input_size=input_size,
        )

    def open(self) -> None:
        if self._cap is not None:
            self.release()
        self._cap = create_video_capture(self._source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Failed to open video source: {self._source}")
        LOGGER.info("Video source opened: %s", self._source)

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read_frame(self) -> np.ndarray | None:
        if not self.is_open:
            return None
        ret, frame = self._cap.read()
        if not ret or frame is None:
            return None
        return frame

    def infer(self, frame: np.ndarray) -> tuple[list[dict], Optional[np.ndarray]]:
        if not self.optimizer.should_process():
            return None, None

        resized = self.optimizer.resize(frame)

        t0 = time.perf_counter()
        detections = self.detector.detect(resized)
        inference_time = time.perf_counter() - t0

        if detections and resized.shape[:2] != frame.shape[:2]:
            h_orig, w_orig = frame.shape[:2]
            h_inf, w_inf = resized.shape[:2]
            sx = w_orig / w_inf
            sy = h_orig / h_inf
            for det in detections:
                x1, y1, x2, y2 = det["bbox"]
                det["bbox"] = [
                    int(x1 * sx),
                    int(y1 * sy),
                    int(x2 * sx),
                    int(y2 * sy),
                ]

        self.optimizer.tick(inference_time)
        return detections, resized

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            LOGGER.info("Video source released")

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def get_source_properties(self) -> dict:
        if not self.is_open:
            return {"source": self._source, "width": 0, "height": 0, "fps": 0, "total_frames": 0}
        return {
            "source": self._source,
            "width": int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": round(self._cap.get(cv2.CAP_PROP_FPS), 2),
            "total_frames": int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        }
