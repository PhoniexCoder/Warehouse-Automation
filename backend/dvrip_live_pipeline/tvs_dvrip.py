"""
Native DVRIP Video Reader for TVS/XM NVR

Implements the DVRIP protocol from scratch (matching XMEye/go2rtc)
to receive H.265 video directly over TCP without RTSP, go2rtc, or FFmpeg.

Protocol flow:
  1. TCP connect to port 34567
  2. Login with SofiaHash (XMMD5) authentication
  3. Send MonitorClaim (type 1413) + MonitorStart (type 1410)
  4. Read proprietary video framing: 00 00 01 XX + payload
  5. Extract H.265 Annex-B NAL units
  6. Decode with PyAV to numpy frames

Discovered packet types:
  0xFC / 0xFE  I-frame (keyframe) - 16-byte header + NAL units
  0xFD         P-frame            - 8-byte header + NAL units
  0xFA         Audio (G.711)      - 8-byte header + PCM data
  0xF9         Unknown/metadata   - skip

Author: Native DVRIP implementation for TVS Security warehouse AI system
"""

import socket
import struct
import time
import hashlib
import logging
import threading
import queue
from string import digits, ascii_uppercase, ascii_lowercase
from io import BytesIO
from typing import Optional, Tuple, NamedTuple
from collections import deque

import numpy as np

try:
    import av
    from av import CodecContext
    from av.codec import Codec
    HAS_PYAV = True
except ImportError:
    HAS_PYAV = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DVRIP_PORT = 34567
DVRIP_MAGIC = 0xFF
DVRIP_HEADER_SIZE = 20
DVRIP_HEADER_FMT = "<BBxxIIHHHI"

# Proprietary video framing types
FRAME_I_0xFC = 0xFC
FRAME_I_0xFE = 0xFE
FRAME_P_0xFD = 0xFD
FRAME_AUDIO_0xFA = 0xFA
FRAME_UNKNOWN_0xF9 = 0xF9

# DVRIP command types
CMD_LOGIN = 1000
CMD_ALIVE = 1006
CMD_MONITOR_CLAIM = 1413
CMD_MONITOR_START = 1410
CMD_MONITOR_STOP = 1412

# H.265 NAL unit types
NAL_VPS = 32
NAL_SPS = 33
NAL_PPS = 34
NAL_IDR_W_RADL = 19
NAL_IDR_N_LP = 20
NAL_TRAIL_R = 1
NAL_TRAIL_N = 0

# SofiaHash character set
_SOFIA_CHARS = digits + ascii_uppercase + ascii_lowercase


# ---------------------------------------------------------------------------
# SofiaHash (XMMD5) authentication
# ---------------------------------------------------------------------------
def sofia_hash(password: str) -> str:
    """Compute XMEye/Sofia password hash (same as dvrip library)."""
    h = hashlib.md5(password.encode("utf-8")).digest()
    return "".join(
        _SOFIA_CHARS[(a + b) % 62]
        for a, b in zip(h[0::2], h[1::2])
    )[:8]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
class DVRIPPacket(NamedTuple):
    """A single raw DVRIP packet."""
    session: int
    number: int
    field0: int
    field1: int
    ptype: int
    payload: bytes


class StreamInfo(NamedTuple):
    """Stream metadata from the NVR."""
    session_id: int
    alive_interval: int
    channel_num: int
    device_type: str
    data_use_aes: bool
    codec: str  # "H264" or "H265"


