"""FFmpeg-based H.264/H.265 to JPEG decoder.

Uses FFmpeg to decode raw H.264 Annex B NAL units to JPEG frames.
More reliable than cv2.imdecode for raw NAL streams from DVRIP NVRs.

Two decode modes:
1. File-based (FfmpegDecoder): Write NAL to temp file, decode, read JPEG.
   Proven reliable. ~5ms per frame on NVMe.
2. One-shot (decode_single_frame): Launch FFmpeg per call. Use for rare frames.
"""

import logging
import os
import subprocess
import tempfile
import threading
import time
from typing import Optional

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)

# JPEG quality for FFmpeg output (lower = better quality; FFmpeg -q:v scale)
JPEG_QUALITY_FFMPEG = 3
# JPEG quality for OpenCV fallback
JPEG_QUALITY_CV = 60

# Temp directory for decode files (shared across all decoders)
_DECODE_TMP_DIR = tempfile.mkdtemp(prefix="dvrip_decode_")


class FfmpegDecoder:
    """File-based FFmpeg decoder for raw H.264/H.265 to JPEG.

    Each decode() call:
    1. Writes NAL bytes to a temp .h264 file
    2. Runs: ffmpeg -i input.h264 -frames:v 1 -f image2pipe -vcodec mjpeg output
    3. Reads the JPEG output

    This is reliable because FFmpeg can properly detect access unit boundaries
    from a file (it can't always do this from a pipe with raw NAL streams).

    Thread-safe. Each camera should have its own FfmpegDecoder instance.
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

        self._lock = threading.Lock()
        self._frames_decoded = 0
        self._errors = 0
        self._tmp_dir = tempfile.mkdtemp(
            prefix=f"dec_{codec}_",
            dir=_DECODE_TMP_DIR,
        )

    @property
    def is_running(self) -> bool:
        return True  # File-based decoder is always "running"

    @property
    def stats(self) -> dict:
        return {
            "running": True,
            "frames_decoded": self._frames_decoded,
            "errors": self._errors,
            "codec": self.codec,
            "resolution": f"{self.width}x{self.height}",
            "mode": "file",
        }

    def start(self) -> bool:
        """No-op for file-based decoder."""
        return True

    def stop(self) -> None:
        """Clean up temp directory."""
        try:
            for f in os.listdir(self._tmp_dir):
                os.unlink(os.path.join(self._tmp_dir, f))
            os.rmdir(self._tmp_dir)
        except Exception:
            pass

    def decode(self, nal_bytes: bytes, timeout: float = 5.0) -> Optional[bytes]:
        """Decode raw H.264/H.265 Annex B bytes to JPEG.

        Args:
            nal_bytes: Raw H.264 Annex B NAL units (I-frame with SPS/PPS or P-frame)
            timeout: Max seconds to wait for FFmpeg

        Returns:
            JPEG bytes or None on failure
        """
        if not nal_bytes:
            return None

        suffix = ".h264" if "h264" in self.codec else ".h265"

        with self._lock:
            try:
                # Write NAL to temp file
                input_path = os.path.join(
                    self._tmp_dir, f"f{self._frames_decoded + self._errors:06d}{suffix}"
                )
                output_path = input_path + ".jpg"

                with open(input_path, "wb") as f:
                    f.write(nal_bytes)

                # Decode with FFmpeg
                # NOTE: Do NOT use "-f h264" — the raw H.264 demuxer fails on
                # some NVR streams. Auto-detect works reliably for all tested NVRs.
                cmd = [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel", "error",
                    "-i", input_path,
                    "-frames:v", "1",
                    "-y",
                    output_path,
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=timeout,
                )

                if result.returncode == 0 and os.path.exists(output_path):
                    with open(output_path, "rb") as f:
                        jpeg = f.read()

                    # Cleanup
                    try:
                        os.unlink(input_path)
                        os.unlink(output_path)
                    except Exception:
                        pass

                    if jpeg:
                        self._frames_decoded += 1
                        return jpeg

                self._errors += 1
                if result.stderr:
                    LOGGER.debug(
                        "FFmpeg decode failed: %s",
                        result.stderr.decode(errors="replace")[:200],
                    )

                # Cleanup on failure
                try:
                    os.unlink(input_path)
                    os.unlink(output_path)
                except Exception:
                    pass

                return None

            except subprocess.TimeoutExpired:
                self._errors += 1
                LOGGER.warning("FFmpeg decode timed out (%.1fs)", timeout)
                try:
                    os.unlink(input_path)
                except Exception:
                    pass
                return None

            except Exception as e:
                self._errors += 1
                LOGGER.warning("FFmpeg decode error: %s", e)
                return None


def decode_single_frame(
    nal_bytes: bytes, codec: str = "h264", width: int = 1920, height: int = 1080
) -> Optional[bytes]:
    """Decode a single H.264/H.265 access unit to JPEG using a one-shot FFmpeg call.

    Writes to a temp file, decodes, reads JPEG, cleans up.
    """
    if not nal_bytes:
        return None

    suffix = ".h264" if "h264" in codec else ".h265"
    input_codec = "h264" if "h264" in codec else "hevc"

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
            tmp_in.write(nal_bytes)
            input_path = tmp_in.name

        output_path = input_path + ".jpg"

        # NOTE: Do NOT use "-f h264" — auto-detect works reliably for all NVRs
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", input_path,
            "-frames:v", "1",
            "-y",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=5)

        if result.returncode == 0 and os.path.exists(output_path):
            with open(output_path, "rb") as f:
                jpeg = f.read()
            os.unlink(output_path)
            os.unlink(input_path)
            return jpeg if jpeg else None

        os.unlink(input_path)
        if os.path.exists(output_path):
            os.unlink(output_path)

    except FileNotFoundError:
        LOGGER.error("ffmpeg not found in PATH")
    except subprocess.TimeoutExpired:
        LOGGER.warning("FFmpeg one-shot decode timed out")
    except Exception as e:
        LOGGER.warning("FFmpeg one-shot decode failed: %s", e)

    return None


def decode_with_opencv(nal_bytes: bytes) -> Optional[np.ndarray]:
    """Fallback: try to decode NAL bytes with OpenCV.

    Only works if OpenCV's FFmpeg backend can handle raw NAL streams.
    Returns BGR numpy array or None.
    """
    try:
        np_arr = np.frombuffer(nal_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is not None and frame.size > 0:
            return frame
    except Exception:
        pass
    return None


def encode_jpeg(frame: np.ndarray, quality: int = JPEG_QUALITY_CV) -> Optional[bytes]:
    """Encode a BGR numpy frame to JPEG bytes."""
    try:
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return jpeg.tobytes()
    except Exception:
        return None
