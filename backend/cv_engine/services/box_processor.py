import logging

import numpy as np

from cv_engine.services.qr_reader import QRReader

LOGGER = logging.getLogger(__name__)


class BoxProcessor:
    def __init__(self, qr_reader: QRReader | None = None) -> None:
        self._qr = qr_reader or QRReader()

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

        crop = frame[y1:y2, x1:x2]

        qr_result = self._qr.detect_qr(crop)

        det["qr_data"] = qr_result.get("qr_data")
        det["has_qr"] = qr_result["success"]
        det["qr_status"] = self._resolve_status(qr_result)

    @staticmethod
    def _resolve_status(qr_result: dict) -> str | None:
        if qr_result["success"]:
            return None
        return "INVALID_QR"

    def process_box(self, frame: np.ndarray, box_dict: dict) -> dict:
        self._process_single(frame, box_dict, frame.shape[0], frame.shape[1])
        return box_dict
