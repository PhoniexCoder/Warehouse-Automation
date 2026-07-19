"""
Local DVRIP streaming test — connects directly to the NVR via the real
DVRIPClient, decodes H.264/H.265 I-frames via FFmpeg, and displays them
in a GUI window.

Usage:
    python test_stream.py                          # defaults: 192.168.1.35:34567 channel 0
    python test_stream.py --host 192.168.1.35 --channel 1
    python test_stream.py --no-gui                 # headless mode, saves frames to disk
"""

import argparse
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add backend to path so we can import the real DVRIPClient
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from cv_engine.services.dvrip_client import (
    DVRIPClient, DVRIPConnectionError, DVRIPAuthError, DVRIPTimeout,
)
from cv_engine.services.dvrip_frames import TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG

# ─── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("test_stream")


def decode_i_frame_to_jpeg(raw_nal: bytes, codec: str = "h264") -> bytes | None:
    """Decode a raw H.264/H.265 I-frame to JPEG via FFmpeg subprocess."""
    if not raw_nal:
        return None

    suffix = ".h264" if codec == "h264" else ".h265"

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
            tmp_in.write(raw_nal)
            input_path = tmp_in.name

        output_path = input_path + ".jpg"

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", input_path, "-frames:v", "1", "-y", output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=5)

        jpeg = None
        if result.returncode == 0 and os.path.exists(output_path):
            with open(output_path, "rb") as f:
                jpeg = f.read()

        try:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)
        except Exception:
            pass

        if jpeg:
            return jpeg

        if result.stderr:
            log.warning("FFmpeg error: %s", result.stderr.decode(errors="replace")[:200])

    except FileNotFoundError:
        log.error("ffmpeg not found in PATH — install ffmpeg first")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        log.warning("FFmpeg decode timed out")
    except Exception as e:
        log.warning("Decode error: %s", e)

    return None


def main():
    parser = argparse.ArgumentParser(description="Local DVRIP streaming test")
    parser.add_argument("--host", default="192.168.1.35", help="NVR IP address")
    parser.add_argument("--port", type=int, default=34567, help="NVR DVRIP port")
    parser.add_argument("--username", default="uxdp", help="NVR username")
    parser.add_argument("--password", default="cw8adc", help="NVR password")
    parser.add_argument("--channel", type=int, default=0, help="Camera channel (0-based)")
    parser.add_argument("--no-gui", action="store_true", help="Headless mode, save frames to disk")
    parser.add_argument("--max-frames", type=int, default=30, help="Max frames to capture")
    args = parser.parse_args()

    # Try importing cv2 for GUI display
    cv2 = None
    if not args.no_gui:
        try:
            import cv2 as _cv2
            cv2 = _cv2
        except ImportError:
            log.warning("cv2 not available — falling back to headless mode")
            args.no_gui = True

    # Connect to NVR using the real DVRIPClient
    log.info("Connecting to %s:%d channel=%d ...", args.host, args.port, args.channel)
    client = DVRIPClient(args.host, args.port, args.username, args.password)

    try:
        client.connect(channel=args.channel)
    except DVRIPAuthError as e:
        log.error("Auth failed: %s", e)
        sys.exit(1)
    except DVRIPConnectionError as e:
        log.error("Connection failed: %s", e)
        sys.exit(1)

    log.info(
        "Connected — device=%s channels=%d max_conn=%d — waiting for I-frames...",
        client.device_name, client.channel_count, client.max_connections,
    )

    frame_count = 0
    last_frame_time = time.time()
    output_dir = Path("test_frames")
    output_dir.mkdir(exist_ok=True)

    window_name = f"DVRIP Stream — {args.host} ch{args.channel}"
    fps_display = 0.0

    try:
        for ptype, payload, meta in client.iter_packets():
            if frame_count >= args.max_frames:
                log.info("Captured %d frames, done.", args.max_frames)
                break

            # Skip P-frames (can't decode without decoder state)
            if ptype == TYPE_P_FRAME:
                continue

            # For JPEG frames, payload is already JPEG
            if ptype == TYPE_JPEG:
                jpeg_bytes = payload
                log.info("[frame %d] JPEG packet (%d bytes) fps=%.1f",
                         frame_count + 1, len(jpeg_bytes), fps_display)
            elif ptype == TYPE_I_FRAME:
                codec_byte = meta.get("codec", 2)
                codec = "h265" if codec_byte in (3, 0x12, 0x13) else "h264"
                width = meta.get("width", 0)
                height = meta.get("height", 0)

                log.info("[frame %d] I-frame: codec=%s %dx%d (%d bytes) fps=%.1f",
                         frame_count + 1, codec, width, height, len(payload), fps_display)

                jpeg_bytes = decode_i_frame_to_jpeg(payload, codec)
                if not jpeg_bytes:
                    log.warning("[frame %d] Decode FAILED — skipping", frame_count + 1)
                    continue

                log.info("[frame %d] Decoded to JPEG: %d bytes", frame_count + 1, len(jpeg_bytes))
            else:
                continue

            # Save to disk
            frame_path = output_dir / f"frame_{frame_count:04d}.jpg"
            frame_path.write_bytes(jpeg_bytes)

            # Display in GUI
            if cv2 is not None:
                import numpy as np
                arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    # Overlay FPS
                    cv2.putText(
                        frame, f"FPS: {fps_display:.1f} | Frame {frame_count+1}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
                    )
                    cv2.imshow(window_name, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27 or key == ord("q"):
                        log.info("User quit")
                        break

            frame_count += 1
            now = time.time()
            dt = now - last_frame_time
            if dt > 0:
                fps_display = 1.0 / dt
            last_frame_time = now

    except KeyboardInterrupt:
        log.info("Interrupted")
    except DVRIPTimeout:
        log.warning("NVR timed out — no data received")
    except Exception as e:
        log.error("Error: %s", e, exc_info=True)
    finally:
        client.close()
        if cv2 is not None:
            cv2.destroyAllWindows()
        log.info("Done — %d frames captured in %s/", frame_count, output_dir)


if __name__ == "__main__":
    main()
