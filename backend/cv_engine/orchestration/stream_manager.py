"""Per-camera DVRIP connection lifecycle manager.

Manages DVRIP connections for each camera, decodes H.264/H.265 to JPEG
via FFmpeg subprocess, distributes JPEG frames to WebSocket subscribers
and FrameStore (for MJPEG fallback).

Includes staggered NVR connection scheduler to prevent exceeding the
NVR's max concurrent session limit and avoid thundering herd issues.
"""

import logging
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Optional

import cv2
import numpy as np

from cv_engine.orchestration.frame_store import FrameStore
from cv_engine.services.dvrip_client import DVRIPClient, DVRIPConnectionError, DVRIPAuthError
from cv_engine.services.dvrip_frames import TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG, TYPE_AUDIO, TYPE_INFO
from cv_engine.services.ffmpeg_decoder import FfmpegDecoder, encode_jpeg

LOGGER = logging.getLogger(__name__)

# JPEG quality for FrameStore persistence (detection workers read from here)
JPEG_QUALITY_STORE = 80
# JPEG quality for WebSocket streaming (speed over quality)
JPEG_QUALITY_STREAM = 60
# Max frames per second to WebSocket subscribers (avoid flooding)
FRAME_INTERVAL_MIN = 0.05  # 20 FPS max

# Reconnection settings
RECONNECT_BASE_DELAY = 2.0
RECONNECT_MAX_DELAY = 30.0
HEALTH_STALE_SECONDS = 20.0

# Default NVR connection limit (overridden by login response TCPMaxConn)
DEFAULT_MAX_CONNECTIONS = 8
# Delay between consecutive connections to the same NVR (avoids overwhelming it)
STAGGER_DELAY = 2.0


class NvrConnectionScheduler:
    """Per-NVR connection scheduler with staggered startup and blocking acquire.

    Uses a threading.Semaphore per NVR to enforce the connection limit.
    Threads block on acquire() instead of polling every 5 seconds.
    """

    def __init__(self) -> None:
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._max_per_nvr: dict[str, int] = {}
        self._last_connect_time: dict[str, float] = {}
        self._lock = threading.Lock()

    def _key(self, host: str, port: int) -> str:
        return f"{host}:{port}"

    def configure_nvr(self, host: str, port: int, max_connections: int) -> None:
        """Set the max connections for an NVR (from login response TCPMaxConn)."""
        key = self._key(host, port)
        with self._lock:
            if key not in self._semaphores or self._max_per_nvr.get(key) != max_connections:
                self._semaphores[key] = threading.Semaphore(max_connections)
                self._max_per_nvr[key] = max_connections
                LOGGER.info("NVR %s configured for %d max connections", key, max_connections)

    def acquire(self, host: str, port: int, timeout: float = 60.0) -> bool:
        """Block until a connection slot is available. Returns False on timeout."""
        key = self._key(host, port)

        # Ensure semaphore exists
        with self._lock:
            if key not in self._semaphores:
                self._semaphores[key] = threading.Semaphore(DEFAULT_MAX_CONNECTIONS)
                self._max_per_nvr[key] = DEFAULT_MAX_CONNECTIONS

        # Stagger: enforce minimum delay between connections to same NVR
        wait = 0.0
        with self._lock:
            last = self._last_connect_time.get(key, 0.0)
            elapsed = time.time() - last
            if elapsed < STAGGER_DELAY:
                wait = STAGGER_DELAY - elapsed

        # Sleep outside the lock to avoid blocking other NVR schedulers
        if wait > 0:
            time.sleep(wait)

        # Blocking acquire with timeout
        sem = self._semaphores[key]
        acquired = sem.acquire(timeout=timeout)
        if acquired:
            with self._lock:
                self._last_connect_time[key] = time.time()
        return acquired

    def release(self, host: str, port: int) -> None:
        """Release a connection slot."""
        key = self._key(host, port)
        with self._lock:
            sem = self._semaphores.get(key)
        if sem:
            try:
                sem.release()
            except ValueError:
                pass  # Released more than acquired

    def get_status(self) -> dict:
        """Return current state of all NVR schedulers."""
        status = {}
        with self._lock:
            for key, sem in self._semaphores.items():
                max_conn = self._max_per_nvr.get(key, DEFAULT_MAX_CONNECTIONS)
                # Count available permits (approximate)
                status[key] = {
                    "max_connections": max_conn,
                }
        return status


# Global scheduler (replaces old NvrConnectionLimiter)
_nvr_scheduler = NvrConnectionScheduler()


