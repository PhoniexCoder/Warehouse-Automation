"""
Local DVRIP streaming test — connects directly to the NVR, decodes H.264/H.265
I-frames via FFmpeg, and displays them in a GUI window.

Usage:
    python test_stream.py                          # defaults: 192.168.1.35:34567 channel 0
    python test_stream.py --host 192.168.1.35 --channel 1
    python test_stream.py --no-gui                 # headless mode, saves frames to disk
"""

import argparse
import logging
import os
import struct
import subprocess
import sys
import tempfile
import time
import socket
import threading
from pathlib import Path

# ─── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("test_stream")

# ─── Constants ────────────────────────────────────────────────────────────
CMD_LOGIN = 1000
CMD_KEEPALIVE = 1006
CMD_OPMONITOR_CLAIM = 1413
CMD_OPMONITOR_START = 1410

TYPE_I_FRAME = 0xFC
TYPE_P_FRAME = 0xFD
TYPE_JPEG = 0xFE
TYPE_AUDIO = 0xFA
TYPE_INFO = 0xF9

FRAME_READ_TIMEOUT = 10.0
KEEPALIVE_INTERVAL = 15.0


def sofia_hash(password: str) -> str:
    """DVRIP/Sofia password hash."""
    md5 = __import__("hashlib").md5(password.encode("utf-8")).digest()
    chars = bytearray(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    out = []
    for i in range(8):
        a = md5[i]
        b = md5[i + 8]
        idx = (a + b) % 62
        out.append(chr(chars[idx]))
    return "".join(out)


class DVRIPTestClient:
    """Minimal DVRIP client for testing — login, claim, start, read frames."""

    def __init__(self, host: str, port: int, username: str, password: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._sock: socket.socket | None = None
        self._session = 0
        self._seq = 0
        self._lock = threading.Lock()
        self._connected = False
        self._keepalive_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._read_buf = bytearray()

        # Device info
        self.channel_count = 16
        self.device_name = ""

    def connect(self, channel: int = 0) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(10.0)
        self._sock.connect((self.host, self.port))
        self._connected = True
        log.info("TCP connected to %s:%d", self.host, self.port)

        self._login()
        self._opmonitor_claim()
        self._opmonitor_start(channel)
        self._start_keepalive()

    def _send(self, cmd: int, payload: bytes) -> int:
        with self._lock:
            seq = self._seq
            self._seq += 1
            header = bytearray(20)
            header[0] = 0xFF
            struct.pack_into("<I", header, 4, self._session)
            struct.pack_into("<I", header, 8, seq)
            struct.pack_into("<H", header, 14, cmd)
            struct.pack_into("<I", header, 16, len(payload))
            self._sock.sendall(bytes(header) + payload)
        return seq

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Connection closed")
            buf.extend(chunk)
        return bytes(buf)

    def _read_packet(self):
        """Read one complete DVRIP packet, return (cmd, seq, payload) or None on timeout."""
        while not self._stop.is_set():
            # Check for buffered data from _opmonitor_start
            if self._read_buf:
                # Try to parse a packet from the buffer
                if len(self._read_buf) >= 20:
                    if self._read_buf[0] != 0xFF:
                        # Binary video data pushed by NVR — not a DVRIP packet header
                        # This IS the video data, parse as a raw frame
                        data = bytes(self._read_buf)
                        self._read_buf.clear()
                        return (1404, 0, data)
                    # Regular DVRIP response
                    cmd_val = struct.unpack_from("<H", self._read_buf, 14)[0]
                    payload_len = struct.unpack_from("<I", self._read_buf, 16)[0]
                    if len(self._read_buf) >= 20 + payload_len:
                        payload = self._read_buf[20:20 + payload_len]
                        self._read_buf = self._read_buf[20 + payload_len:]
                        return (cmd_val, 0, payload)
                # Need more data — fall through to socket read
                break

            # Read 20-byte header from socket
            try:
                header = self._recv_exact(20)
            except (socket.timeout, ConnectionError, OSError):
                return None

            if header[0] != 0xFF:
                log.warning("Unexpected magic byte: 0x%02X", header[0])
                continue

            cmd_val = struct.unpack_from("<H", header, 14)[0]
            payload_len = struct.unpack_from("<I", header, 16)[0]

            if payload_len > 0:
                payload = self._recv_exact(payload_len)
            else:
                payload = b""

            return (cmd_val, 0, payload)

        return None

    def _login(self) -> None:
        pwd_hash = sofia_hash(self.password)
        login_json = (
            '{"EncryptType":"MD5","LoginType":"DVRIP-Web",'
            f'"PassWord":"{pwd_hash}","UserName":"{self.username}"'
            "}\n\x00"
        )
        self._send(CMD_LOGIN, login_json.encode())
        resp = self._recv_exact(20)
        ret = struct.unpack_from("<H", resp, 14)[0]
        payload_len = struct.unpack_from("<I", resp, 16)[0]
        if payload_len > 0:
            body = self._recv_exact(payload_len)
        else:
            body = b""
        if ret == 1000:
            self._session = struct.unpack_from("<I", body, 0)[0]
            # Parse channel count from response JSON
            try:
                import json
                json_str = body[4:].split(b"\x00")[0].decode("utf-8", errors="replace")
                data = json.loads(json_str)
                net_common = data.get("Ret", data)
                if isinstance(data, dict):
                    for key in data:
                        if "NetCommon" in str(data[key]):
                            net_common = data[key]
                            break
                    if "ChannelNum" in str(data):
                        nc = None
                        for k, v in data.items():
                            if isinstance(v, dict) and "ChannelNum" in v:
                                nc = v
                                break
                        if nc:
                            self.channel_count = nc.get("ChannelNum", 16)
                            self.device_name = nc.get("HostName", "")
            except Exception:
                pass
            log.info("Login OK, session=0x%08X, channels=%d, device=%s",
                     self._session, self.channel_count, self.device_name)
        else:
            raise ConnectionError(f"Login failed with ret={ret}")

    def _opmonitor_claim(self) -> None:
        claim_json = (
            '{"SessionID":"%08X","OPMonitor":{'
            '"Cmd":"OPMonitorClaim","Action":"Start",'
            '"Parameter":{"Channel":0,"CombineMode":"Two","StreamType":"Main"}}}\n\x00'
            % self._session
        )
        self._send(CMD_OPMONITOR_CLAIM, claim_json.encode())
        resp = self._recv_exact(20)
        ret = struct.unpack_from("<H", resp, 14)[0]
        payload_len = struct.unpack_from("<I", resp, 16)[0]
        if payload_len > 0:
            self._recv_exact(payload_len)
        log.info("OPMonitor Claim ret=%d", ret)

    def _opmonitor_start(self, channel: int = 0) -> None:
        start_json = (
            '{"SessionID":"%08X","OPMonitor":{'
            '"Cmd":"OPMonitorStart","Action":"Start",'
            '"Parameter":{"Channel":%d,"CombineMode":"Two","StreamType":"Main"}}}\n\x00'
            % (self._session, channel)
        )
        self._send(CMD_OPMONITOR_START, start_json.encode())
        # NVR may start pushing video immediately without a JSON response
        time.sleep(0.5)
        log.info("OPMonitor Start sent for channel %d", channel)

    def _start_keepalive(self) -> None:
        def _keepalive_loop():
            while not self._stop.is_set():
                self._stop.wait(KEEPALIVE_INTERVAL)
                if not self._stop.is_set():
                    try:
                        self._send(CMD_KEEPALIVE, b"")
                    except Exception:
                        break

        self._keepalive_thread = threading.Thread(target=_keepalive_loop, daemon=True)
        self._keepalive_thread.start()

    def iter_frames(self):
        """Yield (ptype, payload, meta_dict) for video frames."""
        for pkt in self._read_packets():
            if pkt is None:
                continue
            cmd_val, seq, payload = pkt
            if cmd_val == 1404:
                # Binary video data pushed by NVR
                data = payload
                if len(data) < 4:
                    continue
                ptype = data[0]
                if ptype in (TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG):
                    meta = {}
                    if ptype == TYPE_I_FRAME and len(data) >= 16:
                        codec_byte = data[1]
                        meta["codec"] = codec_byte
                        meta["fps"] = data[2]
                        meta["width"] = struct.unpack_from("<H", data, 4)[0] * 8
                        meta["height"] = struct.unpack_from("<H", data, 6)[0] * 8
                        frame_data = data[16:]
                    elif ptype == TYPE_JPEG:
                        frame_data = data[1:]
                    else:
                        frame_data = data[1:]
                    yield (ptype, frame_data, meta)
            elif cmd_val == 1000:
                # Login response (shouldn't happen here but handle)
                pass

    def _read_packets(self):
        """Low-level packet reader."""
        while not self._stop.is_set():
            pkt = self._read_packet()
            if pkt is None:
                continue
            yield pkt

    def close(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._connected = False
        log.info("Connection closed")


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

        # Cleanup
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

    # Connect to NVR
    log.info("Connecting to %s:%d channel=%d ...", args.host, args.port, args.channel)
    client = DVRIPTestClient(args.host, args.port, args.username, args.password)

    try:
        client.connect(channel=args.channel)
    except Exception as e:
        log.error("Connection failed: %s", e)
        sys.exit(1)

    log.info("Connected — waiting for I-frames...")

    frame_count = 0
    last_frame_time = time.time()
    output_dir = Path("test_frames")
    output_dir.mkdir(exist_ok=True)

    window_name = f"DVRIP Stream — {args.host} ch{args.channel}"

    try:
        for ptype, payload, meta in client.iter_frames():
            if frame_count >= args.max_frames:
                log.info("Captured %d frames, done.", args.max_frames)
                break

            # Skip P-frames (can't decode without decoder state)
            if ptype == TYPE_P_FRAME:
                continue

            # For JPEG frames, payload is already JPEG
            if ptype == TYPE_JPEG:
                jpeg_bytes = payload
                log.info("[frame %d] JPEG packet (%d bytes)", frame_count + 1, len(jpeg_bytes))
            elif ptype == TYPE_I_FRAME:
                codec_byte = meta.get("codec", 2)
                codec = "h265" if codec_byte in (3, 0x12, 0x13) else "h264"
                width = meta.get("width", 0)
                height = meta.get("height", 0)

                log.info("[frame %d] I-frame: codec=%s %dx%d (%d bytes)",
                         frame_count + 1, codec, width, height, len(payload))

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
            log.info("[frame %d] Saved to %s", frame_count + 1, frame_path)

            # Display in GUI
            if cv2 is not None:
                import numpy as np
                arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    cv2.imshow(window_name, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27 or key == ord("q"):  # ESC or Q to quit
                        log.info("User quit")
                        break

            frame_count += 1
            now = time.time()
            fps = 1.0 / (now - last_frame_time) if last_frame_time else 0
            last_frame_time = now
            log.info("  FPS: %.1f", fps)

    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        client.close()
        if cv2 is not None:
            cv2.destroyAllWindows()
        log.info("Done — %d frames captured in %s/", frame_count, output_dir)


if __name__ == "__main__":
    main()
