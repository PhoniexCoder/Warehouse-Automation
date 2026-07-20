import os
import threading
from typing import Optional

import cv2
import numpy as np


class FrameStore:
    def __init__(self, cache_dir: str = "stream_cache") -> None:
        self._cache_dir = os.path.abspath(cache_dir)
        os.makedirs(self._cache_dir, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._lock_lock = threading.Lock()

    def _get_lock(self, camera_id: str) -> threading.Lock:
        with self._lock_lock:
            if camera_id not in self._locks:
                self._locks[camera_id] = threading.Lock()
            return self._locks[camera_id]

    def publish(self, camera_id: str, frame: np.ndarray, quality: int = 80) -> None:
        _, buffer = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        path = os.path.join(self._cache_dir, f"{camera_id}.jpg")
        tmp_path = path + ".tmp"
        lock = self._get_lock(camera_id)
        with lock:
            try:
                with open(tmp_path, "wb") as f:
                    f.write(buffer.tobytes())
                os.replace(tmp_path, path)
            except PermissionError:
                pass

    def publish_annotated(self, camera_id: str, frame: np.ndarray, quality: int = 80) -> None:
        _, buffer = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        path = os.path.join(self._cache_dir, f"annotated_{camera_id}.jpg")
        tmp_path = path + ".tmp"
        lock = self._get_lock(camera_id)
        with lock:
            try:
                with open(tmp_path, "wb") as f:
                    f.write(buffer.tobytes())
                os.replace(tmp_path, path)
            except PermissionError:
                pass

    def latest_bytes(self, camera_id: str, annotated: bool = False) -> Optional[bytes]:
        prefix = "annotated_" if annotated else ""
        path = os.path.join(self._cache_dir, f"{prefix}{camera_id}.jpg")
        lock = self._get_lock(camera_id)
        with lock:
            try:
                with open(path, "rb") as f:
                    return f.read()
            except (FileNotFoundError, PermissionError):
                return None

    def latest_mtime(self, camera_id: str, annotated: bool = False) -> float:
        prefix = "annotated_" if annotated else ""
        path = os.path.join(self._cache_dir, f"{prefix}{camera_id}.jpg")
        try:
            return os.path.getmtime(path)
        except (FileNotFoundError, PermissionError):
            return 0.0
