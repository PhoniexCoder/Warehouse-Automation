import os
import threading
import time
from typing import Optional

import cv2
import numpy as np


class FrameStore:
    """In-Memory Frame Store.

    Stores live camera stream frames and JPEG encodings in RAM memory.
    Eliminates disk I/O latency, lock contention, and file-write overhead.
    """

    def __init__(self, cache_dir: str = "stream_cache") -> None:
        self._cache_dir = os.path.abspath(cache_dir)
        self._locks: dict[str, threading.Lock] = {}
        self._lock_lock = threading.Lock()

        # In-memory storage
        self._bytes: dict[str, bytes] = {}
        self._raw_frames: dict[str, np.ndarray] = {}
        self._mtimes: dict[str, float] = {}

    def _get_lock(self, camera_id: str) -> threading.Lock:
        with self._lock_lock:
            if camera_id not in self._locks:
                self._locks[camera_id] = threading.Lock()
            return self._locks[camera_id]

    def publish_bytes(
        self,
        camera_id: str,
        jpeg_bytes: bytes,
        annotated: bool = False,
        raw_frame: Optional[np.ndarray] = None,
    ) -> None:
        """Store pre-encoded JPEG bytes directly into RAM memory."""
        key = f"annotated_{camera_id}" if annotated else camera_id
        lock = self._get_lock(camera_id)
        with lock:
            self._bytes[key] = jpeg_bytes
            self._mtimes[key] = time.time()
            if raw_frame is not None and not annotated:
                self._raw_frames[camera_id] = raw_frame

    def publish(self, camera_id: str, frame: np.ndarray, quality: int = 80) -> None:
        """Encode frame to JPEG in memory and save directly to RAM store."""
        if frame is None or frame.size == 0:
            return
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        jpeg_bytes = buffer.tobytes()
        lock = self._get_lock(camera_id)
        with lock:
            self._bytes[camera_id] = jpeg_bytes
            self._raw_frames[camera_id] = frame
            self._mtimes[camera_id] = time.time()

    def publish_annotated(self, camera_id: str, frame: np.ndarray, quality: int = 80) -> None:
        """Encode annotated frame to JPEG in memory and save directly to RAM store."""
        if frame is None or frame.size == 0:
            return
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        jpeg_bytes = buffer.tobytes()
        key = f"annotated_{camera_id}"
        lock = self._get_lock(camera_id)
        with lock:
            self._bytes[key] = jpeg_bytes
            self._mtimes[key] = time.time()

    def latest_bytes(self, camera_id: str, annotated: bool = False) -> Optional[bytes]:
        """Fetch latest JPEG bytes directly from RAM (0ms latency, zero disk reads)."""
        key = f"annotated_{camera_id}" if annotated else camera_id
        lock = self._get_lock(camera_id)
        with lock:
            return self._bytes.get(key)

    def latest_raw_frame(self, camera_id: str) -> Optional[np.ndarray]:
        """Fetch latest uncompressed NumPy frame directly from RAM memory."""
        lock = self._get_lock(camera_id)
        with lock:
            frame = self._raw_frames.get(camera_id)
            return frame.copy() if frame is not None else None

    def latest_mtime(self, camera_id: str, annotated: bool = False) -> float:
        """Fetch latest timestamp from RAM."""
        key = f"annotated_{camera_id}" if annotated else camera_id
        lock = self._get_lock(camera_id)
        with lock:
            return self._mtimes.get(key, 0.0)

