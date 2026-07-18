"""
VideoStream — robust RTSP reader with auto-reconnect, watchdog, and frame buffering.

Go2RTCManager — start/stop go2rtc as a subprocess (for local development).

Usage:
    from go2rtc.video_stream import VideoStream

    stream = VideoStream("rtsp://localhost:554/warehouse_main")
    while stream.is_open():
        ret, frame = stream.read()
        if ret:
            process(frame)
    stream.release()
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class StreamStats:
    frames_read: int = 0
    frames_dropped: int = 0
    reconnects: int = 0
    last_frame_time: float = 0.0
    start_time: float = field(default_factory=time.monotonic)
    latencies: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        uptime = time.monotonic() - self.start_time
        avg_latency = (sum(self.latencies[-100:]) / len(self.latencies[-100:])) if self.latencies else 0.0
        return {
            "frames_read": self.frames_read,
            "frames_dropped": self.frames_dropped,
            "reconnects": self.reconnects,
            "uptime_s": round(uptime, 1),
            "avg_latency_ms": round(avg_latency * 1000, 2),
            "fps": round(self.frames_read / max(uptime, 0.01), 1),
        }


# ---------------------------------------------------------------------------
# VideoStream
# ---------------------------------------------------------------------------

class VideoStream:
    """
    Threaded RTSP/RTMP/HTTP stream reader with auto-reconnect and frame buffering.

    Threading model:
      - Reader thread: reads cv2.VideoCapture frames → queue
      - Watchdog thread: detects stale streams and triggers reconnect
      - Main thread: consumer calls read() to get latest frame

    Args:
        url: Stream URL (rtsp://, rtmp://, http://, or device index)
        buffer_size: Max frames in the buffer queue (default 30)
        hardware_decode: Try D3D11 hardware acceleration (Windows only)
        max_reconnect_attempts: How many reconnect tries before giving up (0 = infinite)
        reconnect_delay: Seconds between reconnect attempts
        enable_watchdog: Enable the watchdog thread
        watchdog_timeout: Seconds of no frames before watchdog triggers reconnect
    """

    def __init__(
        self,
        url: str,
        buffer_size: int = 30,
        hardware_decode: bool = False,
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 2.0,
        enable_watchdog: bool = True,
        watchdog_timeout: float = 10.0,
    ) -> None:
        self._url = url
        self._buffer_size = buffer_size
        self._hardware_decode = hardware_decode
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_delay = reconnect_delay
        self._enable_watchdog = enable_watchdog
        self._watchdog_timeout = watchdog_timeout

        self._frame_queue: queue.Queue[Optional[np.ndarray]] = queue.Queue(maxsize=buffer_size)
        self._cap: Optional[cv2.VideoCapture] = None
        self._stats = StreamStats()
        self._stop = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._connected = False
        self._reconnect_lock = threading.Lock()

        self._open_stream()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self, timeout: float = 1.0) -> tuple[bool, Optional[np.ndarray]]:
        """Read the latest frame. Returns (success, frame)."""
        try:
            frame = self._frame_queue.get(timeout=timeout)
            if frame is None:
                return False, None
            t0 = time.monotonic()
            self._stats.frames_read += 1
            self._stats.last_frame_time = time.monotonic()
            self._stats.latencies.append(time.monotonic() - t0)
            return True, frame
        except queue.Empty:
            return False, None

    def is_open(self) -> bool:
        return self._connected and not self._stop.is_set()

    @property
    def stats(self) -> StreamStats:
        return self._stats

    @property
    def width(self) -> int:
        if self._cap and self._cap.isOpened():
            return int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        return 0

    @property
    def height(self) -> int:
        if self._cap and self._cap.isOpened():
            return int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return 0

    @property
    def fps(self) -> float:
        if self._cap and self._cap.isOpened():
            return self._cap.get(cv2.CAP_PROP_FPS)
        return 0.0

    def release(self) -> None:
        """Stop all threads and release resources."""
        self._stop.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=5.0)
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=5.0)
        self._close_cap()
        self._connected = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open_stream(self) -> None:
        """Open cv2.VideoCapture and start reader + watchdog threads."""
        self._close_cap()

        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if self._hardware_decode and sys.platform == "win32":
            self._cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_D3D11)

        if not self._cap.isOpened():
            LOGGER.error("Cannot open stream: %s", self._url)
            self._connected = False
            return

        self._connected = True
        self._stop.clear()

        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="vs-reader"
        )
        self._reader_thread.start()

        if self._enable_watchdog:
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True, name="vs-watchdog"
            )
            self._watchdog_thread.start()

        LOGGER.info("Stream opened: %s", self._url)

    def _close_cap(self) -> None:
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _reader_loop(self) -> None:
        """Continuously read frames from cv2.VideoCapture into the queue."""
        consecutive_failures = 0
        max_consecutive_failures = 600
        while not self._stop.is_set():
            if not self._cap or not self._cap.isOpened():
                break
            ret, frame = self._cap.read()
            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    LOGGER.warning("Stream read failed %d times: %s", consecutive_failures, self._url)
                    break
                time.sleep(0.05)
                continue

            consecutive_failures = 0

            # Drop old frames if queue is full
            if self._frame_queue.full():
                try:
                    self._frame_queue.get_nowait()
                    self._stats.frames_dropped += 1
                except queue.Empty:
                    pass

            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full:
                pass

        with self._reconnect_lock:
            if not self._stop.is_set():
                self._connected = False
        LOGGER.debug("Reader loop ended for %s", self._url)

    def _watchdog_loop(self) -> None:
        """Check for stale frames and trigger reconnect."""
        while not self._stop.is_set():
            time.sleep(5.0)
            if self._stop.is_set():
                break

            if not self._connected:
                self._try_reconnect()
                continue

            elapsed = time.monotonic() - self._stats.last_frame_time if self._stats.last_frame_time else 0
            if self._stats.last_frame_time > 0 and elapsed > self._watchdog_timeout:
                LOGGER.warning("Watchdog: no frames for %.1fs, reconnecting %s", elapsed, self._url)
                self._try_reconnect()

    def _try_reconnect(self) -> None:
        """Attempt to reconnect to the stream."""
        if not self._reconnect_lock.acquire(blocking=False):
            return
        try:
            attempt = 0
            while not self._stop.is_set():
                attempt += 1
                if self._max_reconnect_attempts > 0 and attempt > self._max_reconnect_attempts:
                    LOGGER.error("Max reconnect attempts reached for %s", self._url)
                    self._connected = False
                    return

                LOGGER.info("Reconnect attempt %d for %s", attempt, self._url)
                self._stats.reconnects += 1
                self._close_cap()

                # Drain the queue
                while not self._frame_queue.empty():
                    try:
                        self._frame_queue.get_nowait()
                    except queue.Empty:
                        break

                self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
                if self._hardware_decode and sys.platform == "win32":
                    self._cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_D3D11)

                if self._cap and self._cap.isOpened():
                    ret, frame = self._cap.read()
                    if ret and frame is not None:
                        self._connected = True
                        try:
                            self._frame_queue.put_nowait(frame)
                        except queue.Full:
                            pass
                        LOGGER.info("Reconnected to %s", self._url)

                        # Restart reader thread to continue delivering frames
                        if self._reader_thread is None or not self._reader_thread.is_alive():
                            self._reader_thread = threading.Thread(
                                target=self._reader_loop, daemon=True, name="vs-reader"
                            )
                            self._reader_thread.start()
                        return

                time.sleep(self._reconnect_delay)
        finally:
            self._reconnect_lock.release()


# ---------------------------------------------------------------------------
# Go2RTCManager
# ---------------------------------------------------------------------------

class Go2RTCManager:
    """
    Manage go2rtc as a subprocess (for local development).

    In Docker deployments, go2rtc runs as a separate container — this class
    is not needed. Use it for local development or Windows desktop usage.

    Args:
        go2rtc_dir: Path to go2rtc installation directory
        config_path: Optional override for go2rtc.yaml path
    """

    def __init__(self, go2rtc_dir: str, config_path: Optional[str] = None) -> None:
        self._dir = Path(go2rtc_dir)
        if sys.platform == "win32":
            self._exe = self._dir / "go2rtc.exe"
        else:
            self._exe = self._dir / "go2rtc"
        self._config = Path(config_path) if config_path else self._dir / "go2rtc.yaml"
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> bool:
        """Start go2rtc as a background process."""
        if self.is_running():
            LOGGER.info("go2rtc is already running")
            return True

        if not self._exe.exists():
            LOGGER.error("go2rtc not found at %s", self._exe)
            return False

        cmd = [str(self._exe)]
        if self._config.exists():
            cmd.extend(["-c", str(self._config)])

        self._process = subprocess.Popen(
            cmd,
            cwd=str(self._dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        LOGGER.info("go2rtc started (pid=%d)", self._process.pid)
        return True

    def stop(self) -> None:
        """Stop the go2rtc process."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            LOGGER.info("go2rtc stopped")
        self._process = None

    def is_running(self) -> bool:
        """Check if go2rtc process is alive."""
        if self._process and self._process.poll() is None:
            return True
        return False

    @property
    def api_url(self) -> str:
        port = os.getenv("GO2RTC_API_PORT", "1984")
        return f"http://localhost:{port}"
