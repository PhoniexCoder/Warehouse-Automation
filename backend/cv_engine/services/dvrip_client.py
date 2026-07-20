"""Direct DVRIP/Sofia binary protocol client for DVRIP-compatible NVRs.

Based on the actual go2rtc DVRIP implementation:
https://github.com/AlexxIT/go2rtc/blob/master/pkg/dvrip/client.go

Protocol details:
- Login: JSON payload with sofia_hash password (cmd=1000)
- OPMonitor: JSON payload with SessionID (Claim=1413, Start=1410)
- KeepAlive: cmd=1006
- Logout: cmd=1006
- Frame packets: multi-chunk reassembly with 20-byte DVRIP headers
- Video data pushed by server after OPMonitor Start
"""

import json
import logging
import socket
import struct
import threading
import time
from typing import Callable, Optional

from cv_engine.services.dvrip_frames import (
    TYPE_AUDIO,
    TYPE_I_FRAME,
    TYPE_INFO,
    TYPE_JPEG,
    TYPE_P_FRAME,
    calculate_packet_size,
    extract_video_data,
    frame_type_name,
    is_frame_header,
    sofia_hash,
)

LOGGER = logging.getLogger(__name__)

# ─── DVRIP Command IDs (from go2rtc pkg/dvrip/client.go) ──────────────────
CMD_LOGIN = 1000           # 0x03E8 — login
CMD_LOGOUT = 1006          # 0x03EE — logout / keepalive
CMD_KEEPALIVE = 1006       # 0x03EE — same as logout (NVR replies with alive status)
CMD_OPMONITOR_CLAIM = 1413 # 0x0585 — OPMonitor Claim
CMD_OPMONITOR_START = 1410 # 0x0582 — OPMonitor Start

# ─── Defaults ───────────────────────────────────────────────────────────────
DEFAULT_PORT = 34567
DEFAULT_TIMEOUT = 10.0
KEEPALIVE_INTERVAL = 15.0
FRAME_READ_TIMEOUT = 10.0
MAX_CHUNK_SIZE = 1024 * 1024  # 1MB max per DVRIP chunk


class DVRIPConnectionError(Exception):
    pass


class DVRIPAuthError(Exception):
    pass


class DVRIPTimeout(Exception):
    pass


