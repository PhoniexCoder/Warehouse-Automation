import logging
import time
from typing import Any, Optional

import numpy as np

LOGGER = logging.getLogger(__name__)

_HAS_BYTETRACK = False
_HAS_DEEPSORT = False

try:
    from boxmot import ByteTrack as _ByteTrack
    _HAS_BYTETRACK = True
except ImportError:
    LOGGER.warning("boxmot not installed — ByteTrack unavailable")

try:
    from deep_sort_realtime.deepsort_tracker import DeepSort as _DeepSort
    _HAS_DEEPSORT = True
except ImportError:
    LOGGER.warning("deep_sort_realtime not installed — DeepSORT unavailable")

_TRACK_DATA_FIELDS = frozenset({"bbox", "confidence", "class", "track_id", "counted"})


class TrackerError(Exception):
    pass


class ObjectTracker:
    def __init__(
        self,
        method: str = "bytetrack",
        track_buffer: int = 30,
        iou_threshold: float = 0.5,
    ) -> None:
        self._track_buffer = track_buffer
        self._iou_threshold = iou_threshold
        self._method = method
        self._n_updates = 0
        self._total_tracks_created = 0

        self._extra_history: dict[int, dict[str, Any]] = {}
        self._lost_frames: dict[int, int] = {}
        self._track_metadata: dict[int, dict[str, Any]] = {}

        if method == "bytetrack" and _HAS_BYTETRACK:
            self._tracker = _ByteTrack(track_buffer=track_buffer)
            self._method = "bytetrack"
        elif method == "deepsort" and _HAS_DEEPSORT:
            self._tracker = _DeepSort()
            self._method = "deepsort"
        elif _HAS_BYTETRACK:
            LOGGER.info("Falling back to ByteTrack")
            self._tracker = _ByteTrack(track_buffer=track_buffer)
            self._method = "bytetrack"
        elif _HAS_DEEPSORT:
            LOGGER.info("Falling back to DeepSORT")
            self._tracker = _DeepSort()
            self._method = "deepsort"
        else:
            raise TrackerError(
                "No tracking backend available. Install boxmot or deep_sort_realtime."
            )

        LOGGER.info(
            "ObjectTracker(method=%s, track_buffer=%d, iou_threshold=%.2f)",
            self._method, track_buffer, iou_threshold,
        )

    def update(
        self,
        detections: list[dict],
        frame: Optional[np.ndarray] = None,
    ) -> list[dict]:
        if not detections:
            self._n_updates += 1
            return []

        extra_by_idx = self._extract_extra_fields(detections)

        if self._method == "bytetrack":
            tracked = self._update_bytetrack(detections, frame)
        else:
            tracked = self._update_deepsort(detections, frame)

        if not tracked:
            self._n_updates += 1
            return []

        self._merge_track_data(tracked, detections, extra_by_idx)
        self._prune_stale_history(tracked)

        self._n_updates += 1
        return tracked

    def reset(self) -> None:
        LOGGER.info(
            "Resetting tracker — created %d tracks across %d updates",
            self._total_tracks_created, self._n_updates,
        )
        self._extra_history.clear()
        self._lost_frames.clear()
        self._track_metadata.clear()
        self._n_updates = 0
        self._total_tracks_created = 0

        if self._method == "bytetrack" and _HAS_BYTETRACK:
            self._tracker = _ByteTrack(track_buffer=self._track_buffer)
        elif _HAS_DEEPSORT:
            self._tracker = _DeepSort()
        LOGGER.info("Tracker reinitialised")

    # ------------------------------------------------------------------
    # Backend-specific update methods
    # ------------------------------------------------------------------

    def _update_bytetrack(
        self,
        detections: list[dict],
        frame: Optional[np.ndarray] = None,
    ) -> list[dict]:
        dets_np = self._detections_to_array(detections)
        if dets_np.shape[0] == 0:
            return []

        frame_or_dummy = self._resolve_frame_for_tracker(frame)

        tracks = self._tracker.update(dets_np, frame_or_dummy)

        tracked: list[dict] = []
        for track in tracks:
            x1, y1, x2, y2, track_id, conf, *_ = track.tolist()
            tracked.append({
                "track_id": int(track_id),
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "confidence": float(conf),
            })

        LOGGER.debug("ByteTrack: %d detections -> %d tracks", len(detections), len(tracked))
        return tracked

    def _update_deepsort(
        self,
        detections: list[dict],
        frame: Optional[np.ndarray] = None,
    ) -> list[dict]:
        if frame is None or frame.size == 0:
            LOGGER.warning("DeepSORT requires a valid frame — using dummy frame")
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        deepsort_dets: list[list] = []
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            
            # Clip bounding boxes to frame boundaries to prevent negative slicing crashes
            fh, fw = frame.shape[:2]
            x1_clipped = max(0, min(int(x1), fw - 1))
            y1_clipped = max(0, min(int(y1), fh - 1))
            x2_clipped = max(0, min(int(x2), fw))
            y2_clipped = max(0, min(int(y2), fh))
            
            w = x2_clipped - x1_clipped
            h = y2_clipped - y1_clipped
            
            # Skip invalid/empty boxes
            if w <= 0 or h <= 0:
                continue
                
            conf = det.get("confidence", 0.5)
            deepsort_dets.append(([x1_clipped, y1_clipped, w, h], conf, 0))

        tracks = self._tracker.update_tracks(deepsort_dets, frame=frame)

        tracked: list[dict] = []
        for track in tracks:
            if not track.is_confirmed():
                continue
            track_id = track.track_id
            ltrb = track.to_ltrb()
            tracked.append({
                "track_id": int(track_id),
                "bbox": [
                    int(ltrb[0]),
                    int(ltrb[1]),
                    int(ltrb[2]),
                    int(ltrb[3]),
                ],
                "confidence": float(
                    track.det_conf
                    if hasattr(track, "det_conf") and track.det_conf is not None
                    else 0.0
                ),
            })

        LOGGER.debug("DeepSORT: %d detections -> %d tracks", len(detections), len(tracked))
        return tracked

    # ------------------------------------------------------------------
    # Extra field management
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_extra_fields(detections: list[dict]) -> dict[int, dict]:
        extra_by_idx: dict[int, dict] = {}
        for i, det in enumerate(detections):
            extra = {
                k: v
                for k, v in det.items()
                if k not in _TRACK_DATA_FIELDS
            }
            if extra:
                extra_by_idx[i] = extra
        return extra_by_idx

    def _merge_track_data(
        self,
        tracked: list[dict],
        detections: list[dict],
        extra_by_idx: dict[int, dict],
    ) -> None:
        for t in tracked:
            tid = t["track_id"]

            if tid in self._extra_history:
                t.update(self._extra_history[tid])
                self._lost_frames.pop(tid, None)
                continue

            best_idx = self._best_match_index(t["bbox"], detections, extra_by_idx)
            if best_idx is not None:
                extra = extra_by_idx[best_idx]
                t.update(extra)
                self._extra_history[tid] = dict(extra)
                self._total_tracks_created += 1
                continue

    def _best_match_index(
        self,
        track_bbox: list[int],
        detections: list[dict],
        extra_by_idx: dict[int, dict],
    ) -> Optional[int]:
        best_idx: Optional[int] = None
        best_iou = self._iou_threshold

        for i, det in enumerate(detections):
            if i not in extra_by_idx:
                continue
            iou = self._iou(track_bbox, det["bbox"])
            if iou > best_iou:
                best_iou = iou
                best_idx = i

        return best_idx

    def _prune_stale_history(self, tracked: list[dict]) -> None:
        active_ids = {t["track_id"] for t in tracked}

        for tid in list(self._extra_history.keys()):
            if tid in active_ids:
                continue
            lost = self._lost_frames.get(tid, 0) + 1
            self._lost_frames[tid] = lost
            if lost > self._track_buffer * 2:
                del self._extra_history[tid]
                del self._lost_frames[tid]
                self._track_metadata.pop(tid, None)
                LOGGER.debug("Pruned stale track_id=%s after %d lost frames", tid, lost)

        for tid in active_ids:
            metadata = self._track_metadata.get(tid)
            if metadata is None:
                self._track_metadata[tid] = {"created": time.time(), "n_hits": 1}
            else:
                metadata["n_hits"] = metadata.get("n_hits", 0) + 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_frame_for_tracker(frame: Optional[np.ndarray]) -> np.ndarray:
        if frame is not None and frame.size > 0:
            return frame
        return np.zeros((10, 10, 3), dtype=np.uint8)

    @staticmethod
    def _iou(bbox_a: list[int], bbox_b: list[int]) -> float:
        x1, y1, x2, y2 = bbox_a
        x3, y3, x4, y4 = bbox_b
        xi1 = max(x1, x3)
        yi1 = max(y1, y3)
        xi2 = min(x2, x4)
        yi2 = min(y2, y4)
        inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
        if inter == 0:
            return 0.0
        area_a = (x2 - x1) * (y2 - y1)
        area_b = (x4 - x3) * (y4 - y3)
        return inter / float(area_a + area_b - inter)

    @staticmethod
    def _detections_to_array(detections: list[dict]) -> np.ndarray:
        if not detections:
            return np.empty((0, 5))
        rows = []
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            conf = d.get("confidence", 0.5)
            rows.append([x1, y1, x2, y2, conf])
        return np.array(rows, dtype=np.float64)
