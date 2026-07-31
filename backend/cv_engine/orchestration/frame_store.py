import os
import threading
import time
from typing import Optional

import cv2
import numpy as np

# Use /dev/shm (Linux RAM disk) if available, else system temp dir.
# This is required because CameraWorker runs in a separate multiprocessing.Process
# (separate memory space) and cannot read from the parent process's in-memory dict.
# /dev/shm is a tmpfs RAM filesystem — reads/writes are sub-millisecond with zero disk I/O.
_SHM_BASE = "/dev/shm" if os.path.isdir("/dev/shm") else os.path.join(os.path.dirname(__file__), "..", "..", "stream_cache")
_DEFAULT_SHM_DIR = os.path.abspath(os.path.join(_SHM_BASE, "framestore"))
os.makedirs(_DEFAULT_SHM_DIR, exist_ok=True)


class FrameStore:
    """Shared RAM-disk Frame Store (cross-process safe).

    Writes JPEG frames to /dev/shm (Linux tmpfs RAM disk) so both the
    parent cv-engine process (StreamManager) and child CameraWorker
    multiprocessing.Process instances share the same frames with
    sub-millisecond access and zero disk I/O overhead.

    When cache_dir is explicitly provided (e.g. in tests), that directory
    is used instead — allowing full test isolation.
    """

    def __init__(self, cache_dir: str = "stream_cache") -> None:
        # Use /dev/shm by default for cross-process sharing; use explicit
        # cache_dir if provided (allows test isolation via tempfile.TemporaryDirectory)
        if cache_dir == "stream_cache":
            self._dir = _DEFAULT_SHM_DIR
        else:
            self._dir = os.path.abspath(os.path.join(cache_dir, "framestore"))
            os.makedirs(self._dir, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._lock_lock = threading.Lock()


    def _get_lock(self, camera_id: str) -> threading.Lock:
        with self._lock_lock:
            if camera_id not in self._locks:
                self._locks[camera_id] = threading.Lock()
            return self._locks[camera_id]

    def _path(self, key: str, suffix: str = ".jpg") -> str:
        """Get the /dev/shm path for a given key."""
        safe = key.replace("/", "_").replace("\\", "_")
        return os.path.join(self._dir, f"{safe}{suffix}")

    def _write(self, key: str, jpeg_bytes: bytes) -> None:
        """Atomic write: write to .tmp then rename for zero corrupt-read risk."""
        path = self._path(key)
        tmp = path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(jpeg_bytes)
            os.replace(tmp, path)  # atomic on Linux
        except Exception:
            pass

    def _write_array(self, key: str, frame: np.ndarray) -> None:
        """Atomically store an uncompressed BGR frame as .npy (no JPEG round-trip).

        The worker process reads these directly instead of decoding a JPEG,
        which removes one imdecode+imencode per frame per camera from the
        CPU budget (the biggest win for sustaining constant FPS).
        """
        path = self._path(key, ".npy")
        tmp = path + ".tmp.npy"  # np.save appends .npy unless already present
        try:
            np.save(tmp, frame)
            os.replace(tmp, path)
        except Exception:
            pass

    def _read(self, key: str) -> Optional[bytes]:
        """Read JPEG bytes from /dev/shm."""
        path = self._path(key)
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def publish_bytes(
        self,
        camera_id: str,
        jpeg_bytes: bytes,
        annotated: bool = False,
        raw_frame: Optional[np.ndarray] = None,
    ) -> None:
        """Store pre-encoded JPEG bytes to /dev/shm.

        When raw_frame is provided (uncompressed BGR), also store it as .npy
        so detection workers can read it without decoding the JPEG.
        """
        key = f"annotated_{camera_id}" if annotated else camera_id
        self._write(key, jpeg_bytes)
        if raw_frame is not None and raw_frame.size > 0 and not annotated:
            self._write_array(key, raw_frame)

    def publish(self, camera_id: str, frame: np.ndarray, quality: int = 80) -> None:
        """Encode frame to JPEG and write to /dev/shm."""
        if frame is None or frame.size == 0:
            return
        ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ret:
            self._write(camera_id, buffer.tobytes())

    def publish_annotated(self, camera_id: str, frame: np.ndarray, quality: int = 80) -> None:
        """Encode annotated frame to JPEG and write to /dev/shm."""
        if frame is None or frame.size == 0:
            return
        ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ret:
            self._write(f"annotated_{camera_id}", buffer.tobytes())

    def latest_bytes(self, camera_id: str, annotated: bool = False) -> Optional[bytes]:
        """Fetch latest JPEG bytes from /dev/shm (sub-millisecond RAM read)."""
        key = f"annotated_{camera_id}" if annotated else camera_id
        return self._read(key)

    def latest_raw_frame(self, camera_id: str) -> Optional[np.ndarray]:
        """Fetch latest frame without a JPEG decode when possible.

        Prefers the uncompressed .npy copy (written alongside the JPEG by
        publish_bytes), falling back to decoding the stored JPEG.
        """
        try:
            arr = np.load(self._path(camera_id, ".npy"), allow_pickle=False)
            if arr is not None and arr.size > 0:
                return arr
        except Exception:
            pass
        data = self._read(camera_id)
        if data is None:
            return None
        arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def latest_mtime(self, camera_id: str, annotated: bool = False) -> float:
        """Fetch mtime of latest frame file from /dev/shm."""
        key = f"annotated_{camera_id}" if annotated else camera_id
        path = self._path(key)
        try:
            return os.path.getmtime(path)
        except FileNotFoundError:
            return 0.0

