"""
Local DVRIP streaming test — connects directly to the NVR via the real
DVRIPClient, decodes H.264/H.265 I-frames and P-frames via persistent
FFmpeg pipe, and displays them in a GUI window at full NVR frame rate.

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
import threading
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


class PersistentDecoder:
    """Persistent FFmpeg process that decodes H.264/H.265 to JPEG via pipes.

    Maintains decoder state between frames, allowing P-frame decoding
    at full NVR frame rate (25+ FPS).
    """

    def __init__(self, codec: str = "h264", jpeg_quality: int = 3):
        self._codec = codec
        self._jpeg_quality = jpeg_quality
        self._proc = None
        self._running = False
        self._reader_thread = None
        self._latest_jpeg = None
        self._new_frame = threading.Event()
        self._lock = threading.Lock()
        self._frames_decoded = 0

    def start(self) -> bool:
        input_codec = "h264" if "h264" in self._codec else "hevc"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", input_codec, "-i", "pipe:0",
            "-f", "mjpeg", "-q:v", str(self._jpeg_quality), "pipe:1",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=0,
            )
        except FileNotFoundError:
            log.error("ffmpeg not found in PATH")
            return False

        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()
        log.info("Persistent FFmpeg decoder started (codec=%s)", self._codec)
        return True

    def _read_loop(self):
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
                jpeg = bytes(buf[soi:eoi + 2])
                del buf[:eoi + 2]
                with self._lock:
                    self._latest_jpeg = jpeg
                    self._frames_decoded += 1
                self._new_frame.set()
        self._running = False

    def decode(self, nal_bytes: bytes, timeout: float = 2.0):
        if not self._running or not self._proc or not nal_bytes:
            return None
        try:
            self._proc.stdin.write(nal_bytes)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._running = False
            return None
        self._new_frame.clear()
        if self._new_frame.wait(timeout=timeout):
            with self._lock:
                return self._latest_jpeg
        return None

    @property
    def is_running(self):
        return self._running and self._proc is not None and self._proc.poll() is None

    def stop(self):
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
        log.info("Decoder stopped (decoded=%d frames)", self._frames_decoded)


def main():
    parser = argparse.ArgumentParser(description="Local DVRIP streaming test (25 FPS)")
    parser.add_argument("--host", default="192.168.1.35", help="NVR IP address")
    parser.add_argument("--port", type=int, default=34567, help="NVR DVRIP port")
    parser.add_argument("--username", default="uxdp", help="NVR username")
    parser.add_argument("--password", default="cw8adc", help="NVR password")
    parser.add_argument("--channel", type=int, default=0, help="Camera channel (0-based)")
    parser.add_argument("--no-gui", action="store_true", help="Headless mode, save frames to disk")
    parser.add_argument("--max-frames", type=int, default=300, help="Max frames to capture")
    parser.add_argument("--debug", action="store_true", help="Verbose packet-level debug logging")
    parser.add_argument("--timeout", type=int, default=30, help="Seconds to wait before giving up (default 30)")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("cv_engine.services.dvrip_client").setLevel(logging.DEBUG)
        logging.getLogger("cv_engine.services.dvrip_frames").setLevel(logging.DEBUG)

    cv2 = None
    if not args.no_gui:
        try:
            import cv2 as _cv2
            cv2 = _cv2
        except ImportError:
            log.warning("cv2 not available — falling back to headless mode")
            args.no_gui = True

    # Connect to NVR
    log.info("Connecting to %s:%d channel=%d ...", args.host, args.port, args.channel)
    client = DVRIPClient(args.host, args.port, args.username, args.password)
    try:
        client.connect(channel=args.channel)
    except (DVRIPAuthError, DVRIPConnectionError) as e:
        log.error("Connection failed: %s", e)
        sys.exit(1)

    log.info("Connected — device=%s channels=%d — starting decode...", client.device_name, client.channel_count)

    # Debug: hook into packet reading to see raw data
    if args.debug:
        _orig_read_chunk = client._read_chunk
        _orig_read_packet = client._read_packet
        _chunk_count = [0]

        def _debug_read_chunk():
            chunk = _orig_read_chunk()
            _chunk_count[0] += 1
            if _chunk_count[0] <= 20:
                if chunk:
                    log.debug("CHUNK #%d: %d bytes: %s", _chunk_count[0], len(chunk), chunk[:40].hex())
                else:
                    log.debug("CHUNK #%d: None (timeout or error)", _chunk_count[0])
            return chunk

        def _debug_read_packet():
            buf = client._read_buf
            if buf:
                log.debug("READ_BUF: %d bytes, first 20: %s", len(buf), buf[:20].hex())
            result = _orig_read_packet()
            ptype, payload, meta = result
            log.debug("PACKET: type=0x%02X payload=%d bytes meta=%s", ptype, len(payload), meta)
            return result

        client._read_chunk = _debug_read_chunk
        client._read_packet = _debug_read_packet

    # Start persistent decoder
    decoder = PersistentDecoder(codec="h264", jpeg_quality=3)
    if not decoder.start():
        log.error("Failed to start FFmpeg decoder")
        client.close()
        sys.exit(1)

    frame_count = 0
    output_dir = Path("test_frames")
    output_dir.mkdir(exist_ok=True)
    window_name = f"DVRIP Stream — {args.host} ch{args.channel}"
    fps_counter = 0
    fps_time = time.time()
    fps_display = 0.0

    try:
        start_time = time.time()
        log.info("Entering packet loop...")
        packet_count = 0
        for ptype, payload, meta in client.iter_packets():
            packet_count += 1
            elapsed = time.time() - start_time

            if elapsed > args.timeout and frame_count == 0:
                log.error("TIMEOUT: No frames received in %d seconds. NVR may not be streaming on channel %d.",
                          args.timeout, args.channel)
                break

            if frame_count >= args.max_frames:
                log.info("Captured %d frames, done.", args.max_frames)
                break

            # Skip audio/info
            if ptype in (0xFA, 0xF9):
                continue

            # Detect codec
            codec = "h264"
            if "codec" in meta:
                cb = meta["codec"]
                if cb in (3, 0x12, 0x13):
                    codec = "h265"

            # Re-init decoder on codec change
            if decoder._codec != codec:
                log.info("Codec changed to %s — restarting decoder", codec)
                decoder.stop()
                decoder = PersistentDecoder(codec=codec, jpeg_quality=3)
                decoder.start()

            # JPEG packets pass through directly
            if ptype == TYPE_JPEG:
                jpeg_bytes = payload
            else:
                # I-frame or P-frame → feed to persistent FFmpeg
                jpeg_bytes = decoder.decode(payload)
                if not jpeg_bytes:
                    continue

            # Save to disk (every 10th frame)
            if frame_count % 10 == 0:
                frame_path = output_dir / f"frame_{frame_count:04d}.jpg"
                frame_path.write_bytes(jpeg_bytes)

            # Display
            if cv2 is not None:
                import numpy as np
                arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    cv2.putText(frame, f"FPS: {fps_display:.1f} | Frames: {frame_count}",
                                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    cv2.imshow(window_name, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27 or key == ord("q"):
                        break

            frame_count += 1
            fps_counter += 1
            now = time.time()
            if now - fps_time >= 1.0:
                fps_display = fps_counter / (now - fps_time)
                fps_counter = 0
                fps_time = now
                log.info("FPS: %.1f | Frames: %d | Decoder: %s",
                         fps_display, frame_count, decoder._frames_decoded)

    except KeyboardInterrupt:
        pass
    except DVRIPTimeout:
        log.warning("NVR timed out")
    except Exception as e:
        log.error("Error: %s", e, exc_info=True)
    finally:
        decoder.stop()
        client.close()
        if cv2 is not None:
            cv2.destroyAllWindows()
        log.info("Done — %d frames captured, %d packets received", frame_count, packet_count)


if __name__ == "__main__":
    main()
