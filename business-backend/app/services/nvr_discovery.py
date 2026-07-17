import socket
import asyncio
import logging
import re
from typing import List, Dict, Any

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
        """Generate DVRIP URLs for channels 1-16. DVRIP doesn't support
        per-channel probing, so we return all 16 as available."""
        channels = []
        for ch in range(1, 17):
            stream_url = f"dvrip://{username}:{password}@{ip}:34567/{ch}"
            channels.append({
                "channel_id": ch,
                "display_name": f"Channel {ch} - DVRIP Live feed",
                "stream_url": stream_url,
                "protocol": "dvrip",
            })
        return channels

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