# ---------------------------------------------------------------------------
# Low-level DVRIP protocol client
# ---------------------------------------------------------------------------
class DVRIPConnection:
    """Low-level TCP connection to TVS/XM NVR."""

    def __init__(self, host: str, port: int = DVRIP_PORT):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.session: int = 0
        self.seq: int = 0
        self._lock = threading.Lock()

    def connect(self, timeout: float = 10.0):
        """Establish TCP connection."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.connect((self.host, self.port))
        logger.info(f"Connected to {self.host}:{self.port}")

    def close(self):
        """Close the connection."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def send_packet(self, cmd: int, payload: bytes):
        """Send a DVRIP command packet."""
        with self._lock:
            header = bytearray(DVRIP_HEADER_SIZE)
            header[0] = DVRIP_MAGIC
            struct.pack_into("<I", header, 4, self.session)
            struct.pack_into("<I", header, 8, self.seq)
            struct.pack_into("<H", header, 14, cmd)
            struct.pack_into("<I", header, 16, len(payload))

            data = bytes(header) + payload
            self.sock.settimeout(5)
            self.sock.sendall(data)
            self.seq += 1

    def recv_packet(self, timeout: float = 5.0) -> DVRIPPacket:
        """Receive one raw DVRIP packet."""
        self.sock.settimeout(timeout)
        header = self._read_exact(DVRIP_HEADER_SIZE)

        if header[0] != DVRIP_MAGIC:
            raise ValueError(f"Bad DVRIP magic: 0x{header[0]:02X}")

        session = struct.unpack_from("<I", header, 4)[0]
        number = struct.unpack_from("<I", header, 8)[0]
        field0 = struct.unpack_from("<H", header, 12)[0]
        field1 = struct.unpack_from("<H", header, 14)[0]
        ptype = struct.unpack_from("<H", header, 16)[0]
        length = struct.unpack_from("<I", header, 16)[0]

        payload = b""
        if length > 0:
            payload = self._read_exact(length)

        return DVRIPPacket(session, number, field0, field1, ptype, payload)

    def recv_json(self, timeout: float = 5.0) -> dict:
        """Receive a JSON response packet."""
        pkt = self.recv_packet(timeout)
        data = pkt.payload
        # Strip trailing \x0A\x00
        while data and data[-1] in (0x0A, 0x00):
            data = data[:-1]
        import json
        return json.loads(data.decode("utf-8"))

    def _read_exact(self, n: int) -> bytes:
        """Read exactly n bytes from the socket."""
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Socket closed by NVR")
            buf.extend(chunk)
        return bytes(buf)


