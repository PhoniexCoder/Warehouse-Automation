import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import cv2
import numpy as np

from cv_engine.orchestration.frame_store import FrameStore
from cv_engine.services.box_processor import BoxProcessor
from cv_engine.services.duplicate_guard import DuplicateGuard
from cv_engine.services.line_counter import LineCounter
from cv_engine.services.tracker import ObjectTracker
from cv_engine.simulation.camera_source import SimulatedCameraSource

LOGGER = logging.getLogger(__name__)

_RECONNECT_BASE_DELAY = 1.0
_RECONNECT_MAX_DELAY = 30.0
_RECONNECT_MAX_ATTEMPTS = 60
_TARGET_FPS = 5.0

_EVENT_TYPE_DETECTION = "detection"


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
        self._frame_store = FrameStore()

        self._source: Optional[SimulatedCameraSource] = None
        self._frame_source: Any = None
        self._box_processor: Optional[BoxProcessor] = None
        self._tracker: Optional[ObjectTracker] = None
        self._counter: Optional[LineCounter] = None
        self._duplicate_guard: Optional[DuplicateGuard] = None
        self._seen_tracks = set()
        self._detector: Any = None

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
                    try:
                        self._publish_frame(frame)
                    except Exception:
                        LOGGER.exception("[%s] Frame publish failed", self.camera_id)
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
        elif self._source_type == "dvrip":
            go2rtc_url = os.getenv("GO2RTC_URL", "http://go2rtc:1984")
            channel = self.config.get("channel", 0)
            rtsp_url = f"rtsp://go2rtc:8554/ch{channel}"
            from go2rtc.video_stream import VideoStream
            self._frame_source = VideoStream(
                rtsp_url,
                buffer_size=30,
                enable_watchdog=True,
                max_reconnect_attempts=0,
                watchdog_timeout=10.0,
            )
            if not self._frame_source.is_open():
                raise RuntimeError(f"Cannot open go2rtc RTSP stream {rtsp_url}")
            from cv_engine.services.detector import BoxDetector
            self._detector = BoxDetector(
                model_path=self.config.get("model_path"),
                conf_threshold=self.config.get("conf", 0.5),
                device=self.config.get("device", "cpu"),
                input_size=self.config.get("input_size", 640),
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
        elif self._source_type == "dvrip":
            ret, frame = self._frame_source.read()
            if not ret or frame is None:
                return False, None, None
            return True, frame, None
        else:
            frame = self._frame_source.read_frame()
            if frame is None:
                return False, None, None
            return True, frame, None

    def _process_frame(self, frame: np.ndarray, pre_dets: Optional[list[dict]]) -> list[dict]:
        if pre_dets is not None:
            detections = pre_dets
        elif self._detector is not None:
            detections = self._detector.detect(frame)
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

        ts = datetime.now(timezone.utc).isoformat()
        events: list[dict] = []

        for obj in tracked:
            tid = obj.get("track_id")
            if tid is None:
                continue

            if tid not in self._seen_tracks:
                self._seen_tracks.add(tid)
                if self._counter:
                    self._counter.total_count += 1

                x1, y1, x2, y2 = obj["bbox"]
                base = {
                    "camera_id": self.camera_id,
                    "tracking_id": tid,
                    "timestamp": ts,
                    "type": _EVENT_TYPE_DETECTION,
                    "qr_data": f"CRAX-BOX-{tid}",
                    "box": {
                        "x": x1,
                        "y": y1,
                        "width": x2 - x1,
                        "height": y2 - y1,
                    },
                }
                events.append(base)

        return events

    def _publish_frame(self, frame: np.ndarray) -> None:
        self._frame_store.publish(self.camera_id, frame)

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
            elif hasattr(self._frame_source, "close"):
                self._frame_source.close()
        except Exception:
            pass
        self._report_health("stopped")
