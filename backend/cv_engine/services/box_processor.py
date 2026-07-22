import logging

import numpy as np

LOGGER = logging.getLogger(__name__)


class BoxProcessor:
    def __init__(self) -> None:
        pass

    def process_detections(
        self,
        frame: np.ndarray,
        detections: list[dict],
    ) -> list[dict]:
        if frame is None or frame.size == 0 or not detections:
            return detections

        h, w = frame.shape[:2]

        for det in detections:
            self._process_single(frame, det, h, w)

        return detections

    def _process_single(
        self,
        frame: np.ndarray,
        det: dict,
        frame_h: int,
        frame_w: int,
    ) -> None:
        x1, y1, x2, y2 = det["bbox"]

        x1 = max(0, min(x1, frame_w - 1))
        y1 = max(0, min(y1, frame_h - 1))
        x2 = max(x1 + 2, min(x2, frame_w))
        y2 = max(y1 + 2, min(y2, frame_h))

        det["qr_data"] = None
        det["has_qr"] = False
        det["qr_status"] = None
