"""Per-camera DVRIP connection lifecycle manager.

Manages DVRIP connections for each camera, decodes H.264/H.265 to JPEG
via FFmpeg subprocess, distributes JPEG frames to WebSocket subscribers
and FrameStore (for MJPEG fallback).

Includes NVR connection limiter to prevent exceeding the NVR's max
concurrent session limit (typically 8).
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

# NVR connection limiting — most NVRs allow max 8 simultaneous DVRIP sessions
MAX_CONNECTIONS_PER_NVR = 8


class NvrConnectionLimiter:
    """Tracks and limits concurrent DVRIP connections per NVR host:port."""

    def __init__(self, max_per_nvr: int = MAX_CONNECTIONS_PER_NVR) -> None:
        self._max = max_per_nvr
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def _key(self, host: str, port: int) -> str:
        return f"{host}:{port}"

    def acquire(self, host: str, port: int) -> bool:
        """Try to acquire a connection slot. Returns True if allowed."""
        with self._lock:
            key = self._key(host, port)
            if self._counts[key] >= self._max:
                return False
            self._counts[key] += 1
            return True

    def release(self, host: str, port: int) -> None:
        """Release a connection slot."""
        with self._lock:
            key = self._key(host, port)
            if self._counts[key] > 0:
                self._counts[key] -= 1

    @property
    def status(self) -> dict:
        with self._lock:
            return dict(self._counts)


# Global limiter
_nvr_limiter = NvrConnectionLimiter()


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

        _nvr_limiter.release(self.host, self.port)

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
            # Check NVR connection limit
            if not _nvr_limiter.acquire(self.host, self.port):
                LOGGER.warning(
                    "[%s] NVR connection limit reached (%s:%d), waiting...",
                    self.camera_id,
                    self.host,
                    self.port,
                )
                self._stop.wait(5.0)
                continue

            try:
                self._connect()
                self._read_loop()
            except DVRIPConnectionError as e:
                LOGGER.warning("[%s] Connection failed: %s", self.camera_id, e)
            except DVRIPAuthError as e:
                LOGGER.error("[%s] Auth failed: %s", self.camera_id, e)
                # Auth errors are permanent — don't retry
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
                _nvr_limiter.release(self.host, self.port)

            if self._stop.is_set():
                break

            # Exponential backoff reconnection
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
        LOGGER.info(
            "[%s] DVRIP connected to %s:%d",
            self.camera_id,
            self.host,
            self.port,
        )

    def _read_loop(self) -> None:
        """Read packets from DVRIP client, decode, and distribute.

        Only I-frames are decoded to JPEG (P-frames can't be decoded in
        isolation without decoder state). This gives us keyframe-rate FPS
        (~1 FPS) for live preview, which is acceptable for surveillance.
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

            # Detect codec from I-frame metadata
            if ptype == TYPE_I_FRAME and "codec" in meta:
                codec_byte = meta["codec"]
                if codec_byte in (3, 0x12, 0x13):
                    codec = "h265"
                else:
                    codec = "h264"

            self._total_frames += 1
            self._last_frame_time = time.time()

            # Only decode I-frames (keyframes) — P-frames need decoder state
            if ptype in (TYPE_I_FRAME, TYPE_JPEG):
                jpeg_bytes = self._decode_to_jpeg(payload, ptype, codec, meta)
                if jpeg_bytes:
                    self._distribute_jpeg(jpeg_bytes)

    def _decode_to_jpeg(
        self, payload: bytes, ptype: int, codec: str, meta: dict
    ) -> Optional[bytes]:
        """Decode raw video bytes to JPEG using FFmpeg decoder.

        Initializes the FFmpeg process lazily on first frame.
        """
        # Lazy-init FFmpeg decoder
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

        # Decode via FFmpeg
        jpeg = self._decoder.decode(payload)
        if jpeg:
            return jpeg

        # Fallback: try OpenCV (works for JPEG packets and sometimes raw NALs)
        if ptype == TYPE_JPEG:
            return payload  # Already JPEG

        frame = None
        if ptype == TYPE_I_FRAME:
            # I-frame with NAL units — try cv2.imdecode
            import numpy as np
            np_arr = np.frombuffer(payload, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is not None and frame.size > 0:
            return encode_jpeg(frame, JPEG_QUALITY_STREAM)

        LOGGER.debug(
            "[%s] Decode failed for frame type 0x%02X (codec=%s)",
            self.camera_id,
            ptype,
            codec,
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
