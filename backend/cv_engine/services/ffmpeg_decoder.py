"""FFmpeg-based video decoders for live streaming.

Provides two decoder classes:
- FfmpegDecoder: Decodes raw H.264/H.265 Annex B NAL units (from DVRIP) to JPEG
- RtspDecoder: Reads RTSP streams directly and outputs JPEG frames

Both use persistent FFmpeg processes with pipe I/O for low-latency decoding.
"""

import logging
import os
import subprocess
import threading
import time
from typing import Optional

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)

JPEG_QUALITY_FFMPEG = 3
JPEG_QUALITY_CV = 60

_NAL_TERM = b"\x00\x00\x00\x01"


class FfmpegDecoder:
    """Persistent FFmpeg decoder for raw H.264/H.265 to JPEG via pipes.

    Writes Annex B NAL units to FFmpeg stdin, reads JPEG from stdout.
    Maintains decoder state between frames for P-frame decoding.
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
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._frames_decoded = 0
        self._errors = 0
        self._start_time = 0.0

        self._frame_counter = 0
        self._frame_cond = threading.Condition(self._lock)

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
        input_codec = "h264" if "h264" in self.codec else "hevc"

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-fflags", "nobuffer",
            "-probesize", "32768",
            "-analyzeduration", "0",
            "-f", input_codec,
            "-i", "pipe:0",
            "-flags", "low_delay",
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
        self._frame_counter = 0
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="ffmpeg-reader"
        )
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True, name="ffmpeg-stderr"
        )
        self._stderr_thread.start()

        LOGGER.info("FFmpeg decoder started (codec=%s)", self.codec)
        return True

    def _drain_stderr(self) -> None:
        """Drain FFmpeg stderr to prevent pipe deadlock on Windows."""
        try:
            while self._running and self._proc and self._proc.stderr:
                data = self._proc.stderr.read(4096)
                if not data:
                    break
                if data.strip():
                    LOGGER.debug("FFmpeg: %s", data.decode(errors="replace").strip())
        except Exception:
            pass

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

            while True:
                soi = buf.find(b"\xff\xd8")
                if soi < 0:
                    buf.clear()
                    break

                eoi = buf.find(b"\xff\xd9", soi + 2)
                if eoi < 0:
                    if soi > 0:
                        del buf[:soi]
                    break

                jpeg = bytes(buf[soi : eoi + 2])
                del buf[: eoi + 2]

                with self._lock:
                    self._frames_decoded += 1
                    self._frame_counter += 1
                    self._frame_cond.notify_all()

                self._latest_jpeg = jpeg

        self._running = False
        LOGGER.info("FFmpeg reader thread exiting")

    def decode(self, nal_bytes: bytes, timeout: float = 2.0) -> Optional[bytes]:
        """Feed raw NAL bytes to FFmpeg and return the latest JPEG frame.

        Appends a trailing Annex B start code so the raw HEVC demuxer
        can determine NAL boundaries without needing EOF on stdin.
        """
        if not self.is_running or not nal_bytes:
            return None

        with self._lock:
            expected = self._frame_counter + 1

        try:
            self._proc.stdin.write(nal_bytes + _NAL_TERM)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            LOGGER.warning("FFmpeg stdin write failed: %s", e)
            self._running = False
            return None

        deadline = time.monotonic() + timeout
        with self._lock:
            while time.monotonic() < deadline:
                if self._frame_counter >= expected:
                    return self._latest_jpeg
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._frame_cond.wait(timeout=min(remaining, 0.05))

        return None

    def stop(self) -> None:
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


class RtspDecoder:
    """Persistent FFmpeg decoder for RTSP streams to JPEG.

    Reads an RTSP URL directly via FFmpeg and outputs JPEG frames
    to stdout. No stdin needed — FFmpeg pulls from RTSP.
    """

    def __init__(
        self,
        rtsp_url: str,
        jpeg_quality: int = JPEG_QUALITY_FFMPEG,
        RTSP_TRANSPORT: str = "tcp",
    ) -> None:
        self.rtsp_url = rtsp_url
        self.jpeg_quality = jpeg_quality
        self.RTSP_TRANSPORT = RTSP_TRANSPORT

        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._frames_decoded = 0
        self._errors = 0
        self._start_time = 0.0

        self._frame_counter = 0
        self._frame_cond = threading.Condition(self._lock)

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
            "mode": "rtsp",
            "rtsp_url": self.rtsp_url,
            "fps": round(fps, 1),
        }

    def start(self) -> bool:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-rtsp_transport", self.RTSP_TRANSPORT,
            "-i", self.rtsp_url,
            "-f", "mjpeg",
            "-q:v", str(self.jpeg_quality),
            "-r", "25",
            "pipe:1",
        ]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError:
            LOGGER.error("ffmpeg not found in PATH")
            return False
        except Exception as e:
            LOGGER.error("Failed to start FFmpeg for RTSP: %s", e)
            return False

        self._running = True
        self._start_time = time.time()
        self._frame_counter = 0
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="rtsp-reader"
        )
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True, name="rtsp-stderr"
        )
        self._stderr_thread.start()

        LOGGER.info("RTSP decoder started (%s)", self.rtsp_url)
        return True

    def _drain_stderr(self) -> None:
        try:
            while self._running and self._proc and self._proc.stderr:
                data = self._proc.stderr.read(4096)
                if not data:
                    break
                if data.strip():
                    LOGGER.debug("FFmpeg RTSP: %s", data.decode(errors="replace").strip())
        except Exception:
            pass

    def _read_loop(self) -> None:
        buf = bytearray()
        while self._running:
            try:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
            except Exception:
                break

            buf.extend(chunk)

            while True:
                soi = buf.find(b"\xff\xd8")
                if soi < 0:
                    buf.clear()
                    break

                eoi = buf.find(b"\xff\xd9", soi + 2)
                if eoi < 0:
                    if soi > 0:
                        del buf[:soi]
                    break

                jpeg = bytes(buf[soi : eoi + 2])
                del buf[: eoi + 2]

                with self._lock:
                    self._frames_decoded += 1
                    self._frame_counter += 1
                    self._frame_cond.notify_all()

                self._latest_jpeg = jpeg

        self._running = False
        LOGGER.info("RTSP reader thread exiting")

    def read_frame(self, timeout: float = 2.0) -> Optional[bytes]:
        """Wait for the next JPEG frame from the RTSP stream."""
        if not self.is_running:
            return None

        with self._lock:
            expected = self._frame_counter

        deadline = time.monotonic() + timeout
        with self._lock:
            while time.monotonic() < deadline:
                if self._frame_counter > expected:
                    return self._latest_jpeg
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._frame_cond.wait(timeout=min(remaining, 0.05))

        return None

    def stop(self) -> None:
        self._running = False
        if self._proc:
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
            "RTSP decoder stopped (decoded=%d, errors=%d)",
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