class CameraStream:
    """Manages a single camera's DVRIP connection and frame distribution.

    Lifecycle:
    1. Connect to NVR via DVRIPClient (JSON login, OPMonitor Claim+Start)
    2. Read packets: I-frames, P-frames, JPEG, audio, info
    3. Decode H.264/H.265 → JPEG via FFmpeg subprocess
    4. Distribute JPEG to WebSocket subscribers + FrameStore
    """

    def __init__(
        self,
        camera_id: str,
        host: str,
        port: int,
        username: str,
        password: str,
        channel: int,
        frame_store: FrameStore,
    ) -> None:
        self.camera_id = camera_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.channel = channel
        self._frame_store = frame_store

        self._client: Optional[DVRIPClient] = None
        self._decoder: Optional[FfmpegDecoder] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self._consecutive_errors = 0
        self._last_frame_time = 0.0
        self._total_frames = 0

        # WebSocket subscribers: dict[subscriber_id, queue_put_callable]
        self._ws_subscribers: dict[str, Callable] = {}
        self._sub_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def status(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "connected": self._connected,
            "running": self.is_running,
            "total_frames": self._total_frames,
            "last_frame_age": (
                time.time() - self._last_frame_time
                if self._last_frame_time
                else None
            ),
            "subscribers": len(self._ws_subscribers),
            "consecutive_errors": self._consecutive_errors,
            "decoder": self._decoder.stats if self._decoder else None,
        }

    def start(self) -> None:
        """Start the DVRIP connection and frame reader thread."""
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"dvrip-{self.camera_id}",
        )
        self._thread.start()
        LOGGER.info(
            "[%s] CameraStream started (NVR=%s:%d ch=%d)",
            self.camera_id,
            self.host,
            self.port,
            self.channel,
        )

    def stop(self) -> None:
        """Stop the connection and clean up."""
        self._stop.set()
        self._connected = False

        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

        if self._decoder:
            try:
                self._decoder.stop()
            except Exception:
                pass
            self._decoder = None

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        _nvr_scheduler.release(self.host, self.port)

    def subscribe_websocket(self, subscriber_id: str, queue_put: Callable) -> None:
        """Register a WebSocket subscriber for JPEG frames."""
        with self._sub_lock:
            self._ws_subscribers[subscriber_id] = queue_put
        LOGGER.debug(
            "[%s] WebSocket subscriber added: %s (total=%d)",
            self.camera_id,
            subscriber_id,
            len(self._ws_subscribers),
        )

    def unsubscribe_websocket(self, subscriber_id: str) -> None:
        """Remove a WebSocket subscriber."""
        with self._sub_lock:
            self._ws_subscribers.pop(subscriber_id, None)
        LOGGER.debug(
            "[%s] WebSocket subscriber removed: %s (total=%d)",
            self.camera_id,
            subscriber_id,
            len(self._ws_subscribers),
        )

    def _run(self) -> None:
        """Main loop: connect, read packets, decode, distribute."""
        while not self._stop.is_set():
            # Block until a connection slot is available (with stagger delay)
            if not _nvr_scheduler.acquire(self.host, self.port, timeout=30.0):
                LOGGER.warning(
                    "[%s] NVR connection slot timeout (%s:%d), retrying...",
                    self.camera_id, self.host, self.port,
                )
                self._stop.wait(10.0)
                continue

            try:
                self._connect()
                self._read_loop()
            except DVRIPConnectionError as e:
                LOGGER.warning("[%s] Connection failed: %s", self.camera_id, e)
            except DVRIPAuthError as e:
                LOGGER.error("[%s] Auth failed: %s", self.camera_id, e)
                break
            except Exception as e:
                LOGGER.exception("[%s] Unexpected error: %s", self.camera_id, e)
            finally:
                self._connected = False
                if self._client:
                    try:
                        self._client.close()
                    except Exception:
                        pass
                    self._client = None
                # Stop decoder between connections to reset state
                if self._decoder:
                    try:
                        self._decoder.stop()
                    except Exception:
                        pass
                    self._decoder = None
                _nvr_scheduler.release(self.host, self.port)

            if self._stop.is_set():
                break

            self._consecutive_errors += 1
            delay = min(
                RECONNECT_BASE_DELAY * (2 ** min(self._consecutive_errors - 1, 4)),
                RECONNECT_MAX_DELAY,
            )
            LOGGER.info(
                "[%s] Reconnecting in %.1fs (attempt %d)",
                self.camera_id,
                delay,
                self._consecutive_errors,
            )
            self._stop.wait(delay)

    def _connect(self) -> None:
        """Establish DVRIP connection to the NVR."""
        self._client = DVRIPClient(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
        )
        self._client.connect(channel=self.channel)
        self._connected = True
        self._consecutive_errors = 0

        # Update scheduler with NVR's actual connection limit from login response
        if self._client.max_connections:
            _nvr_scheduler.configure_nvr(self.host, self.port, self._client.max_connections)

        LOGGER.info(
            "[%s] DVRIP connected (channel=%d, device=%s, max_conn=%d)",
            self.camera_id, self.channel,
            self._client.device_name or "unknown",
            self._client.max_connections,
        )

    def _read_loop(self) -> None:
        """Read packets from DVRIP client, decode, and distribute.

        Decodes both I-frames and P-frames to JPEG. The persistent FFmpeg
        decoder maintains state between frames, allowing P-frame decoding
        at full NVR frame rate (25+ FPS).
        """
        assert self._client is not None

        for ptype, payload, meta in self._client.iter_packets():
            if self._stop.is_set():
                break

            # Skip audio and info packets
            if ptype in (TYPE_AUDIO, TYPE_INFO):
                continue

            # Skip non-video packets
            if ptype not in (TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG):
                continue

            # Detect codec from I-frame metadata; default to h264
            codec = "h264"
            if "codec" in meta:
                codec_byte = meta["codec"]
                if codec_byte in (3, 0x12, 0x13):
                    codec = "h265"

            self._total_frames += 1
            self._last_frame_time = time.time()

            # Decode I-frames, P-frames, and JPEG packets
            if ptype in (TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG):
                jpeg_bytes = self._decode_to_jpeg(payload, ptype, codec, meta)
                if jpeg_bytes:
                    self._distribute_jpeg(jpeg_bytes)

    def _decode_to_jpeg(
        self, payload: bytes, ptype: int, codec: str, meta: dict
    ) -> Optional[bytes]:
        """Decode raw video bytes to JPEG using the persistent FFmpeg decoder.

        The decoder maintains state between frames, allowing P-frame decoding.
        Re-initializes if codec changes (e.g., H.264 → H.265).
        """
        # Lazy-init or re-init on codec change
        if self._decoder is None or not self._decoder.is_running:
            width = meta.get("width", 1920)
            height = meta.get("height", 1080)
            self._decoder = FfmpegDecoder(
                width=width, height=height, codec=codec
            )
            if not self._decoder.start():
                LOGGER.error("[%s] Failed to start FFmpeg decoder", self.camera_id)
                self._decoder = None
                return None
        elif self._decoder.codec != codec:
            # Codec changed — restart decoder
            LOGGER.info(
                "[%s] Codec changed %s → %s, restarting decoder",
                self.camera_id, self._decoder.codec, codec,
            )
            self._decoder.stop()
            self._decoder = FfmpegDecoder(
                width=meta.get("width", 1920),
                height=meta.get("height", 1080),
                codec=codec,
            )
            if not self._decoder.start():
                LOGGER.error("[%s] Failed to restart FFmpeg decoder", self.camera_id)
                self._decoder = None
                return None

        # JPEG packets are already JPEG — pass through directly
        if ptype == TYPE_JPEG:
            return payload

        # Decode via persistent FFmpeg (works for both I-frames and P-frames)
        jpeg = self._decoder.decode(payload)
        if jpeg:
            return jpeg

        # Fallback: try OpenCV for I-frames only
        if ptype == TYPE_I_FRAME:
            try:
                np_arr = np.frombuffer(payload, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is not None and frame.size > 0:
                    return encode_jpeg(frame, JPEG_QUALITY_STREAM)
            except Exception:
                pass

        LOGGER.warning(
            "[%s] Decode failed for frame type 0x%02X (codec=%s, payload=%d bytes)",
            self.camera_id,
            ptype,
            codec,
            len(payload),
        )
        return None

    def _distribute_jpeg(self, jpeg_bytes: bytes) -> None:
        """Send JPEG bytes to WebSocket subscribers and FrameStore."""
        # Write to FrameStore for MJPEG fallback and detection workers
        try:
            import numpy as np
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                self._frame_store.publish(
                    self.camera_id, frame, quality=JPEG_QUALITY_STORE
                )
        except Exception:
            pass

        # Distribute to WebSocket subscribers (non-blocking)
        with self._sub_lock:
            dead = []
            for sub_id, put_fn in self._ws_subscribers.items():
                try:
                    put_fn(jpeg_bytes)
                except Exception:
                    dead.append(sub_id)
            for sid in dead:
                self._ws_subscribers.pop(sid, None)


class StreamManager:
    """Manages CameraStream instances for all active cameras."""

    def __init__(self, frame_store: FrameStore) -> None:
        self._frame_store = frame_store
        self._streams: dict[str, CameraStream] = {}
        self._lock = threading.Lock()

    @property
    def status(self) -> dict:
        with self._lock:
            return {
                cam_id: stream.status
                for cam_id, stream in self._streams.items()
            }

    def start_camera(
        self,
        camera_id: str,
        host: str,
        port: int,
        username: str,
        password: str,
        channel: int,
    ) -> None:
        """Start a DVRIP stream for a camera."""
        with self._lock:
            if camera_id in self._streams:
                existing = self._streams[camera_id]
                if existing.is_running:
                    return
                existing.stop()

            stream = CameraStream(
                camera_id=camera_id,
                host=host,
                port=port,
                username=username,
                password=password,
                channel=channel,
                frame_store=self._frame_store,
            )
            self._streams[camera_id] = stream
            stream.start()

    def stop_camera(self, camera_id: str) -> None:
        """Stop a camera's DVRIP stream."""
        with self._lock:
            stream = self._streams.pop(camera_id, None)
            if stream:
                stream.stop()

    def stop_all(self) -> None:
        """Stop all camera streams."""
        with self._lock:
            for stream in self._streams.values():
                stream.stop()
            self._streams.clear()

    def get_stream(self, camera_id: str) -> Optional[CameraStream]:
        """Get a camera's stream by ID."""
        with self._lock:
            return self._streams.get(camera_id)
