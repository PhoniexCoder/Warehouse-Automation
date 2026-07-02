import logging
import multiprocessing
import threading
import time
from typing import Any, Optional

from cv_engine.orchestration.camera_worker import CameraWorker
from cv_engine.orchestration.event_consumer import EventConsumer

LOGGER = logging.getLogger(__name__)

_MONITOR_INTERVAL = 2.0
_HEALTH_STALE_SECONDS = 10.0
_EVENT_QUEUE_MAXSIZE = 10000


class CameraManager:
    def __init__(self) -> None:
        self._workers: dict[str, multiprocessing.Process] = {}
        self._configs: dict[str, dict] = {}
        self._event_queue: Optional[multiprocessing.Queue] = None
        self._health: Any = None
        self._stop_event = multiprocessing.Event()
        self._manager: Optional[multiprocessing.managers.SyncManager] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._consumer: Optional[EventConsumer] = None
        self._running = False

    @property
    def event_queue(self) -> Optional[multiprocessing.Queue]:
        return self._event_queue

    def add_camera(self, camera_id: str, config: dict[str, Any]) -> None:
        if camera_id in self._configs:
            LOGGER.warning("Camera %s already configured, overwriting", camera_id)
        self._configs[camera_id] = config
        LOGGER.info("Camera added: %s (scene=%s, line_y=%d)",
                     camera_id, config.get("sim_scene", "?"), config.get("line_y", 400))

    def remove_camera(self, camera_id: str) -> None:
        self._configs.pop(camera_id, None)
        worker = self._workers.pop(camera_id, None)
        if worker is not None and worker.is_alive():
            worker.terminate()
            worker.join(timeout=2)
            LOGGER.info("Camera %s removed and terminated", camera_id)

    def start_all(self) -> None:
        if not self._configs:
            LOGGER.warning("No cameras configured — nothing to start")
            return

        LOGGER.info("Starting CameraManager with %d cameras", len(self._configs))

        self._manager = multiprocessing.Manager()
        self._health = self._manager.dict()
        self._event_queue = multiprocessing.Queue(maxsize=_EVENT_QUEUE_MAXSIZE)

        self._consumer = EventConsumer(
            event_queue=self._event_queue,
            stop_event=self._stop_event,
        )
        self._consumer.start()

        for camera_id, config in self._configs.items():
            self._start_worker(camera_id, config)

        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="camera-monitor",
        )
        self._monitor_thread.start()

        LOGGER.info("CameraManager started")

    def _start_worker(self, camera_id: str, config: dict[str, Any]) -> None:
        worker = multiprocessing.Process(
            target=self._worker_main,
            args=(camera_id, config, self._event_queue, self._health, self._stop_event),
            name=f"cam-{camera_id}",
            daemon=True,
        )
        worker.start()
        self._workers[camera_id] = worker
        LOGGER.info("Worker started: %s (pid=%d)", camera_id, worker.pid)

    @staticmethod
    def _worker_main(
        camera_id: str,
        config: dict[str, Any],
        event_queue: Any,
        health: Any,
        stop_event: Any,
    ) -> None:
        worker = CameraWorker(camera_id, config, event_queue, health, stop_event)
        worker.run()

    def _monitor_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                now = time.time()

                for camera_id in list(self._configs.keys()):
                    worker = self._workers.get(camera_id)

                    if worker is None or not worker.is_alive():
                        LOGGER.warning("[%s] Worker dead, restarting", camera_id)
                        self._workers.pop(camera_id, None)
                        cfg = self._configs.get(camera_id)
                        if cfg:
                            self._start_worker(camera_id, cfg)
                        continue

                    self._check_health_staleness(camera_id, now)

            except Exception:
                LOGGER.exception("Monitor loop error")

            self._sleep(_MONITOR_INTERVAL)

    def _check_health_staleness(self, camera_id: str, now: float) -> None:
        try:
            entry = self._health.get(camera_id)
            if entry and entry.get("status") == "running":
                last_ts = entry.get("timestamp", 0)
                if now - last_ts > _HEALTH_STALE_SECONDS:
                    LOGGER.warning("[%s] Health stale (%.1fs), restarting",
                                   camera_id, now - last_ts)
                    self._restart_worker(camera_id)
        except Exception:
            pass

    def _restart_worker(self, camera_id: str) -> None:
        worker = self._workers.pop(camera_id, None)
        if worker is not None and worker.is_alive():
            worker.terminate()
            worker.join(timeout=2)

        cfg = self._configs.get(camera_id)
        if cfg:
            self._start_worker(camera_id, cfg)

    def stop_all(self) -> None:
        LOGGER.info("Stopping CameraManager")
        self._running = False
        self._stop_event.set()

        for camera_id, worker in list(self._workers.items()):
            LOGGER.info("Stopping worker: %s (pid=%d)", camera_id, worker.pid or 0)
            if worker.is_alive():
                worker.join(timeout=3)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=1)

        self._workers.clear()

        if self._consumer is not None and self._consumer.is_alive():
            self._consumer.join(timeout=3)

        if self._manager is not None:
            self._manager.shutdown()

        LOGGER.info("CameraManager stopped")

    def get_status(self) -> dict[str, Any]:
        statuses: dict[str, Any] = {}
        for camera_id in sorted(self._configs.keys()):
            worker = self._workers.get(camera_id)
            health = {}
            try:
                health = dict(self._health.get(camera_id, {})) if self._health else {}
            except Exception:
                pass

            alive = worker is not None and worker.is_alive()
            statuses[camera_id] = {
                "pid": worker.pid if worker and worker.is_alive() else None,
                "alive": alive,
                "health": health,
                "config": {
                    "scene": self._configs[camera_id].get("sim_scene", "?"),
                    "line_y": self._configs[camera_id].get("line_y", 400),
                },
            }

        consumer_stats = self._consumer.stats if self._consumer else {}
        return {
            "cameras": statuses,
            "consumer": {
                "running": self._consumer is not None and self._consumer.is_alive(),
                "stats": consumer_stats,
            },
            "running": self._running,
            "queue_size": self._event_queue.qsize() if self._event_queue else 0,
        }

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(seconds)
