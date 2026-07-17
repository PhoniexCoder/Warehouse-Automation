"""
cv2.VideoCapture-compatible adapter for native DVRIP streams.

Wraps TVSDVRIPReader to provide .read() and .isOpened() so main2.py
and any OpenCV-based pipeline can use native DVRIP without RTSP/go2rtc.
"""

import cv2
import numpy as np
from dvrip_live_pipeline.tvs_dvrip import TVSDVRIPReader


class DVRIPCapture:
    """
    cv2.VideoCapture-compatible wrapper around TVSDVRIPReader.

    Usage:
        cap = DVRIPCapture("192.168.1.35", "uxdp", "cw8adc", channel=0)
        while cap.isOpened():
            ret, frame = cap.read()   # frame is BGR (OpenCV format)
            ...
        cap.release()
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        channel: int = 0,
        subtype: int = 0,
        port: int = 34567,
    ):
        self._reader = TVSDVRIPReader(
            host, username, password, port=port, buffer_size=5
        )
        self._opened = self._reader.open(channel, subtype)
        self._frame_w = 0
        self._frame_h = 0
        if self._opened:
            import time
            frame = self._reader.read(timeout=5.0)
            if frame[0] and frame[1] is not None:
                self._frame_h, self._frame_w = frame[1].shape[:2]

    def read(self):
        """
        Read next frame.

        Returns:
            (True, BGR ndarray) on success, (False, None) on failure.
        """
        ret, rgb = self._reader.read(timeout=2.0)
        if ret and rgb is not None:
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            return True, bgr
        return False, None

    def isOpened(self):
        return self._opened and self._reader.is_open()

    def release(self):
        self._reader.close()
        self._opened = False

    def get(self, propId):
        if propId == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._frame_w)
        elif propId == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._frame_h)
        elif propId == cv2.CAP_PROP_FPS:
            return 25.0
        elif propId == cv2.CAP_PROP_FRAME_COUNT:
            return -1.0
        return 0.0

    def set(self, propId, value):
        return False

    def grab(self):
        """Discard next frame (cv2.VideoCapture compatibility)."""
        ret, _ = self._reader.read(timeout=0.5)
        return ret
