import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import cv2
import numpy as np

from cv_engine.services.box_processor import BoxProcessor
from cv_engine.services.duplicate_guard import DuplicateGuard
from cv_engine.services.line_counter import LineCounter
from cv_engine.services.tracker import ObjectTracker
from cv_engine.simulation.camera_source import SimulatedCameraSource

LOGGER = logging.getLogger(__name__)

_RECONNECT_BASE_DELAY = 1.0
_RECONNECT_MAX_DELAY = 30.0
_RECONNECT_MAX_ATTEMPTS = 60
_TARGET_FPS = 30.0
_FRAME_INTERVAL = 1.0 / _TARGET_FPS

_EVENT_TYPE_DETECTION = "detection"
_EVENT_TYPE_INVALID_QR = "invalid_qr"
_EVENT_TYPE_DUPLICATE = "duplicate"


class CameraWorker:
    def __init__(
        self,
        camera_id: str,
        config: dict[str, Any],
        event_queue: Any,
        health_dict: Any,
        stop_event: Any,
    ) -> None:
        self.camera_id = camera_id
        self.config = config
        self._event_queue = event_queue
        self._health = health_dict
        self._stop = stop_event

        self._source_type = config.get("source_type", "simulated")
        self._scene = config.get("sim_scene", "entry")
        self._line_y = config.get("line_y", 400)
        self._tracker_method = config.get("tracker", "bytetrack")
        self._target_fps = config.get("target_fps", _TARGET_FPS)
        self._frame_interval = 1.0 / max(self._target_fps, 1.0)
        self._consecutive_errors = 0

        self._source: Optional[SimulatedCameraSource] = None
        self._frame_source: Any = None
        self._box_processor: Optional[BoxProcessor] = None
        self._tracker: Optional[ObjectTracker] = None
        self._counter: Optional[LineCounter] = None
        self._duplicate_guard: Optional[DuplicateGuard] = None

    def run(self) -> None:
        LOGGER.info("[%s] Worker starting (source=%s, scene=%s, line_y=%d)",
                     self.camera_id, self._source_type, self._scene, self._line_y)

        try:
            self._init_components()
        except Exception:
            LOGGER.exception("[%s] Component init failed — worker cannot run", self.camera_id)
            self._report_health("dead", {"reason": "init_failed"})
            return

        self._report_health("starting")

        frame_start = 0.0
        reconnect_delay = _RECONNECT_BASE_DELAY
        frame_count = 0

        try:
            while not self._stop.is_set():
                try:
                    frame_start = time.time()

                    ret, frame, pre_dets = self._read_frame()

                    if not ret or frame is None:
                        self._consecutive_errors += 1
                        if self._consecutive_errors > _RECONNECT_MAX_ATTEMPTS:
                            LOGGER.error("[%s] Max reconnection attempts reached, giving up",
                                         self.camera_id)
                            self._report_health("dead", {"reason": "max_reconnects"})
                            break

                        reconnect_delay = min(reconnect_delay * 2, _RECONNECT_MAX_DELAY)
                        LOGGER.warning("[%s] No frame (%d/%d), retry in %.1fs",
                                       self.camera_id, self._consecutive_errors,
                                       _RECONNECT_MAX_ATTEMPTS, reconnect_delay)
                        self._report_health("reconnecting", {
                            "delay": reconnect_delay,
                            "attempt": self._consecutive_errors,
                        })
                        self._sleep(reconnect_delay)
                        continue

                    reconnect_delay = _RECONNECT_BASE_DELAY
                    self._consecutive_errors = 0
                    frame_count += 1

                    events = self._process_frame(frame, pre_dets)
                    for event in events:
                        self._event_queue.put(event)

                    if frame_count % 30 == 0:
                        self._report_health("running", {
                            "frames": frame_count,
                            "counted": self._counter.total_count if self._counter else 0,
                        })

                    elapsed = time.time() - frame_start
                    sleep_time = max(0.0, self._frame_interval - elapsed)
                    if sleep_time > 0:
                        self._sleep(sleep_time)

                except Exception:
                    LOGGER.exception("[%s] Frame processing error", self.camera_id)
                    self._consecutive_errors += 1
                    self._report_health("error", {"error": "frame processing"})
                    self._sleep(1.0)

        finally:
            self._cleanup()

    def _init_components(self) -> None:
        if self._source_type == "simulated":
            self._frame_source = SimulatedCameraSource(
                camera_id=self.camera_id,
                scene=self._scene,
            )
        else:
            from cv_engine.services.inference_engine import InferenceEngine
            self._frame_source = InferenceEngine(
                source=self.config.get("source", "0"),
                model_path=self.config.get("model_path"),
                conf_threshold=self.config.get("conf", 0.5),
                device=self.config.get("device", "cpu"),
                input_size=self.config.get("input_size", 640),
                frame_skip=self.config.get("frame_skip", 1),
            )
            self._frame_source.open()

        self._box_processor = BoxProcessor()
        try:
            self._tracker = ObjectTracker(method=self._tracker_method)
        except Exception:
            LOGGER.exception("[%s] Failed to initialise tracker — running without tracking", self.camera_id)
            self._tracker = None
        self._counter = LineCounter(line_y=self._line_y)
        self._duplicate_guard = DuplicateGuard()

    def _read_frame(self):
        if self._source_type == "simulated":
            return self._frame_source.read()
        frame = self._frame_source.read_frame()
        if frame is None:
            return False, None, None
        return True, frame, None

    def _process_frame(self, frame: np.ndarray, pre_dets: Optional[list[dict]]) -> list[dict]:
        if pre_dets is not None:
            detections = pre_dets
        else:
            detections, _ = self._frame_source.infer(frame)

        if not detections:
            return []

        detections = self._box_processor.process_detections(frame, detections)
        if self._tracker is None:
            return []
        tracked = self._tracker.update(detections, frame)
        if not tracked:
            return []

        self._counter.update(tracked)

        ts = datetime.now(timezone.utc).isoformat()
        events: list[dict] = []

        for obj in tracked:
            if not obj.get("counted"):
                continue

            tid = obj["track_id"]
            if tid is None:
                continue

            qr_data = obj.get("qr_data")
            has_qr = obj.get("has_qr", False)
            x1, y1, x2, y2 = obj["bbox"]

            base = {
                "camera_id": self.camera_id,
                "tracking_id": tid,
                "timestamp": ts,
                "box": {
                    "x": x1,
                    "y": y1,
                    "width": x2 - x1,
                    "height": y2 - y1,
                },
            }

            if not self._duplicate_guard.is_new(tid, qr_data):
                base["type"] = _EVENT_TYPE_DUPLICATE
                base["qr_data"] = qr_data
                events.append(base)
                continue

            self._duplicate_guard.mark_counted(tid, qr_data)

            if has_qr and qr_data:
                base["type"] = _EVENT_TYPE_DETECTION
                base["qr_data"] = qr_data
            else:
                base["type"] = _EVENT_TYPE_INVALID_QR
                base["error_type"] = obj.get("qr_status", "NO_QR")

            events.append(base)

        return events

    def _report_health(self, status: str, extras: Optional[dict] = None) -> None:
        entry = {
            "status": status,
            "timestamp": time.time(),
        }
        if extras:
            entry.update(extras)
        try:
            self._health[self.camera_id] = entry
        except Exception:
            pass

    def _sleep(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline and not self._stop.is_set():
            time.sleep(min(0.1, deadline - time.time()))

    def _cleanup(self) -> None:
        LOGGER.info("[%s] Worker cleaning up", self.camera_id)
        try:
            if hasattr(self._frame_source, "release"):
                self._frame_source.release()
        except Exception:
            pass
        self._report_health("stopped")
