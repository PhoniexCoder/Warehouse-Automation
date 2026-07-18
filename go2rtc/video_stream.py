"""
VideoStream — robust RTSP reader with auto-reconnect, watchdog, and frame buffering.

Supports NVDEC GPU decoding via ffmpeg subprocess when available,
falls back to cv2.VideoCapture (CPU) otherwise.

Go2RTCManager — start/stop go2rtc as a subprocess (for local development).
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import struct
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

_nvdec_available: Optional[bool] = None


def _check_nvdec() -> bool:
    global _nvdec_available
    if _nvdec_available is not None:
        return _nvdec_available
    try:
        out = subprocess.check_output(
            ["ffmpeg", "-hide_banner", "-hwaccels"],
            stderr=subprocess.STDOUT, timeout=5,
        )
        _nvdec_available = b"cuda" in out
    except Exception:
        _nvdec_available = False
    if _nvdec_available:
        LOGGER.info("NVDEC GPU acceleration available")
    else:
        LOGGER.info("NVDEC not available, using CPU decoding")
    return _nvdec_available


def _probe_stream(url: str, timeout: int = 10) -> Optional[tuple[int, int]]:
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                url,
            ],
            stderr=subprocess.DEVNULL, timeout=timeout,
        )
        parts = out.decode().strip().split(",")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None


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
# GPU ffmpeg reader
# ---------------------------------------------------------------------------

class _FFmpegGPUReader:
    """Read frames from an RTSP stream using ffmpeg with NVDEC GPU decoding."""

    def __init__(self, url: str, width: int, height: int) -> None:
        self._url = url
        self._width = width
        self._height = height
        self._frame_size = width * height * 3
        self._proc: Optional[subprocess.Popen] = None
        self._open()

    def _open(self) -> None:
        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "warning",
            "-hwaccel", "cuda",
            "-rtsp_transport", "tcp",
            "-i", self._url,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-v", "error",
            "-an",
            "pipe:1",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=self._frame_size * 2,
        )

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        if not self._proc or self._proc.poll() is not None:
            return False, None
        try:
            raw = self._proc.stdout.read(self._frame_size)
            if raw is None or len(raw) < self._frame_size:
                return False, None
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(self._height, self._width, 3)
            return True, frame
        except Exception:
            return False, None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self) -> None:
        if self._proc:
            try:
                self._proc.stdout.close()
            except Exception:
                pass
            try:
                self._proc.stderr.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def __del__(self) -> None:
        self.close()


# ---------------------------------------------------------------------------
# VideoStream
# ---------------------------------------------------------------------------

class VideoStream:
    """
    Threaded RTSP/RTMP/HTTP stream reader with auto-reconnect and frame buffering.

    Uses NVDEC GPU decoding via ffmpeg subprocess when available,
    falls back to cv2.VideoCapture (CPU) otherwise.

    Threading model:
      - Reader thread: reads frames → queue
      - Watchdog thread: detects stale streams and triggers reconnect
      - Main thread: consumer calls read() to get latest frame
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
        self._gpu_reader: Optional[_FFmpegGPUReader] = None
        self._use_gpu = False
        self._width = 0
        self._height = 0
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
        try:
            frame = self._frame_queue.get(timeout=timeout)
            if frame is None:
                return False, None
            self._stats.frames_read += 1
            self._stats.last_frame_time = time.monotonic()
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
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def release(self) -> None:
        self._stop.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=5.0)
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=5.0)
        self._close_all()
        self._connected = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _close_all(self) -> None:
        if self._gpu_reader:
            try:
                self._gpu_reader.close()
            except Exception:
                pass
            self._gpu_reader = None
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _open_stream(self) -> None:
        self._close_all()

        use_gpu = _check_nvdec()

        if use_gpu:
            dims = _probe_stream(self._url)
            if dims:
                self._width, self._height = dims
                self._gpu_reader = _FFmpegGPUReader(self._url, self._width, self._height)
                if self._gpu_reader.is_alive():
                    self._use_gpu = True
                    self._connected = True
                    self._stop.clear()
                    self._start_threads()
                    LOGGER.info("GPU stream opened: %s (%dx%d)", self._url, self._width, self._height)
                    return
                else:
                    self._gpu_reader.close()
                    self._gpu_reader = None
                    LOGGER.warning("GPU reader failed, falling back to CPU for %s", self._url)

        self._use_gpu = False
        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if self._cap.isOpened():
            self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._connected = True
            self._stop.clear()
            self._start_threads()
            LOGGER.info("CPU stream opened: %s (%dx%d)", self._url, self._width, self._height)
        else:
            LOGGER.error("Cannot open stream: %s", self._url)
            self._connected = False

    def _start_threads(self) -> None:
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="vs-reader"
        )
        self._reader_thread.start()

        if self._enable_watchdog:
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True, name="vs-watchdog"
            )
            self._watchdog_thread.start()

    def _reader_loop(self) -> None:
        consecutive_failures = 0
        max_consecutive_failures = 600

        while not self._stop.is_set():
            if self._use_gpu:
                if not self._gpu_reader or not self._gpu_reader.is_alive():
                    break
                ret, frame = self._gpu_reader.read()
            else:
                if not self._cap or not self._cap.isOpened():
                    break
                ret, frame = self._cap.read()

            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    LOGGER.warning("Reader failed %d times: %s", consecutive_failures, self._url)
                    break
                time.sleep(0.05)
                continue

            consecutive_failures = 0

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
                self._close_all()

                while not self._frame_queue.empty():
                    try:
                        self._frame_queue.get_nowait()
                    except queue.Empty:
                        break

                use_gpu = _check_nvdec()

                if use_gpu:
                    dims = _probe_stream(self._url)
                    if dims:
                        self._width, self._height = dims
                        self._gpu_reader = _FFmpegGPUReader(self._url, self._width, self._height)
                        if self._gpu_reader.is_alive():
                            self._use_gpu = True
                            self._connected = True
                            LOGGER.info("GPU reconnected to %s", self._url)
                            self._restart_reader_thread()
                            return
                        self._gpu_reader.close()
                        self._gpu_reader = None

                self._use_gpu = False
                self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
                if self._cap and self._cap.isOpened():
                    ret, frame = self._cap.read()
                    if ret and frame is not None:
                        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        self._connected = True
                        try:
                            self._frame_queue.put_nowait(frame)
                        except queue.Full:
                            pass
                        LOGGER.info("CPU reconnected to %s", self._url)
                        self._restart_reader_thread()
                        return

                time.sleep(self._reconnect_delay)
        finally:
            self._reconnect_lock.release()

    def _restart_reader_thread(self) -> None:
        if self._reader_thread is None or not self._reader_thread.is_alive():
            self._reader_thread = threading.Thread(
                target=self._reader_loop, daemon=True, name="vs-reader"
            )
            self._reader_thread.start()


# ---------------------------------------------------------------------------
# Go2RTCManager
# ---------------------------------------------------------------------------

class Go2RTCManager:
    """
    Manage go2rtc as a subprocess (for local development).

    In Docker deployments, go2rtc runs as a separate container — this class
    is not needed. Use it for local development or Windows desktop usage.
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
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            LOGGER.info("go2rtc stopped")
        self._process = None

    def is_running(self) -> bool:
        if self._process and self._process.poll() is None:
            return True
        return False

    @property
    def api_url(self) -> str:
        port = os.getenv("GO2RTC_API_PORT", "1984")
        return f"http://localhost:{port}"
