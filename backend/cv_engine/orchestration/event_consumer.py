import logging
import queue
import threading
from typing import Any

from cv_engine.database import save_detection, save_duplicate_event, save_invalid_qr

LOGGER = logging.getLogger(__name__)

_EVENT_TYPE_DETECTION = "detection"
_EVENT_TYPE_INVALID_QR = "invalid_qr"
_EVENT_TYPE_DUPLICATE = "duplicate"

_QUEUE_GET_TIMEOUT = 1.0


class EventConsumer(threading.Thread):
    def __init__(
        self,
        event_queue: "multiprocessing.Queue",
        stop_event: "multiprocessing.synchronize.Event",
    ) -> None:
        super().__init__(daemon=True, name="event-consumer")
        self._queue = event_queue
        self._stop_event = stop_event
        self._processed_count = 0
        self._last_event_type: str | None = None

    @property
    def stats(self) -> dict:
        return {
            "processed": self._processed_count,
            "last_event_type": self._last_event_type,
        }

    def run(self) -> None:
        LOGGER.info("EventConsumer started")
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=_QUEUE_GET_TIMEOUT)
                self._handle_event(event)
            except queue.Empty:
                continue
            except Exception:
                LOGGER.exception("EventConsumer crashed")
                self._sleep(1.0)

        LOGGER.info("EventConsumer stopped (%d events processed)", self._processed_count)

    def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        camera_id = event.get("camera_id", "unknown")
        tracking_id = event.get("tracking_id")
        box = event.get("box", {})

        if event_type == _EVENT_TYPE_DETECTION:
            self._save_detection(event, camera_id, tracking_id, box)
        elif event_type == _EVENT_TYPE_INVALID_QR:
            self._save_invalid_qr(event, camera_id, tracking_id, box)
        elif event_type == _EVENT_TYPE_DUPLICATE:
            self._save_duplicate(event, camera_id, tracking_id, box)
        else:
            LOGGER.warning("Unknown event type: %s", event_type)
            return

        self._processed_count += 1
        self._last_event_type = event_type

    def _save_detection(self, event: dict, camera_id: str, tracking_id: int, box: dict) -> None:
        try:
            save_detection(
                tracking_id=tracking_id,
                qr_data=event.get("qr_data"),
                camera_id=camera_id,
                counted_status=True,
                box_x=box.get("x", 0),
                box_y=box.get("y", 0),
                box_width=box.get("width", 0),
                box_height=box.get("height", 0),
            )
        except Exception:
            LOGGER.exception("Failed to save detection event")

    def _save_invalid_qr(self, event: dict, camera_id: str, tracking_id: int, box: dict) -> None:
        try:
            save_invalid_qr(
                tracking_id=tracking_id,
                error_type=event.get("error_type", "NO_QR"),
                camera_id=camera_id,
                box_x=box.get("x", 0),
                box_y=box.get("y", 0),
                box_width=box.get("width", 0),
                box_height=box.get("height", 0),
            )
        except Exception:
            LOGGER.exception("Failed to save invalid QR event")

    def _save_duplicate(self, event: dict, camera_id: str, tracking_id: int, box: dict) -> None:
        try:
            save_duplicate_event(
                tracking_id=tracking_id,
                qr_data=event.get("qr_data"),
                camera_id=camera_id,
                box_x=box.get("x", 0),
                box_y=box.get("y", 0),
                box_width=box.get("width", 0),
                box_height=box.get("height", 0),
            )
        except Exception:
            LOGGER.exception("Failed to save duplicate event")

    @staticmethod
    def _sleep(seconds: float) -> None:
        import time
        time.sleep(seconds)
