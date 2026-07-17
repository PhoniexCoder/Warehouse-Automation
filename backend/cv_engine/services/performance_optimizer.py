import time

import cv2
import numpy as np

from cv_engine.config.inference_config import InferenceConfig


class PerformanceOptimizer:
    def __init__(
        self,
        input_size: int | None = None,
        frame_skip: int | None = None,
    ) -> None:
        self._input_size = input_size if input_size is not None else InferenceConfig.INPUT_SIZE
        self._frame_skip = frame_skip if frame_skip is not None else InferenceConfig.FRAME_SKIP

        self._frame_count = 0
        self._processed_count = 0

        self._fps_value = 0.0
        self._fps_counter = 0
        self._fps_start = time.perf_counter()

        self._last_inference_time = 0.0
        self._avg_inference_time = 0.0

    def should_process(self) -> bool:
        self._frame_count += 1
        return (self._frame_count - 1) % self._frame_skip == 0

    def resize(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if max(w, h) == self._input_size:
            return frame
        scale = self._input_size / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        new_w -= new_w % 32
        new_h -= new_h % 32
        new_w = max(new_w, 32)
        new_h = max(new_h, 32)
        return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    def tick(self, inference_time: float | None = None) -> None:
        self._processed_count += 1
        self._fps_counter += 1

        elapsed = time.perf_counter() - self._fps_start
        if elapsed >= 1.0:
            self._fps_value = round(self._fps_counter / elapsed, 1)
            self._fps_counter = 0
            self._fps_start = time.perf_counter()

        if inference_time is not None:
            self._last_inference_time = inference_time
            if self._avg_inference_time == 0.0:
                self._avg_inference_time = inference_time
            else:
                self._avg_inference_time = 0.95 * self._avg_inference_time + 0.05 * inference_time

    @property
    def fps(self) -> float:
        return self._fps_value

    @property
    def avg_inference_time_ms(self) -> float:
        return round(self._avg_inference_time * 1000, 1)

    @property
    def last_inference_time_ms(self) -> float:
        return round(self._last_inference_time * 1000, 1)

    @property
    def total_frames_seen(self) -> int:
        return self._frame_count

    @property
    def total_frames_processed(self) -> int:
        return self._processed_count

    @property
    def effective_skip(self) -> int:
        return self._frame_skip

    def stats(self) -> dict:
        return {
            "fps": self.fps,
            "avg_inference_ms": self.avg_inference_time_ms,
            "last_inference_ms": self.last_inference_time_ms,
            "total_frames": self.total_frames_seen,
            "processed_frames": self.total_frames_processed,
            "frame_skip": self.effective_skip,
            "input_size": self._input_size,
        }