class DVRIPClient:
    """Direct DVRIP binary protocol client for a single camera channel.

    Protocol follows go2rtc's implementation exactly:
    1. TCP connect to host:port (default 34567)
    2. Login with JSON payload (cmd=1000)
    3. OPMonitor Claim (cmd=1413) — JSON with SessionID
    4. OPMonitor Start (cmd=1410) — JSON with SessionID
    5. Server pushes video data chunks (cmd=1404 typically)
    6. KeepAlive every 15s (cmd=1006)

    Usage:
        client = DVRIPClient("192.168.1.35", 34567, "admin", "admin")
        client.connect(channel=0)
        for frame_type, frame_data in client.iter_packets():
            # frame_data is raw video/audio bytes
            ...
        client.close()
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        username: str = "",
        password: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout

        self._sock: Optional[socket.socket] = None
        self._session: int = 0
        self._seq: int = 0
        self._lock = threading.Lock()
        self._connected = False
        self._channel: int = 0
        self._stop = threading.Event()
        self._keepalive_thread: Optional[threading.Thread] = None

        # Read buffer for chunk reassembly (like go2rtc's c.buf)
        self._read_buf: bytearray = bytearray()

        # Device info from login response (NetWork.NetCommon)
        self.channel_count: int = 16
        self.max_connections: int = 8
        self.device_type: int = 0
        self.device_name: str = ""
        self.firmware_version: str = ""
        self.login_response: dict = {}

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, channel: int = 0, stream_type: str = "Main") -> bool:
        """Connect to NVR, authenticate, and start OPMonitor.

        Args:
            channel: Camera channel number (0-based)
            stream_type: "Main" for primary stream, "Extra1" for sub-stream

        Returns True on success, raises DVRIPConnectionError on failure.
        """
        self._channel = channel
        self._stream_type = stream_type
        self._stop.clear()
        self._read_buf = bytearray()

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
        except (socket.error, OSError) as e:
            raise DVRIPConnectionError(
                f"TCP connect failed to {self.host}:{self.port}: {e}"
            ) from e

        self._connected = True
        LOGGER.info(
            "[%s:%d] TCP connected (channel=%d)", self.host, self.port, channel
        )

        try:
            self._login()
            self._opmonitor_claim()
            self._opmonitor_start()
            self._start_keepalive()
        except Exception:
            self.close()
            raise

        return True

    def close(self) -> None:
        """Cleanly close the connection."""
        self._stop.set()
        self._connected = False

        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=3)
            self._keepalive_thread = None

        if self._sock:
            try:
                # Send logout (same cmd as keepalive but acts as disconnect)
                self._send_command(CMD_LOGOUT, b"")
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        LOGGER.info("[%s:%d] Connection closed", self.host, self.port)

    def probe_channel(self, channel: int, stream_type: str = "Main", timeout: float = 5.0) -> bool:
        """Probe a single channel to check if it has active video.

        Connects, logs in, starts OPMonitor on the given channel, and waits
        for at least one video packet. Returns True if video arrives.

        This reuses the current connection if already logged in (same session).
        If not connected, creates a new temporary connection.
        """
        was_connected = self._connected

        if not was_connected:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(timeout)
            try:
                self._sock.connect((self.host, self.port))
            except (socket.error, OSError):
                return False
            self._connected = True
            try:
                self._login()
            except Exception:
                self.close()
                return False

        # Save state for restore
        old_channel = self._channel
        old_stream_type = getattr(self, "_stream_type", "Main")
        old_buf = self._read_buf

        try:
            self._channel = channel
            self._stream_type = stream_type
            self._read_buf = bytearray()

            self._opmonitor_claim()
            self._opmonitor_start()

            # Wait for first video packet
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    ptype, payload, meta = self._read_packet()
                    if ptype in (TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG):
                        LOGGER.debug(
                            "[%s:%d] Channel %d active (got %s)",
                            self.host, self.port, channel, frame_type_name(ptype),
                        )
                        return True
                except (socket.timeout, OSError, DVRIPTimeout):
                    break

            LOGGER.debug("[%s:%d] Channel %d no video", self.host, self.port, channel)
            return False
        finally:
            # Restore state
            self._channel = old_channel
            self._stream_type = old_stream_type
            self._read_buf = old_buf

            if not was_connected:
                self.close()

    def discover_channels(
        self,
        channel_count: Optional[int] = None,
        probe_timeout: float = 5.0,
        on_progress: Optional[Callable[[int, int, bool], None]] = None,
    ) -> list[dict]:
        """Discover active channels by probing each one sequentially.

        Args:
            channel_count: Number of channels to probe (uses login info if None)
            probe_timeout: Seconds to wait for video on each channel
            on_progress: Callback(channel, total, active) for progress updates

        Returns list of dicts: [{"channel": 0, "active": True}, ...]
        """
        if channel_count is None:
            channel_count = self.channel_count

        active = []
        for ch in range(channel_count):
            is_active = self.probe_channel(ch, timeout=probe_timeout)
            active.append({"channel": ch, "active": is_active})
            if on_progress:
                on_progress(ch, channel_count, is_active)

        LOGGER.info(
            "[%s:%d] Discovered %d/%d active channels",
            self.host, self.port,
            sum(1 for c in active if c["active"]),
            channel_count,
        )
        return active

    @staticmethod
    def discover_broadcast(timeout: float = 3.0) -> list[dict]:
        """UDP broadcast discovery on port 34569 (like go2rtc).

        Sends a DVRIP probe packet to 239.255.255.250:34569 and collects
        responses from NVRs on the local network.

        Returns list of dicts with device info:
        [{"host": "192.168.1.35", "name": "TVS-XXXX", "channel_count": 10, ...}]
        """
        import select

        probe_packet = bytes.fromhex("ff00000000000000000000000000fa0500000000")
        multicast_addr = ("239.255.255.250", 34569)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)
            sock.bind(("", 34569))

            # Join multicast group
            mreq = struct.pack(
                "4s4s",
                socket.inet_aton("239.255.255.250"),
                socket.inet_aton("0.0.0.0"),
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except (OSError, socket.error) as e:
            LOGGER.warning("UDP discovery socket setup failed: %s", e)
            return []

        # Send probe 3 times (like go2rtc)
        for _ in range(3):
            try:
                sock.sendto(probe_packet, multicast_addr)
            except OSError:
                pass
            time.sleep(0.1)

        devices = []
        seen_ips = set()
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            ready, _, _ = select.select([sock], [], [], min(remaining, 0.5))
            if not ready:
                continue

            try:
                data, addr = sock.recvfrom(4096)
            except (OSError, socket.error):
                break

            ip = addr[0]
            if ip in seen_ips or len(data) <= 21:
                continue
            seen_ips.add(ip)

            # Parse JSON after 20-byte header
            try:
                json_str = data[20:].decode("utf-8", errors="ignore").rstrip("\x00\n")
                msg = json.loads(json_str)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            net_common = msg.get("NetWork.NetCommon", {})
            if not net_common:
                continue

            # Convert hex IP to decimal if needed
            host_ip = net_common.get("HostIP", ip)
            if host_ip.startswith("0x"):
                try:
                    hex_bytes = bytes.fromhex(host_ip[2:])
                    host_ip = f"{hex_bytes[3]}.{hex_bytes[2]}.{hex_bytes[1]}.{hex_bytes[0]}"
                except (ValueError, IndexError):
                    host_ip = ip

            devices.append({
                "host": host_ip,
                "name": net_common.get("HostName", f"NVR ({host_ip})"),
                "channel_count": int(net_common.get("ChannelNum", 0)),
                "max_connections": int(net_common.get("TCPMaxConn", 8)),
                "device_type": int(net_common.get("DeviceType", 0)),
                "version": net_common.get("Version", ""),
                "mac": net_common.get("MAC", ""),
                "http_port": int(net_common.get("HttpPort", 80)),
            })

        try:
            sock.close()
        except OSError:
            pass

        LOGGER.info("UDP discovery found %d device(s)", len(devices))
        return devices

    def iter_packets(
        self, on_frame: Optional[Callable[[int, bytes, dict], None]] = None
    ):
        """Yield (packet_type, payload_bytes, metadata) tuples.

        packet_type is one of TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG, etc.
        payload_bytes is the raw video/audio data.
        """
        while self._connected and not self._stop.is_set():
            try:
                ptype, payload, meta = self._read_packet()
                if payload:
                    if on_frame:
                        on_frame(ptype, payload, meta)
                    yield ptype, payload, meta
            except socket.timeout:
                continue
            except (DVRIPTimeout, OSError) as e:
                LOGGER.warning(
                    "[%s:%d] Packet read error: %s", self.host, self.port, e
                )
                break
            except Exception as e:
                LOGGER.exception(
                    "[%s:%d] Unexpected error in packet iterator: %s",
                    self.host,
                    self.port,
                    e,
                )
                break

    # ─── Protocol Methods ────────────────────────────────────────────────

    def _login(self) -> None:
        """Perform JSON-based DVRIP login.

        Login payload (from go2rtc):
        {"EncryptType":"MD5","LoginType":"DVRIP-Web","PassWord":"<sofia_hash>","UserName":"<user>"}\\n\\x00
        """
        hashed = sofia_hash(self.password)
        login_data = {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": hashed,
            "UserName": self.username,
        }
        payload = json.dumps(login_data, separators=(",", ":")) + "\n\x00"

        LOGGER.debug(
            "[%s:%d] Sending login (username=%s, sofia_hash=%s)",
            self.host,
            self.port,
            self.username,
            hashed,
        )

        resp = self._send_and_receive_json(CMD_LOGIN, payload.encode("utf-8"))
        self.login_response = resp

        ret = resp.get("Ret", -1)
        if ret in (100, 515):
            # Extract device info from login response
            net_common = resp.get("NetWork.NetCommon", {})
            if net_common:
                self.channel_count = int(net_common.get("ChannelNum", 16))
                self.max_connections = int(net_common.get("TCPMaxConn", 8))
                self.device_type = int(net_common.get("DeviceType", 0))
                self.device_name = str(net_common.get("HostName", ""))
                self.firmware_version = str(net_common.get("Version", ""))
            LOGGER.info(
                "[%s:%d] Login OK (Ret=%s) channels=%d max_conn=%d device=%s",
                self.host, self.port, ret,
                self.channel_count, self.max_connections, self.device_name,
            )
        else:
            ret_name = {
                205: "LOCKOUT (account locked)",
                403: "WRONG_PASSWORD",
                404: "USER_NOT_FOUND",
                405: "USER_DISABLE",
                500: "NOT_FOUND",
                501: "TIMEOUT",
                502: "NOT_SUPPORT",
            }.get(int(ret), f"UNKNOWN({ret})")
            raise DVRIPAuthError(
                f"Login failed: Ret={ret} ({ret_name}). "
                f"Full response: {resp}"
            )

    def _opmonitor_claim(self) -> None:
        """Send OPMonitor Claim (cmd=1413).

        Format from go2rtc:
        {"Name":"OPMonitor","SessionID":"0x%08X","OPMonitor":{"Action":"Claim","Parameter":{"Channel":N,"CombinMode":"NONE","StreamType":"Main","TransMode":"TCP"}}}
        """
        session_hex = f"0x{self._session:08X}"
        claim_data = {
            "Name": "OPMonitor",
            "SessionID": session_hex,
            "OPMonitor": {
                "Action": "Claim",
                "Parameter": {
                    "Channel": self._channel,
                    "CombinMode": "NONE",
                    "StreamType": self._stream_type,
                    "TransMode": "TCP",
                },
            },
        }
        payload = json.dumps(claim_data, separators=(",", ":")) + "\n\x00"

        resp = self._send_and_receive_json(
            CMD_OPMONITOR_CLAIM, payload.encode("utf-8")
        )

        ret = resp.get("Ret", -1)
        if ret in (100, 515):
            LOGGER.info(
                "[%s:%d] OPMonitor Claim OK (Ret=%s)",
                self.host,
                self.port,
                ret,
            )
        else:
            LOGGER.warning(
                "[%s:%d] OPMonitor Claim failed (Ret=%s): %s",
                self.host,
                self.port,
                ret,
                resp,
            )

    def _opmonitor_start(self) -> None:
        """Send OPMonitor Start (cmd=1410).

        Some NVRs respond with JSON, others immediately start pushing video data.
        We handle both cases.
        """
        session_hex = f"0x{self._session:08X}"
        start_data = {
            "Name": "OPMonitor",
            "SessionID": session_hex,
            "OPMonitor": {
                "Action": "Start",
                "Parameter": {
                    "Channel": self._channel,
                    "CombinMode": "NONE",
                    "StreamType": self._stream_type,
                    "TransMode": "TCP",
                },
            },
        }
        payload = json.dumps(start_data, separators=(",", ":")) + "\n\x00"

        # OPMonitor Start may return JSON or immediately push video data.
        # Read the first chunk and check if it's JSON or frame data.
        self._send_command(CMD_OPMONITOR_START, payload.encode("utf-8"))

        old_timeout = self._sock.gettimeout()
        self._sock.settimeout(5.0)
        try:
            chunk = self._read_chunk()
            if chunk is not None and len(chunk) > 0:
                # Check if it's a frame header (binary video data)
                if is_frame_header(chunk):
                    # Video data arrived immediately — stash it in read buffer
                    self._read_buf = bytearray(chunk)
                    LOGGER.info(
                        "[%s:%d] OPMonitor Start OK — streaming on channel %d (video data received)",
                        self.host,
                        self.port,
                        self._channel,
                    )
                    return

                # Try parsing as JSON response
                try:
                    json_data = chunk
                    if len(json_data) > 2 and json_data[-2:] in (b"\n\x00", b"\x00\x00"):
                        json_data = json_data[:-2]
                    elif len(json_data) > 1 and json_data[-1:] == b"\x00":
                        json_data = json_data[:-1]

                    resp = json.loads(json_data)
                    ret = resp.get("Ret", -1)
                    if ret in (100, 515):
                        LOGGER.info(
                            "[%s:%d] OPMonitor Start OK — streaming on channel %d",
                            self.host,
                            self.port,
                            self._channel,
                        )
                    else:
                        LOGGER.warning(
                            "[%s:%d] OPMonitor Start response (Ret=%s): %s",
                            self.host,
                            self.port,
                            ret,
                            resp,
                        )
                except (json.JSONDecodeError, ValueError):
                    # Not JSON and not a frame header — stash and continue
                    self._read_buf = bytearray(chunk)
                    LOGGER.info(
                        "[%s:%d] OPMonitor Start OK — streaming on channel %d (non-JSON response stashed)",
                        self.host,
                        self.port,
                        self._channel,
                    )
            else:
                LOGGER.info(
                    "[%s:%d] OPMonitor Start sent (no response)",
                    self.host,
                    self.port,
                )
        finally:
            if self._sock:
                self._sock.settimeout(old_timeout)

    def _start_keepalive(self) -> None:
        """Start background keepalive thread (cmd=1006)."""

        def _keepalive_loop():
            while self._connected and not self._stop.is_set():
                self._stop.wait(KEEPALIVE_INTERVAL)
                if self._connected and not self._stop.is_set():
                    try:
                        # go2rtc doesn't send keepalive payload, just the command
                        self._send_command(CMD_KEEPALIVE, b"")
                    except Exception as e:
                        LOGGER.warning(
                            "[%s:%d] Keepalive failed: %s",
                            self.host,
                            self.port,
                            e,
                        )

        self._keepalive_thread = threading.Thread(
            target=_keepalive_loop,
            daemon=True,
            name=f"dvrip-keepalive-{self.host}",
        )
        self._keepalive_thread.start()

    # ─── Packet Reading (matches go2rtc ReadPacket) ──────────────────────

    def _read_packet(self) -> tuple[int, bytes, dict]:
        """Read the next complete DVRIP frame packet.

        Matches go2rtc's ReadPacket method:
        1. Read chunks (20-byte DVRIP header + payload) into buffer
        2. Check for 00 00 01 <type> frame signature
        3. Calculate total packet size based on type
        4. Read more chunks if needed until complete
        5. Return (type, payload_bytes, metadata)

        Returns (ptype, payload, meta).
        """
        while self._connected and not self._stop.is_set():
            # Need at least 4 bytes to check frame signature
            while len(self._read_buf) < 4:
                chunk = self._read_chunk()
                if chunk is None:
                    raise DVRIPTimeout("Connection closed during chunk read")
                self._read_buf.extend(chunk)

            # Check frame signature: 00 00 01 <type>
            if not is_frame_header(self._read_buf):
                # Skip garbage bytes until we find a frame header
                # (might happen during initial handshake response or error recovery)
                skip = 1
                for i in range(1, min(len(self._read_buf), 16)):
                    if is_frame_header(self._read_buf[i:]):
                        skip = i
                        break
                LOGGER.debug(
                    "[%s:%d] Skipping %d bytes (not frame header): %s",
                    self.host,
                    self.port,
                    skip,
                    self._read_buf[:min(16, len(self._read_buf))].hex(),
                )
                self._read_buf = self._read_buf[skip:]
                continue

            # Calculate total packet size
            total_size = calculate_packet_size(self._read_buf)
            if total_size < 0:
                LOGGER.warning(
                    "[%s:%d] Cannot calculate packet size from: %s",
                    self.host,
                    self.port,
                    self._read_buf[:16].hex(),
                )
                self._read_buf = self._read_buf[4:]
                continue

            # Read more chunks until we have the full packet
            while len(self._read_buf) < total_size:
                chunk = self._read_chunk()
                if chunk is None:
                    raise DVRIPTimeout("Connection closed during packet read")
                self._read_buf.extend(chunk)

            # Extract the complete packet
            packet = bytes(self._read_buf[:total_size])
            self._read_buf = self._read_buf[total_size:]

            ptype = packet[3]
            meta = self._parse_packet_meta(packet)

            # Extract payload (video/audio data)
            if ptype == TYPE_I_FRAME:
                payload = packet[16:] if len(packet) > 16 else b""
            elif ptype == TYPE_P_FRAME:
                payload = packet[8:] if len(packet) > 8 else b""
            elif ptype == TYPE_JPEG:
                payload = packet[16:] if len(packet) > 16 else b""
            elif ptype in (TYPE_AUDIO, TYPE_INFO):
                payload = packet[8:] if len(packet) > 8 else b""
            else:
                payload = packet[4:] if len(packet) > 4 else b""

            if not payload:
                continue  # Skip empty packets

            return ptype, payload, meta

        raise DVRIPTimeout("Connection stopped")

    def _read_chunk(self) -> Optional[bytes]:
        """Read a single DVRIP chunk's PAYLOAD (after 20-byte header).

        Matches go2rtc's ReadChunk method — returns only the payload portion
        that gets appended to the reassembly buffer.
        """
        if self._sock is None:
            return None

        old_timeout = self._sock.gettimeout()
        self._sock.settimeout(FRAME_READ_TIMEOUT)

        try:
            # Read 20-byte DVRIP header
            header = self._recv_exact(20)
            if not header or len(header) < 20:
                return None

            # Validate magic byte
            if header[0] != 0xFF:
                LOGGER.warning(
                    "[%s:%d] Invalid chunk magic: 0x%02X",
                    self.host,
                    self.port,
                    header[0],
                )
                return None

            # Update session from response header
            self._session = struct.unpack_from("<I", header, 4)[0]

            # Read payload size (bytes 16-19, LE uint32)
            payload_size = struct.unpack_from("<I", header, 16)[0]

            if payload_size > MAX_CHUNK_SIZE:
                LOGGER.warning(
                    "[%s:%d] Chunk payload too large: %d bytes",
                    self.host,
                    self.port,
                    payload_size,
                )
                return None

            payload = self._recv_exact(payload_size) if payload_size > 0 else b""
            if payload_size > 0 and not payload:
                return None

            return payload  # Return payload only (not header)

        except socket.timeout:
            return None
        except (socket.error, OSError):
            self._connected = False
            return None
        finally:
            if self._sock:
                self._sock.settimeout(old_timeout)

    def _parse_packet_meta(self, packet: bytes) -> dict:
        """Parse metadata from a complete frame packet."""
        if len(packet) < 4:
            return {"frame_type": "unknown"}

        ptype = packet[3]
        meta = {
            "frame_type": frame_type_name(ptype),
            "type_byte": ptype,
            "total_length": len(packet),
        }

        if ptype == TYPE_I_FRAME and len(packet) >= 16:
            # I-frame sub-header: 00 00 01 FC codec fps w8 h8 timestamp(4) length(4)
            codec = packet[4]
            fps = packet[5]
            w8 = packet[6]
            h8 = packet[7]
            meta.update({
                "codec": codec,
                "fps": fps,
                "width": w8 * 8,
                "height": h8 * 8,
            })

        return meta

    # ─── Low-Level Send/Receive ──────────────────────────────────────────

    def _send_and_receive_json(
        self, cmd: int, payload: bytes, timeout: float = 5.0
    ) -> dict:
        """Send a command and parse the JSON response.

        Returns the parsed JSON dict. Raises on timeout or non-JSON response.
        """
        old_timeout = self._sock.gettimeout()
        self._sock.settimeout(timeout)

        try:
            self._send_command(cmd, payload)

            # Read response chunk payload (header already stripped by _read_chunk)
            json_data = self._read_chunk()
            if json_data is None:
                raise DVRIPTimeout("No response chunk received")

            # Strip trailing null/newline bytes
            if len(json_data) > 2 and json_data[-2:] in (b"\n\x00", b"\x00\x00"):
                json_data = json_data[:-2]
            elif len(json_data) > 1 and json_data[-1:] == b"\x00":
                json_data = json_data[:-1]

            try:
                return json.loads(json_data)
            except json.JSONDecodeError:
                LOGGER.warning(
                    "[%s:%d] Non-JSON response to cmd %d: %s",
                    self.host,
                    self.port,
                    cmd,
                    json_data[:100],
                )
                return {"Ret": -1, "raw": json_data.decode("utf-8", errors="replace")}

        finally:
            if self._sock:
                self._sock.settimeout(old_timeout)

    def _send_command(self, cmd: int, payload: bytes) -> int:
        """Send a DVRIP command packet. Returns the sequence number used.

        Lock protects both seq increment AND sendall() to prevent
        keepalive thread and main thread from interleaving bytes on the socket.
        """
        with self._lock:
            seq = self._seq
            self._seq += 1

            # 20-byte DVRIP header (matches go2rtc's WriteCmd exactly)
            header = bytearray(20)
            header[0] = 0xFF  # magic
            # bytes 1-3: unused (direction=0, padding=0)
            struct.pack_into("<I", header, 4, self._session)  # session
            struct.pack_into("<I", header, 8, seq)  # sequence
            # bytes 12-13: unused (0)
            struct.pack_into("<H", header, 14, cmd)  # command
            struct.pack_into("<I", header, 16, len(payload))  # payload_size

            try:
                self._sock.sendall(bytes(header) + payload)
            except (socket.error, OSError) as e:
                self._connected = False
                raise DVRIPConnectionError(f"Send failed: {e}") from e

        return seq

    def _recv_exact(self, n: int) -> bytes:
        """Read exactly n bytes from the socket."""
        data = bytearray()
        while len(data) < n:
            if self._stop.is_set():
                return bytes(data)
            try:
                chunk = self._sock.recv(n - len(data))
                if not chunk:
                    return bytes(data)
                data.extend(chunk)
            except socket.timeout:
                continue
            except (socket.error, OSError):
                self._connected = False
                return bytes(data)
        return bytes(data)
