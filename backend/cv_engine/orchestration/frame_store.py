import os
from typing import Optional

import cv2
import numpy as np


class FrameStore:
    def __init__(self, cache_dir: str = "stream_cache") -> None:
        self._cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def publish(self, camera_id: str, frame: np.ndarray, quality: int = 80) -> None:
        _, buffer = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        path = os.path.join(self._cache_dir, f"{camera_id}.jpg")
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(buffer.tobytes())
            os.replace(tmp_path, path)
        except PermissionError:
            pass

    def latest_bytes(self, camera_id: str) -> Optional[bytes]:
        path = os.path.join(self._cache_dir, f"{camera_id}.jpg")
        try:
            with open(path, "rb") as f:
                return f.read()
        except (FileNotFoundError, PermissionError):
            return None

    def latest_mtime(self, camera_id: str) -> float:
        path = os.path.join(self._cache_dir, f"{camera_id}.jpg")
        try:
            return os.path.getmtime(path)
        except (FileNotFoundError, PermissionError):
            return 0.0
