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
        self._roi = config.get("roi")
        self._roi_mask = None
        self._roi_points = []

        self._source: Optional[SimulatedCameraSource] = None
        self._frame_source: Any = None
        self._box_processor: Optional[BoxProcessor] = None
        self._tracker: Optional[ObjectTracker] = None
        self._counter: Optional[LineCounter] = None
        self._duplicate_guard: Optional[DuplicateGuard] = None
        self._seen_tracks: set = set()
        self._detector: Any = None
        self._detection_conf = float(config.get("detection_conf", 0.55))
        self._count_conf = float(config.get("count_conf", 0.65))

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

                    events, vis_boxes = self._process_frame(frame, pre_dets)
                    try:
                        vis_frame = self._draw_overlays(frame, vis_boxes)
                        self._publish_frame(vis_frame)
                    except Exception:
                        LOGGER.exception("[%s] Frame publish failed", self.camera_id)
                    for event in events:
                        self._event_queue.put(event)

                    if frame_count % 30 == 0:
                        self._report_health("running", {
                            "frames": frame_count,
                            "counted": self._counter.total_count if self._counter else 0,
                            "vis_boxes": len(vis_boxes),
                            "events": len(events),
                            "seen_tracks": len(self._seen_tracks),
                        })
                        LOGGER.info("[%s] frame=%d vis_boxes=%d events=%d counted=%d seen=%d",
                                    self.camera_id, frame_count, len(vis_boxes), len(events),
                                    self._counter.total_count if self._counter else 0,
                                    len(self._seen_tracks))

                    if frame_count % 600 == 0 and self._seen_tracks:
                        old = len(self._seen_tracks)
                        self._seen_tracks.clear()
                        LOGGER.info("[%s] Cleared _seen_tracks (%d -> 0)", self.camera_id, old)

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
            go2rtc_rtsp_host = os.getenv("GO2RTC_RTSP_HOST", "localhost")
            channel = self.config.get("channel", 0)
            rtsp_url = f"rtsp://{go2rtc_rtsp_host}:8554/ch{channel}"
            from go2rtc.video_stream import VideoStream

            for attempt in range(1, 11):
                if self._frame_source is not None:
                    try:
                        self._frame_source.release()
                    except Exception:
                        pass
                    self._frame_source = None
                self._frame_source = VideoStream(
                    rtsp_url,
                    buffer_size=30,
                    enable_watchdog=True,
                    max_reconnect_attempts=0,
                    watchdog_timeout=10.0,
                )
                if self._frame_source.is_open():
                    break
                LOGGER.warning("[%s] RTSP connect attempt %d/10 failed for %s, retry in 3s...",
                               self.camera_id, attempt, rtsp_url)
                self._sleep(3.0)
            else:
                raise RuntimeError(f"Cannot open go2rtc RTSP stream {rtsp_url} after 10 attempts")
            model_path = self.config.get("model_path")
            if model_path:
                from cv_engine.services.detector import BoxDetector
                import subprocess
                device = self.config.get("device", "cpu")
                try:
                    subprocess.check_output(["nvidia-smi"], stderr=subprocess.STDOUT)
                    if device == "cpu":
                        device = "cuda:0"
                except Exception:
                    pass
                self._detector = BoxDetector(
                    model_path=model_path,
                    conf_threshold=self._detection_conf,
                    device=device,
                    input_size=self.config.get("input_size", 640),
                )
                LOGGER.info("[%s] YOLO loaded: %s (conf=%.2f, device=%s)",
                            self.camera_id, model_path, self._detection_conf, device)
            else:
                LOGGER.info("[%s] No model selected — stream-only mode (no detection)", self.camera_id)
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
        self._build_roi_mask()

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

    def _build_roi_mask(self) -> None:
        if not self._roi:
            return
        points = self._roi
        if isinstance(points, dict) and "points" in points:
            points = points["points"]
        if not isinstance(points, list) or len(points) < 3:
            LOGGER.warning("[%s] ROI has fewer than 3 points, ignoring", self.camera_id)
            return
        self._roi_points = []
        for p in points:
            if isinstance(p, dict) and "x" in p and "y" in p:
                self._roi_points.append((float(p["x"]), float(p["y"])))
            elif isinstance(p, (list, tuple)) and len(p) == 2:
                self._roi_points.append((float(p[0]), float(p[1])))
            else:
                LOGGER.warning("[%s] Skipping invalid ROI point: %s", self.camera_id, p)
        if len(self._roi_points) < 3:
            LOGGER.warning("[%s] ROI has fewer than 3 valid points after parsing, ignoring", self.camera_id)
            self._roi_points = []
            return
        self._roi_normalized = True
        self._roi_mask = None
        LOGGER.info("[%s] ROI mask configured with %d points (normalized=True)",
                     self.camera_id, len(self._roi_points))

    def _apply_roi(self, frame: np.ndarray) -> np.ndarray:
        if not self._roi_points:
            return frame
        h, w = frame.shape[:2]
        pixel_pts = np.array(
            [[int(p[0] * w), int(p[1] * h)] for p in self._roi_points], dtype=np.int32
        )
        if self._roi_mask is None or self._roi_mask.shape != (h, w):
            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(mask, [pixel_pts], 255)
            self._roi_mask = mask
        masked = cv2.bitwise_and(frame, frame, mask=self._roi_mask)
        return masked

    def _process_frame(self, frame: np.ndarray, pre_dets: Optional[list[dict]]) -> tuple[list[dict], list[dict]]:
        detect_frame = self._apply_roi(frame) if self._roi_points else frame

        if pre_dets is not None:
            detections = pre_dets
        elif self._detector is not None:
            detections = self._detector.detect(detect_frame)
        else:
            return [], []

        if not detections:
            return [], []

        if self._roi_points:
            h, w = frame.shape[:2]
            pixel_pts = np.array(
                [[int(p[0] * w), int(p[1] * h)] for p in self._roi_points], dtype=np.int32
            )
            filtered = []
            for det in detections:
                bbox = det.get("bbox")
                if bbox and len(bbox) == 4:
                    x1, y1, x2, y2 = bbox
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)
                    if cv2.pointPolygonTest(pixel_pts, (cx, cy), False) >= 0:
                        filtered.append(det)
            detections = filtered

        if not detections:
            return [], []

        detections = self._box_processor.process_detections(frame, detections)

        if self._tracker is not None:
            tracked = self._tracker.update(detections, frame)
        else:
            tracked = detections

        if not tracked:
            return [], []

        ts = datetime.now(timezone.utc).isoformat()
        events: list[dict] = []
        vis_boxes: list[dict] = []

        for obj in tracked:
            bbox = obj.get("bbox") or obj.get("bbox_xyxy")
            if not bbox or len(bbox) != 4:
                continue
            x1, y1, x2, y2 = bbox
            conf = obj.get("confidence", 0)

            tid = obj.get("track_id")
            is_new = False
            if tid is not None:
                if tid not in self._seen_tracks:
                    is_new = True
                    self._seen_tracks.add(tid)
            else:
                tid = f"{self.camera_id}-det-{len(self._seen_tracks)}"
                is_new = True
                self._seen_tracks.add(tid)

            label = f"#{tid}" if isinstance(tid, int) else str(tid)
            vis_boxes.append({
                "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
                "label": label,
                "confidence": conf,
            })

            if is_new and conf >= self._count_conf:
                if self._counter:
                    self._counter.total_count += 1

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
                    "confidence": conf,
                    "class": obj.get("class", "box"),
                }
                events.append(base)

        return events, vis_boxes

    def _draw_overlays(self, frame: np.ndarray, boxes: list[dict]) -> np.ndarray:
        vis = frame.copy()

        if self._roi_points:
            h, w = vis.shape[:2]
            pts = np.array(
                [[int(p[0] * w), int(p[1] * h)] for p in self._roi_points], dtype=np.int32
            )
            cv2.polylines(vis, [pts], isClosed=True, color=(0, 255, 255), thickness=2)

        for b in boxes:
            x1, y1, x2, y2 = b["x1"], b["y1"], b["x2"], b["y2"]
            label = b.get("label", "")
            conf = b.get("confidence", 0)

            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)

            text = f"{label} {conf:.0%}" if conf else label
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6
            thickness = 2
            (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
            cv2.rectangle(vis, (x1, y1 - th - 8), (x1 + tw + 4, y1), (0, 255, 0), -1)
            cv2.putText(vis, text, (x1 + 2, y1 - 4), font, font_scale, (0, 0, 0), thickness)

        if self._counter:
            count_text = f"Count: {self._counter.total_count}"
            cv2.putText(vis, count_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        return vis

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
