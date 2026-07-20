import socket
import asyncio
import json
import logging
import re
import struct
from typing import List, Dict, Any, Optional

LOGGER = logging.getLogger(__name__)

# WS-Discovery Probe Message (ONVIF Probe for Network Video Transmitters)
WS_DISCOVERY_PROBE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Envelope xmlns:dn="http://www.onvif.org/ver10/network/wsdl" xmlns="http://www.w3.org/2003/05/soap-envelope">'
    '<Header>'
        '<MessageID>uuid:84192f5a-480c-4b3b-b27b-e774d2bf32d1</MessageID>'
        '<To>urn:schemas-xmlsoap-org:node:rules:discovery:2006</To>'
        '<Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</Action>'
    '</Header>'
    '<Body>'
        '<Probe>'
            '<Types>dn:NetworkVideoTransmitter</Types>'
        '</Probe>'
    '</Body>'
    '</Envelope>'
)

class NvrDiscoveryService:
    @staticmethod
    def get_local_ip_prefix() -> str:
        """Finds the local network IP interface and gets the /24 prefix."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = "192.168.1.1"
        finally:
            s.close()
        parts = ip.split(".")
        return ".".join(parts[:3]) + "."

    @classmethod
    async def scan_port(cls, ip: str, port: int, timeout: float = 0.25) -> str | None:
        """Asynchronously checks if a TCP port is open."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return ip
        except Exception:
            return None

    @classmethod
    async def discover_devices(cls) -> List[Dict[str, Any]]:
        """Discovers NVRs and cameras via WS-Discovery (UDP Multicast) and falls back to subnet scanning."""
        devices = []
        seen_ips = set()

        # 1. Try WS-Discovery (ONVIF Probe)
        try:
            loop = asyncio.get_running_loop()
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: WSDiscoveryProtocol(devices, seen_ips),
                family=socket.AF_INET,
                remote_addr=("239.255.255.250", 3702)
            )
            # Send probe XML
            transport.sendto(WS_DISCOVERY_PROBE.encode("utf-8"))
            # Wait for responses
            await asyncio.sleep(1.0)
            transport.close()
        except Exception as e:
            LOGGER.warning("WS-Discovery multicast failed: %s. Falling back to subnet scan.", e)

        # 2. Subnet Port Scan (Fallback and Supplement)
        prefix = cls.get_local_ip_prefix()
        LOGGER.info("Starting rapid port scan on subnet: %s0/24", prefix)

        scan_tasks = []
        # Scan both RTSP (554) and DVRIP (34567) ports
        for i in range(1, 255):
            ip = f"{prefix}{i}"
            if ip in seen_ips:
                continue
            scan_tasks.append(cls._scan_device_ports(ip))

        results = await asyncio.gather(*scan_tasks)
        for ip, has_rtsp, has_dvrip in results:
            if ip:
                seen_ips.add(ip)
                protocols = []
                if has_rtsp:
                    protocols.append("rtsp")
                if has_dvrip:
                    protocols.append("dvrip")
                devices.append({
                    "ip": ip,
                    "name": f"Surveillance Node ({ip})",
                    "type": "NVR / Camera",
                    "discovery_method": "subnet_scan",
                    "protocols": protocols,
                    "has_dvrip": has_dvrip,
                })

        return devices

    @classmethod
    async def _scan_device_ports(cls, ip: str, timeout: float = 0.25) -> tuple:
        """Scan RTSP and DVRIP ports on a single IP. Returns (ip, has_rtsp, has_dvrip)."""
        async def check_port(port):
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=timeout
                )
                writer.close()
                await writer.wait_closed()
                return True
            except Exception:
                return False

        rtsp_task = check_port(554)
        dvrip_task = check_port(34567)
        has_rtsp, has_dvrip = await asyncio.gather(rtsp_task, dvrip_task)

        if has_rtsp or has_dvrip:
            return (ip, has_rtsp, has_dvrip)
        return (None, False, False)

    @classmethod
    async def verify_rtsp_channel(cls, ip: str, port: int, path: str, timeout: float = 1.0) -> bool:
        """Sends an RTSP OPTIONS request to verify if a channel/stream exists."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
            # Create a simple RTSP OPTIONS packet
            req = (
                f"OPTIONS rtsp://{ip}:{port}/{path} RTSP/1.0\r\n"
                f"CSeq: 1\r\n"
                f"User-Agent: VMS-Discovery/1.0\r\n\r\n"
            )
            writer.write(req.encode("utf-8"))
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(1024), timeout=timeout)
            writer.close()
            await writer.wait_closed()

            resp_str = resp.decode("utf-8", errors="ignore")
            # If NVR replies with RTSP/1.0 and is not a 404, the channel exists
            if "RTSP/1.0" in resp_str and "404" not in resp_str:
                return True
        except Exception:
            pass
        return False

    @classmethod
    async def scan_active_channels(cls, ip: str, username: str, password: str) -> List[Dict[str, Any]]:
        """Checks channels 1 to 16 on the NVR and returns active ones.
        
        Detects whether the NVR supports DVRIP (port 34567) and generates
        the appropriate stream URL format.
        """
        # Check if DVRIP port is open
        has_dvrip = False
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 34567), timeout=0.5
            )
            writer.close()
            await writer.wait_closed()
            has_dvrip = True
        except Exception:
            pass

        if has_dvrip:
            return cls._scan_dvrip_channels(ip, username, password)
        return await cls._scan_rtsp_channels(ip, username, password)

    @classmethod
    def _scan_dvrip_channels(cls, ip: str, username: str, password: str) -> List[Dict[str, Any]]:
        """DVRIP channel discovery: login to get device info, then probe channels.

        Uses the DVRIP protocol to:
        1. Connect and login to get ChannelNum from the response
        2. Probe each channel by starting OPMonitor and checking for video
        """
        channels = []

        # Step 1: Login to get channel count
        channel_count = cls._dvrip_get_channel_count(ip, 34567, username, password)
        if channel_count is None:
            LOGGER.warning("DVRIP: Could not get channel count from %s, defaulting to 16", ip)
            channel_count = 16

        # Step 2: Probe each channel for active video
        for ch in range(channel_count):
            is_active = cls._dvrip_probe_channel(ip, 34567, username, password, ch)
            stream_url = f"dvrip://{username}:{password}@{ip}:34567/{ch}"
            channels.append({
                "channel_id": ch,
                "display_name": f"Channel {ch}" + (" (active)" if is_active else ""),
                "stream_url": stream_url,
                "protocol": "dvrip",
                "active": is_active,
            })

        active_count = sum(1 for c in channels if c.get("active"))
        LOGGER.info("DVRIP %s: %d/%d channels active", ip, active_count, channel_count)
        return channels

    @classmethod
    def _dvrip_get_channel_count(cls, ip: str, port: int, username: str, password: str, timeout: float = 5.0) -> Optional[int]:
        """Connect via DVRIP, login, and extract ChannelNum from response."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            LOGGER.info("DVRIP connecting to %s:%d (timeout=%.1fs)", ip, port, timeout)
            sock.connect((ip, port))
            LOGGER.info("DVRIP TCP connected to %s:%d", ip, port)
        except (socket.error, OSError) as e:
            LOGGER.warning("DVRIP TCP connect to %s:%d FAILED: %s", ip, port, e)
            return None

        try:
            hashed = cls._sofia_hash(password)
            LOGGER.info("DVRIP sofia_hash(%s) = %s", password, hashed)

            login_data = json.dumps({
                "EncryptType": "MD5",
                "LoginType": "DVRIP-Web",
                "PassWord": hashed,
                "UserName": username,
            }, separators=(",", ":")) + "\n\x00"

            payload = login_data.encode("utf-8")
            header = bytearray(20)
            header[0] = 0xFF
            struct.pack_into("<I", header, 16, len(payload))
            struct.pack_into("<H", header, 14, 1000)
            sock.sendall(bytes(header) + payload)
            LOGGER.info("DVRIP login sent to %s:%d (user=%s)", ip, port, username)

            resp_header = sock.recv(20)
            if len(resp_header) < 20:
                LOGGER.warning("DVRIP response from %s:%d truncated (%d bytes)", ip, port, len(resp_header))
                return None

            resp_size = struct.unpack_from("<I", resp_header, 16)[0]
            resp_cmd = struct.unpack_from("<H", resp_header, 14)[0]
            LOGGER.info("DVRIP response header from %s:%d: cmd=%d, size=%d", ip, port, resp_cmd, resp_size)
            if resp_size > 1048576:
                LOGGER.warning("DVRIP response too large: %d bytes", resp_size)
                return None

            resp_data = b""
            while len(resp_data) < resp_size:
                chunk = sock.recv(min(resp_size - len(resp_data), 65536))
                if not chunk:
                    break
                resp_data += chunk

            resp_json = resp_data.decode("utf-8", errors="ignore").rstrip("\x00\n")
            resp = json.loads(resp_json)
            LOGGER.info("DVRIP login response from %s:%d: Ret=%s, SessionID=%s",
                        ip, port, resp.get("Ret"), resp.get("SessionID"))

            net_common = resp.get("NetWork.NetCommon", {})
            channel_count = int(net_common.get("ChannelNum", 0))
            LOGGER.info("DVRIP channel count from %s:%d = %d", ip, port, channel_count)
            return channel_count if channel_count > 0 else None

        except Exception as e:
            LOGGER.warning("DVRIP login to %s:%d failed: %s", ip, port, e, exc_info=True)
            return None
        finally:
            try:
                sock.close()
            except OSError:
                pass

    @classmethod
    def _dvrip_probe_channel(cls, ip: str, port: int, username: str, password: str, channel: int, timeout: float = 4.0) -> bool:
        """Probe a single DVRIP channel for active video.

        Connects, logs in, sends OPMonitor Claim+Start, and checks if video arrives.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, port))
        except (socket.error, OSError):
            return False

        try:
            # Login
            hashed = cls._sofia_hash(password)
            login_payload = json.dumps({
                "EncryptType": "MD5",
                "LoginType": "DVRIP-Web",
                "PassWord": hashed,
                "UserName": username,
            }, separators=(",", ":")) + "\n\x00"

            cls._dvrip_send(sock, 1000, login_payload.encode("utf-8"))
            resp = cls._dvrip_recv(sock)
            if resp is None:
                return False

            ret = resp.get("Ret", -1)
            if ret not in (100, 515):
                return False

            session = resp.get("SessionID", "0x00000000")

            # OPMonitor Claim
            claim_data = json.dumps({
                "Name": "OPMonitor",
                "SessionID": session,
                "OPMonitor": {
                    "Action": "Claim",
                    "Parameter": {
                        "Channel": channel,
                        "CombinMode": "NONE",
                        "StreamType": "Main",
                        "TransMode": "TCP",
                    },
                },
            }, separators=(",", ":")) + "\n\x00"

            cls._dvrip_send(sock, 1413, claim_data.encode("utf-8"))
            resp = cls._dvrip_recv(sock)
            if resp is None:
                return False

            # OPMonitor Start
            start_data = json.dumps({
                "Name": "OPMonitor",
                "SessionID": session,
                "OPMonitor": {
                    "Action": "Start",
                    "Parameter": {
                        "Channel": channel,
                        "CombinMode": "NONE",
                        "StreamType": "Main",
                        "TransMode": "TCP",
                    },
                },
            }, separators=(",", ":")) + "\n\x00"

            cls._dvrip_send(sock, 1410, start_data.encode("utf-8"))

            # Wait for first chunk — if it's video data, channel is active
            sock.settimeout(timeout)
            try:
                data = sock.recv(20)
                if len(data) < 20:
                    return False

                cmd = struct.unpack_from("<H", data, 14)[0]
                size = struct.unpack_from("<I", data, 16)[0]

                if size > 0 and size < 1048576:
                    payload = b""
                    while len(payload) < size:
                        chunk = sock.recv(min(size - len(payload), 65536))
                        if not chunk:
                            break
                        payload += chunk

                    # Check if this looks like a frame packet (starts with 00 00 01)
                    if len(payload) >= 3 and payload[:3] == b"\x00\x00\x01":
                        frame_type = payload[3]
                        # Video frame types: 0xFC (I), 0xFD (P), 0xFE (JPEG)
                        if frame_type in (0xFC, 0xFD, 0xFE):
                            return True

                # Non-video response — channel inactive
                return False

            except (socket.timeout, OSError):
                return False

        except Exception as e:
            LOGGER.debug("DVRIP probe channel %d on %s failed: %s", channel, ip, e)
            return False
        finally:
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def _dvrip_send(sock: socket.socket, cmd: int, payload: bytes) -> None:
        """Send a DVRIP command with 20-byte header."""
        header = bytearray(20)
        header[0] = 0xFF
        struct.pack_into("<H", header, 14, cmd)
        struct.pack_into("<I", header, 16, len(payload))
        sock.sendall(bytes(header) + payload)

    @staticmethod
    def _dvrip_recv(sock: socket.socket, timeout: float = 3.0) -> Optional[dict]:
        """Read a DVRIP response and parse as JSON."""
        sock.settimeout(timeout)
        try:
            header = b""
            while len(header) < 20:
                chunk = sock.recv(20 - len(header))
                if not chunk:
                    return None
                header += chunk

            size = struct.unpack_from("<I", header, 16)[0]
            if size > 1048576:
                return None

            payload = b""
            while len(payload) < size:
                chunk = sock.recv(min(size - len(payload), 65536))
                if not chunk:
                    break
                payload += chunk

            json_str = payload.decode("utf-8", errors="ignore").rstrip("\x00\n")
            return json.loads(json_str)

        except (json.JSONDecodeError, socket.timeout, OSError):
            return None

    @staticmethod
    def _sofia_hash(password: str) -> str:
        """Compute DVRIP sofia_hash (MD5-based password hash)."""
        import hashlib
        chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        md5_digest = hashlib.md5(password.encode("utf-8")).digest()
        sofia = bytearray(8)
        for i in range(0, 8):
            j = md5_digest[i * 2] + md5_digest[i * 2 + 1]
            sofia[i] = chars[j % 62]
        return sofia.decode("ascii")

    @classmethod
    async def _scan_rtsp_channels(cls, ip: str, username: str, password: str) -> List[Dict[str, Any]]:
        """Probe RTSP channels 1-16 and return active ones."""
        active_channels = []
        tasks = []

        for ch in range(1, 17):
            path = f"user={username}&password={password}&channel={ch}&stream=1.sdp?"
            tasks.append((ch, cls.verify_rtsp_channel(ip, 554, path)))

        channels, checks = zip(*tasks) if tasks else ([], [])
        results = await asyncio.gather(*checks) if checks else []

        for ch, active in zip(channels, results):
            if active:
                stream_url = f"rtsp://{username}:{password}@{ip}:554/user={username}&password={password}&channel={ch}&stream=1.sdp?"
                active_channels.append({
                    "channel_id": ch,
                    "display_name": f"Channel {ch} - Live feed",
                    "stream_url": stream_url,
                    "protocol": "rtsp",
                })

        return active_channels


class WSDiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, devices: list, seen_ips: set):
        self.devices = devices
        self.seen_ips = seen_ips

    def datagram_received(self, data: bytes, addr: tuple):
        ip = addr[0]
        if ip in self.seen_ips:
            return
        
        raw_xml = data.decode("utf-8", errors="ignore")
        # Extract metadata from ONVIF ProbeMatch xml
        name_match = re.search(r"<d:Scopes[^>]*>(.*?)</d:Scopes>", raw_xml, re.IGNORECASE)
        device_name = f"ONVIF Device ({ip})"
        if name_match:
            scopes = name_match.group(1)
            # Find scopes representing hardware name
            hardware = re.search(r"hardware/([^/\s]+)", scopes)
            if hardware:
                device_name = f"{hardware.group(1).replace('_', ' ')} ({ip})"

        self.seen_ips.add(ip)
        self.devices.append({
            "ip": ip,
            "name": device_name,
            "type": "ONVIF NVR / IP Camera",
            "discovery_method": "ws_discovery"
        })