# ---------------------------------------------------------------------------
# TVS DVRIP Client - Login and Monitor management
# ---------------------------------------------------------------------------
class TVSDVRIPClient:
    """High-level DVRIP client for TVS/XM NVRs."""

    def __init__(self, host: str, port: int = DVRIP_PORT):
        self.host = host
        self.port = port
        self.conn = DVRIPConnection(host, port)
        self.stream_info: Optional[StreamInfo] = None
        self._alive_thread: Optional[threading.Thread] = None
        self._alive_running = False

    def start_alive(self):
        """Start sending keepalive packets at AliveInterval / 2."""
        if self._alive_running:
            return
        if not self.stream_info:
            return
        interval = max(self.stream_info.alive_interval // 2, 5)
        self._alive_running = True
        self._alive_thread = threading.Thread(
            target=self._alive_loop, args=(interval,),
            daemon=True, name="DVRIPAlive",
        )
        self._alive_thread.start()
        logger.info(f"Alive thread started: every {interval}s")

    def _alive_loop(self, interval: int):
        """Send keepalive packets to prevent NVR disconnect."""
        while self._alive_running:
            time.sleep(interval)
            if not self._alive_running:
                break
            try:
                payload = (
                    '{"Name":"","SessionID":"0x'
                    + format(self.conn.session, "08X")
                    + '"}\x0A\x00'
                )
                self.conn.send_packet(CMD_ALIVE, payload.encode("utf-8"))
                self._drain_control_socket()
            except Exception as e:
                logger.warning(f"Alive send failed: {e}")

    def _drain_control_socket(self):
        """Drain any pending responses from the control socket.

        The NVR replies to alive packets and may send unsolicited status
        messages on the control socket. If nobody reads them, the TCP
        receive buffer fills up, which can cause flow-control stalls
        and eventually the NVR may drop ALL connections.
        """
        try:
            self.conn.sock.settimeout(0.5)
            while True:
                try:
                    data = self.conn.sock.recv(4096)
                    if not data:
                        break
                except socket.timeout:
                    break
        except Exception:
            pass

    def stop_alive(self):
        """Stop the keepalive thread."""
        self._alive_running = False
        if self._alive_thread and self._alive_thread.is_alive():
            self._alive_thread.join(timeout=2)
        self._alive_thread = None

    def connect_and_login(self, username: str, password: str) -> StreamInfo:
        """Connect to NVR, login, and extract stream info."""
        self.conn.connect()

        # Build login payload
        hash_val = sofia_hash(password)
        payload = (
            '{"EncryptType":"MD5","LoginType":"DVRIP-Web",'
            '"PassWord":"' + hash_val + '","UserName":"' + username + '"}'
            + "\x0A\x00"
        )

        self.conn.send_packet(CMD_LOGIN, payload.encode("utf-8"))
        reply = self.conn.recv_json()

        ret = reply.get("Ret")
        if ret != 100:
            raise ConnectionError(f"Login failed: Ret={ret}, reply={reply}")

        # Parse session
        session_str = reply.get("SessionID", "0x00000000")
        if isinstance(session_str, str):
            self.conn.session = int(session_str, 16)
        else:
            self.conn.session = session_str

        # Extract stream info
        alive_interval = reply.get("AliveInterval", 21)
        channel_num = reply.get("ChannelNum", 1)
        device_type = reply.get("DeviceType ", "NVR")
        data_use_aes = reply.get("DataUseAES", False)

        self.stream_info = StreamInfo(
            session_id=self.conn.session,
            alive_interval=alive_interval,
            channel_num=channel_num,
            device_type=device_type,
            data_use_aes=data_use_aes,
            codec="H265",  # will be confirmed during probing
        )

        logger.info(
            f"Login OK  Session=0x{self.conn.session:08X}  "
            f"Alive={alive_interval}s  Channels={channel_num}  "
            f"Device={device_type}  AES={data_use_aes}"
        )

        return self.stream_info

    def _send_raw_packet(
        self, sock: socket.socket, cmd: int, payload: bytes, seq: int
    ):
        """Send a raw DVRIP packet on an arbitrary socket."""
        header = bytearray(DVRIP_HEADER_SIZE)
        header[0] = DVRIP_MAGIC
        struct.pack_into("<I", header, 4, self.conn.session)
        struct.pack_into("<I", header, 8, seq)
        struct.pack_into("<H", header, 14, cmd)
        struct.pack_into("<I", header, 16, len(payload))
        sock.sendall(bytes(header) + payload)

    def _recv_raw_json(
        self, sock: socket.socket, timeout: float = 5.0
    ) -> dict:
        """Receive one DVRIP JSON packet from an arbitrary socket."""
        import json as _json

        sock.settimeout(timeout)
        buf = bytearray()
        while len(buf) < DVRIP_HEADER_SIZE:
            chunk = sock.recv(DVRIP_HEADER_SIZE - len(buf))
            if not chunk:
                raise ConnectionError("Socket closed")
            buf.extend(chunk)

        if buf[0] != DVRIP_MAGIC:
            raise ValueError(f"Bad magic: 0x{buf[0]:02X}")

        length = struct.unpack_from("<I", buf, 16)[0]
        payload = b""
        if length > 0:
            remaining = length
            while remaining > 0:
                chunk = sock.recv(remaining)
                if not chunk:
                    raise ConnectionError("Socket closed during payload")
                payload += chunk
                remaining -= len(chunk)

        while payload and payload[-1] in (0x0A, 0x00):
            payload = payload[:-1]
        return _json.loads(payload.decode("utf-8"))

    def start_monitor(
        self, channel: int = 0, subtype: int = 0
    ) -> socket.socket:
        """
        Start monitor stream and return the data socket.

        The data socket will receive the proprietary video stream
        after MonitorClaim + MonitorStart are sent.

        Args:
            channel: Camera channel number
            subtype: 0=Main (HD), 1=Extra (SD)

        Returns:
            The data socket for reading video packets
        """
        stream_type = "Main" if subtype == 0 else "Extra1"
        params = (
            '{"Channel":' + str(channel) + ',"CombinMode":"NONE",'
            '"StreamType":"' + stream_type + '","TransMode":"TCP"}'
        )

        # Create data socket
        data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        data_sock.settimeout(5)
        data_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        data_sock.connect((self.host, self.port))

        # Send MonitorClaim on the DATA socket
        claim_payload = (
            '{"Name":"OPMonitor","SessionID":"0x'
            + format(self.conn.session, "08X")
            + '","OPMonitor":{"Action":"Claim","Parameter":'
            + params + '}}\x0A\x00'
        )
        self._send_raw_packet(
            data_sock, CMD_MONITOR_CLAIM,
            claim_payload.encode("utf-8"), seq=0,
        )

        # Read MonitorClaim reply from the DATA socket
        try:
            claim_reply = self._recv_raw_json(data_sock, timeout=5)
            logger.info(f"MonitorClaim reply: Ret={claim_reply.get('Ret')}")
        except Exception as e:
            logger.warning(f"MonitorClaim reply read failed (non-fatal): {e}")

        # Send MonitorStart on the DATA socket (same socket as Claim)
        # This matches what XMEye/go2rtc/dump_dvrip_raw_v2.py does.
        # Sending MonitorStart on the control socket causes the NVR to
        # kill the data connection after ~15-30s.
        start_payload = (
            '{"Name":"OPMonitor","SessionID":"0x'
            + format(self.conn.session, "08X")
            + '","OPMonitor":{"Action":"Start","Parameter":'
            + params + '}}\x0A\x00'
        )
        self._send_raw_packet(
            data_sock, CMD_MONITOR_START,
            start_payload.encode("utf-8"), seq=0,
        )

        logger.info(
            f"Monitor started: channel={channel} subtype={stream_type}"
        )

        return data_sock

    def stop_monitor(self):
        """Stop the monitor stream."""
        try:
            self.conn.send_packet(CMD_MONITOR_STOP, b"")
        except Exception:
            pass

    def logout(self):
        """Logout from the NVR."""
        try:
            payload = (
                '{"Name":"","SessionID":"0x'
                + format(self.conn.session, "08X")
                + '"}\x0A\x00'
            )
            self.conn.send_packet(1002, payload.encode("utf-8"))
        except Exception:
            pass

    def close(self):
        """Close all connections."""
        self.stop_alive()
        try:
            self.stop_monitor()
        except Exception:
            pass
        try:
            self.logout()
        except Exception:
            pass
        self.conn.close()


# ---------------------------------------------------------------------------
# Proprietary video stream parser
# ---------------------------------------------------------------------------
class TVSStreamParser:
    """
    Parses the proprietary TVS/XM video framing.

    After MonitorStart, the data socket delivers DVRIP packets whose
    payloads contain:

      [00 00 01 XX] [header] [NAL units / audio data]

    Where XX is:
      0xFC / 0xFE  I-frame (keyframe) - 16-byte header
      0xFD         P-frame           - 8-byte header
      0xFA         Audio             - 8-byte header
      0xF9         Unknown/metadata  - skip
    """

    def __init__(self):
        self.buf = bytearray()
        self.frame_count = 0
        self.codec: Optional[str] = None  # "H264" or "H265"
        self.vps: Optional[bytes] = None
        self.sps: Optional[bytes] = None
        self.pps: Optional[bytes] = None
        # Multi-packet frame accumulation state
        self._pending_header_size = 0
        self._pending_total_size = 0
        self._pending_frame_type = ""

    def feed(self, data: bytes) -> list:
        """
        Feed raw data from the DVRIP data socket and extract NAL units.

        Returns a list of (frame_type, annex_b_data) tuples.
        """
        self.buf.extend(data)
        frames = []

        while True:
            # If we're accumulating a multi-packet frame, check if we have enough
            if self._pending_total_size > 0:
                if len(self.buf) < self._pending_total_size:
                    break  # Wait for more data

                annex_b = bytes(self.buf[self._pending_header_size:self._pending_total_size])
                self.buf = self.buf[self._pending_total_size:]
                self._pending_total_size = 0

                self._detect_codec(annex_b)
                self.frame_count += 1
                frames.append((self._pending_frame_type, annex_b))
                continue

            # Find framing marker: 00 00 01 XX
            if len(self.buf) < 4:
                break

            if not (self.buf[0] == 0 and self.buf[1] == 0 and self.buf[2] == 1):
                # Scan for next framing marker
                found = False
                scan_limit = min(len(self.buf), 4096)
                for i in range(1, scan_limit - 2):
                    if (self.buf[i] == 0 and self.buf[i+1] == 0
                            and self.buf[i+2] == 1
                            and i + 3 < len(self.buf)
                            and self.buf[i+3] in (
                                FRAME_I_0xFC, FRAME_I_0xFE, FRAME_P_0xFD,
                                FRAME_AUDIO_0xFA, FRAME_UNKNOWN_0xF9)):
                        self.buf = self.buf[i:]
                        found = True
                        break
                if not found:
                    break
                continue

            frame_type_byte = self.buf[3]

            if frame_type_byte in (FRAME_I_0xFC, FRAME_I_0xFE):
                header_size = 16
                if len(self.buf) < header_size:
                    break
                total_size = struct.unpack_from("<I", self.buf, 12)[0] + header_size
                frame_type = "I"
            elif frame_type_byte == FRAME_P_0xFD:
                header_size = 8
                if len(self.buf) < header_size:
                    break
                total_size = struct.unpack_from("<I", self.buf, 4)[0] + header_size
                frame_type = "P"
            elif frame_type_byte == FRAME_AUDIO_0xFA:
                header_size = 8
                if len(self.buf) < header_size:
                    break
                total_size = struct.unpack_from("<H", self.buf, 6)[0] + header_size
                self.buf = self.buf[total_size:]
                continue
            elif frame_type_byte == FRAME_UNKNOWN_0xF9:
                self.buf = self.buf[4:]
                continue
            else:
                self.buf = self.buf[3:]
                continue

            if total_size > len(self.buf):
                # Enter accumulation state for multi-packet frames
                self._pending_header_size = header_size
                self._pending_total_size = total_size
                self._pending_frame_type = frame_type
                break  # Wait for more data

            # Frame fits in buffer — extract directly
            annex_b = bytes(self.buf[header_size:total_size])
            self.buf = self.buf[total_size:]

            self._detect_codec(annex_b)
            self.frame_count += 1
            frames.append((frame_type, annex_b))

        return frames

    def _detect_codec(self, annex_b: bytes):
        """Scan Annex-B stream for VPS/SPS/PPS to detect codec."""
        i = 0
        while i + 4 < len(annex_b):
            # Find Annex-B start code 00 00 00 01 or 00 00 01
            if annex_b[i] == 0 and annex_b[i+1] == 0:
                if annex_b[i+2] == 1:
                    start = i + 3
                elif annex_b[i+2] == 0 and i + 3 < len(annex_b) and annex_b[i+3] == 1:
                    start = i + 4
                else:
                    i += 1
                    continue

                if start >= len(annex_b):
                    break

                nal_header = annex_b[start]

                # H.265: NAL type is bits 1-6 of first byte
                nal_type_265 = (nal_header >> 1) & 0x3F
                # H.264: NAL type is bits 0-4
                nal_type_264 = nal_header & 0x1F

                if nal_type_265 == NAL_VPS:
                    self.codec = "H265"
                elif nal_type_265 == NAL_SPS:
                    self.codec = "H265"
                elif nal_type_265 == NAL_PPS:
                    self.pps = True
                elif nal_type_264 == 7:
                    self.codec = "H264"
                elif nal_type_264 == 8:
                    self.pps = True

                i = start + 1
            else:
                i += 1


# ---------------------------------------------------------------------------
# PyAV Decoder - converts H.265/H.264 byte streams to numpy frames
# ---------------------------------------------------------------------------
class H265Decoder:
    """Hardware-accelerated H.265/H.264 decoder using PyAV."""

    def __init__(self):
        if not HAS_PYAV:
            raise RuntimeError("PyAV not installed. Install: pip install av")

        self._codec_ctx: Optional[CodecContext] = None
        self._initialized = False
        self._width = 0
        self._height = 0

    def initialize(self, annex_b_data: bytes) -> bool:
        """
        Initialize the decoder with the first keyframe containing
        VPS/SPS/PPS NAL units.
        """
        try:
            # Detect codec from NAL units
            codec_name = "hevc"  # default to H.265
            if b"\x00\x00\x00\x01\x67" in annex_b_data:  # H.264 SPS
                codec_name = "h264"

            codec = Codec(codec_name, "r")
            self._codec_ctx = CodecContext.create(codec)
            self._codec_ctx.open()

            # Feed the first packet (contains VPS/SPS/PPS)
            packet = av.Packet(annex_b_data)
            self._codec_ctx.decode(packet)

            self._initialized = True
            logger.info(f"Decoder initialized: {codec_name}")
            return True

        except Exception as e:
            logger.error(f"Decoder init failed: {e}")
            self._initialized = False
            return False

    def decode(self, annex_b_data: bytes) -> list:
        """
        Decode H.265/H.264 Annex-B data into numpy frames.

        Returns list of (numpy_array, pts) tuples.
        """
        if not self._initialized or self._codec_ctx is None:
            return []

        frames = []
        try:
            packet = av.Packet(annex_b_data)
            decoded_frames = self._codec_ctx.decode(packet)

            for frame in decoded_frames:
                img = frame.to_ndarray(format="rgb24")
                self._width = img.shape[1]
                self._height = img.shape[0]
                pts = frame.pts / frame.time_base if frame.pts else 0
                frames.append((img, pts))

        except Exception as e:
            logger.debug(f"Decode error (non-fatal): {e}")

        return frames

    @property
    def resolution(self) -> Tuple[int, int]:
        return (self._width, self._height)

    def flush(self):
        """Flush any buffered frames."""
        if self._codec_ctx:
            try:
                self._codec_ctx.decode(None)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main video reader - combines connection, parsing, and decoding
# ---------------------------------------------------------------------------
class TVSDVRIPReader:
    """
    Production-grade DVRIP video reader for TVS/XM NVRs.

    Provides a cv2.VideoCapture-like interface:
        reader = TVSDVRIPReader("192.168.1.35", "uxdp", "cw8adc")
        reader.open(channel=0)
        while True:
            ret, frame = reader.read()
            if ret:
                # frame is numpy.ndarray (H, W, 3) RGB
                process(frame)
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = DVRIP_PORT,
        buffer_size: int = 5,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.buffer_size = buffer_size

        self._client: Optional[TVSDVRIPClient] = None
        self._parser: Optional[TVSStreamParser] = None
        self._decoder: Optional[H265Decoder] = None
        self._data_sock: Optional[socket.socket] = None

        self._frame_queue: queue.Queue = queue.Queue(maxsize=buffer_size)
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._stream_info: Optional[StreamInfo] = None

        self._frame_number = 0
        self._last_frame_time = 0.0
        self._connected = False
        self._channel = 0
        self._subtype = 0

    def open(self, channel: int = 0, subtype: int = 0) -> bool:
        """
        Open the DVRIP stream.

        Args:
            channel: Camera channel number
            subtype: 0=Main (HD), 1=Extra (SD)

        Returns:
            True if connected and streaming
        """
        self._channel = channel
        self._subtype = subtype
        try:
            # Connect and login
            self._client = TVSDVRIPClient(self.host, self.port)
            self._stream_info = self._client.connect_and_login(
                self.username, self.password
            )

            # Start monitor
            self._data_sock = self._client.start_monitor(channel, subtype)

            # Start keepalive thread
            self._client.start_alive()

            # Initialize parser and decoder
            self._parser = TVSStreamParser()
            self._decoder = H265Decoder()

            # Start reader thread
            self._running = True
            self._connected = True
            self._reader_thread = threading.Thread(
                target=self._reader_loop, daemon=True, name="DVRIPReader"
            )
            self._reader_thread.start()

            logger.info(
                f"DVRIP stream opened: channel={channel} subtype={subtype} "
                f"codec={self._stream_info.codec}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to open DVRIP stream: {e}")
            self.close()
            return False

    def read(self, timeout: float = 5.0) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read the next frame (cv2.VideoCapture compatible).

        Returns:
            (success, frame) where frame is numpy.ndarray (H, W, 3) RGB
        """
        try:
            ret, frame = self._frame_queue.get(timeout=timeout)
            return ret, frame
        except queue.Empty:
            return False, None

    def is_open(self) -> bool:
        """Check if the stream is connected and open."""
        return self._connected and self._running

    def get_stream_info(self) -> Optional[StreamInfo]:
        """Get stream metadata."""
        return self._stream_info

    def close(self):
        """Close the stream and cleanup resources."""
        self._running = False
        self._connected = False

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3)

        if self._client:
            self._client.close()

        if self._decoder:
            self._decoder.flush()

        # Drain the queue
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

        logger.info("DVRIP stream closed")

    def _reader_loop(self):
        """Background thread that reads and decodes video packets."""
        logger.info("Reader thread started")

        # Read raw data from the data socket and parse it
        read_buf = bytearray()
        decoder_initialized = False
        consecutive_reconnects = 0
        MAX_RECONNECTS = 10
        RECONNECT_DELAY = 3  # seconds

        while self._running:
            try:
                # Read a chunk from the data socket
                self._data_sock.settimeout(1.0)

                # Read the DVRIP packet header (20 bytes)
                header = self._read_exact(DVRIP_HEADER_SIZE)
                if header[0] != DVRIP_MAGIC:
                    logger.warning(f"Bad magic: 0x{header[0]:02X}")
                    continue

                length = struct.unpack_from("<I", header, 16)[0]
                payload = b""
                if length > 0:
                    payload = self._read_exact(length)

                consecutive_reconnects = 0  # reset on successful read

                # Feed to parser
                frames = self._parser.feed(payload)

                for frame_type, annex_b_data in frames:
                    # Initialize decoder on first keyframe
                    if not decoder_initialized:
                        if self._decoder.initialize(annex_b_data):
                            decoder_initialized = True
                            logger.info(
                                f"Decoder ready: codec={self._parser.codec} "
                                f"VPS={'yes' if self._parser.vps else 'no'} "
                                f"SPS={'yes' if self._parser.sps else 'no'} "
                                f"PPS={'yes' if self._parser.pps else 'no'}"
                            )
                        else:
                            continue

                    # Decode frame
                    decoded = self._decoder.decode(annex_b_data)

                    for img, pts in decoded:
                        self._frame_number += 1
                        self._last_frame_time = time.time()

                        vf = VideoFrame(
                            image=img,
                            pts=pts,
                            timestamp=self._last_frame_time,
                            frame_type=frame_type,
                            frame_number=self._frame_number,
                        )

                        # Enqueue (drop oldest if full)
                        try:
                            self._frame_queue.put_nowait((True, img))
                        except queue.Full:
                            try:
                                self._frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                            self._frame_queue.put_nowait((True, img))

            except socket.timeout:
                continue
            except ConnectionError as e:
                if not self._running:
                    break
                logger.warning(f"Connection lost: {e}")
                consecutive_reconnects += 1
                if consecutive_reconnects > MAX_RECONNECTS:
                    logger.error(
                        f"Failed to reconnect after {MAX_RECONNECTS} attempts"
                    )
                    self._connected = False
                    break
                logger.info(
                    f"Reconnecting in {RECONNECT_DELAY}s "
                    f"(attempt {consecutive_reconnects}/{MAX_RECONNECTS})..."
                )
                time.sleep(RECONNECT_DELAY)
                if not self._running:
                    break
                if self._reconnect():
                    decoder_initialized = False
                    read_buf = bytearray()
                    logger.info("Reconnected successfully")
                else:
                    logger.error("Reconnect failed")
                    self._connected = False
                    break
            except Exception as e:
                if self._running:
                    logger.error(f"Reader error: {e}")
                continue

        logger.info("Reader thread stopped")

    def _reconnect(self) -> bool:
        """Reconnect after a connection loss. Returns True on success."""
        try:
            logger.info("Closing old connection...")
            if self._client:
                self._client.close()
            if self._data_sock:
                try:
                    self._data_sock.close()
                except Exception:
                    pass
                self._data_sock = None

            time.sleep(1)

            logger.info("Reconnecting to NVR...")
            self._client = TVSDVRIPClient(self.host, self.port)
            self._stream_info = self._client.connect_and_login(
                self.username, self.password
            )
            self._data_sock = self._client.start_monitor(
                self._channel, self._subtype
            )
            self._client.start_alive()
            self._parser = TVSStreamParser()
            self._decoder = H265Decoder()
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            return False

    def _read_exact(self, n: int, max_consecutive_timeouts: int = 10) -> bytes:
        """Read exactly n bytes from the data socket.

        Raises ConnectionError if no data arrives after max_consecutive_timeouts
        (each 1s due to socket timeout), preventing infinite spin.
        """
        buf = bytearray()
        consecutive_timeouts = 0
        while len(buf) < n:
            try:
                chunk = self._data_sock.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("Socket closed")
                buf.extend(chunk)
                consecutive_timeouts = 0
            except socket.timeout:
                consecutive_timeouts += 1
                if not self._running:
                    raise ConnectionError("Reader stopped")
                if consecutive_timeouts >= max_consecutive_timeouts:
                    raise ConnectionError(
                        f"Read timeout: no data for {max_consecutive_timeouts}s"
                    )
                continue
        return bytes(buf)
