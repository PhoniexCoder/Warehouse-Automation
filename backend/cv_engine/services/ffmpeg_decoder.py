"""FFmpeg-based H.264/H.265 to JPEG decoder.

Uses a persistent FFmpeg process with pipe I/O to decode raw H.264/H.265
Annex B NAL units (both I-frames and P-frames) to JPEG in real-time.

The persistent process maintains decoder state between frames, allowing
P-frame decoding at full NVR frame rate (25+ FPS).
"""

import logging
import os
import struct
import subprocess
import sys
import threading
import time
from typing import Optional

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)

# JPEG quality for FFmpeg output (1=best, 31=worst; 3 is high quality)
JPEG_QUALITY_FFMPEG = 3
# JPEG quality for OpenCV fallback
JPEG_QUALITY_CV = 60


class FfmpegDecoder:
    """Persistent FFmpeg decoder for raw H.264/H.265 to JPEG via pipes.

    Starts one FFmpeg process that reads raw NAL units from stdin and
    outputs JPEG frames to stdout. A background thread reads JPEGs
    from the stdout pipe.

    Usage:
        decoder = FfmpegDecoder(codec="h264", jpeg_quality=3)
        decoder.start()
        jpeg = decoder.decode(nal_bytes)  # blocks until JPEG is ready
        decoder.stop()
    """

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        codec: str = "h264",
        jpeg_quality: int = JPEG_QUALITY_FFMPEG,
    ) -> None:
        self.width = width
        self.height = height
        self.codec = codec
        self.jpeg_quality = jpeg_quality

        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._latest_jpeg: Optional[bytes] = None
        self._new_frame = threading.Event()
        self._lock = threading.Lock()
        self._frames_decoded = 0
        self._errors = 0
        self._start_time = 0.0

    @property
    def is_running(self) -> bool:
        return self._running and self._proc is not None and self._proc.poll() is None

    @property
    def stats(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        fps = self._frames_decoded / elapsed if elapsed > 0 else 0
        return {
            "running": self.is_running,
            "frames_decoded": self._frames_decoded,
            "errors": self._errors,
            "codec": self.codec,
            "resolution": f"{self.width}x{self.height}",
            "fps": round(fps, 1),
            "mode": "pipe",
        }

    def start(self) -> bool:
        """Start the persistent FFmpeg process."""
        input_codec = "h264" if "h264" in self.codec else "hevc"

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            # Input: raw H.264/H.265 from stdin
            "-f", input_codec,
            "-i", "pipe:0",
            # Output: MJPEG to stdout
            "-f", "mjpeg",
            "-q:v", str(self.jpeg_quality),
            "pipe:1",
        ]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError:
            LOGGER.error("ffmpeg not found in PATH")
            return False
        except Exception as e:
            LOGGER.error("Failed to start FFmpeg: %s", e)
            return False

        self._running = True
        self._start_time = time.time()
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="ffmpeg-reader"
        )
        self._reader_thread.start()
        LOGGER.info("FFmpeg decoder started (codec=%s)", self.codec)
        return True

    def _read_loop(self) -> None:
        """Background thread: read JPEG frames from FFmpeg stdout."""
        buf = bytearray()
        while self._running:
            try:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
            except Exception:
                break

            buf.extend(chunk)

            # Extract complete JPEG frames (SOI=FFD8 ... EOI=FFD9)
            while True:
                soi = buf.find(b"\xff\xd8")
                if soi < 0:
                    buf.clear()
                    break

                eoi = buf.find(b"\xff\xd9", soi + 2)
                if eoi < 0:
                    # Incomplete JPEG — keep from SOI onward, discard before
                    if soi > 0:
                        del buf[:soi]
                    break

                # Complete JPEG found
                jpeg = bytes(buf[soi : eoi + 2])
                del buf[: eoi + 2]

                with self._lock:
                    self._latest_jpeg = jpeg
                    self._frames_decoded += 1

                self._new_frame.set()

        self._running = False
        LOGGER.info("FFmpeg reader thread exiting")

    def decode(self, nal_bytes: bytes, timeout: float = 2.0) -> Optional[bytes]:
        """Feed raw NAL bytes to FFmpeg and return the latest JPEG frame.

        Args:
            nal_bytes: Raw H.264/H.265 Annex B NAL units (I-frame or P-frame)
            timeout: Max seconds to wait for a JPEG frame

        Returns:
            JPEG bytes, or None on failure/timeout
        """
        if not self.is_running or not nal_bytes:
            return None

        # Write NAL bytes to FFmpeg stdin
        try:
            self._proc.stdin.write(nal_bytes)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            LOGGER.warning("FFmpeg stdin write failed: %s", e)
            self._running = False
            return None

        # Wait for a JPEG frame from the reader thread
        self._new_frame.clear()
        if self._new_frame.wait(timeout=timeout):
            with self._lock:
                return self._latest_jpeg

        return None

    def stop(self) -> None:
        """Stop the FFmpeg process and clean up."""
        self._running = False
        if self._proc:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        LOGGER.info(
            "FFmpeg decoder stopped (decoded=%d, errors=%d)",
            self._frames_decoded,
            self._errors,
        )


def encode_jpeg(frame: np.ndarray, quality: int = JPEG_QUALITY_CV) -> Optional[bytes]:
    """Encode a BGR numpy frame to JPEG bytes."""
    try:
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return jpeg.tobytes()
    except Exception:
        return None
