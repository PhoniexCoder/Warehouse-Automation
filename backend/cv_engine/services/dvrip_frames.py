"""DVRIP/Sofia binary protocol frame parser.

Based on the actual go2rtc DVRIP implementation:
https://github.com/AlexxIT/go2rtc/blob/master/pkg/dvrip/client.go

Frame packet format:
- Multi-chunk reassembly: chunks have 20-byte DVRIP headers, payload reassembled
- Frame sub-header starts with 00 00 01 <type_byte>
- type 0xFC (I-frame) / 0xFE (JPEG): size = LE_uint32(buf[12:]) + 16
- type 0xFD (P-frame): size = LE_uint32(buf[4:]) + 8
- type 0xFA (audio) / 0xF9 (info): size = LE_uint16(buf[6:]) + 8
"""

import hashlib
import struct
from typing import Optional

# Frame type signatures (single byte at offset 3 in the sub-header)
TYPE_I_FRAME = 0xFC
TYPE_JPEG = 0xFE
TYPE_P_FRAME = 0xFD
TYPE_AUDIO = 0xFA
TYPE_INFO = 0xF9

# Codec mappings
VIDEO_CODEC = {1: "mpeg4", 2: "h264", 3: "h265", 0x12: "h265", 0x13: "h265"}
AUDIO_CODEC = {0x0E: "g711a", 0x0A: "g711u"}


def sofia_hash(password: str) -> str:
    """Compute the DVRIP/Sofia password hash.

    MD5(password) -> pair bytes -> (a+b) % 62 -> base62 char -> 8 chars.
    Matches go2rtc's SofiaHash function exactly.
    """
    md5 = hashlib.md5(password.encode("utf-8")).digest()
    chars = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    result = bytearray(8)
    for i in range(8):
        j = uint16(md5[2 * i]) + uint16(md5[2 * i + 1])
        result[i] = chars[j % 62]
    return result.decode("ascii")


def uint16(b: int) -> int:
    """Cast to unsigned 16-bit (Python has no unsigned types)."""
    return b & 0xFFFF


def calculate_packet_size(buf: bytes) -> int:
    """Calculate total packet size from the sub-header.

    Must be called after confirming buf starts with 00 00 01.
    Returns the total number of bytes needed for this frame packet.
    """
    if len(buf) < 4:
        return -1

    ptype = buf[3]

    if ptype in (TYPE_I_FRAME, TYPE_JPEG):
        # Need at least 16 bytes for the size field at offset 12
        if len(buf) < 16:
            return -1
        return struct.unpack_from("<I", buf, 12)[0] + 16

    elif ptype == TYPE_P_FRAME:
        # Need at least 8 bytes for the size field at offset 4
        if len(buf) < 8:
            return -1
        return struct.unpack_from("<I", buf, 4)[0] + 8

    elif ptype in (TYPE_AUDIO, TYPE_INFO):
        # Need at least 8 bytes for the size field at offset 6
        if len(buf) < 8:
            return -1
        return struct.unpack_from("<H", buf, 6)[0] + 8

    return -1


def is_frame_header(buf: bytes) -> bool:
    """Check if buffer starts with the DVRIP frame signature 00 00 01."""
    return len(buf) >= 3 and buf[0] == 0 and buf[1] == 0 and buf[2] == 1


def extract_video_data(packet: bytes) -> Optional[bytes]:
    """Extract raw video NAL data from a frame packet.

    For I-frames (0xFC): video data starts at offset 16
    For P-frames (0xFD): video data starts at offset 8
    For JPEG (0xFE): packet IS the JPEG data starting at offset 16
    """
    if len(packet) < 4:
        return None

    ptype = packet[3]

    if ptype == TYPE_I_FRAME:
        return packet[16:] if len(packet) > 16 else None
    elif ptype == TYPE_P_FRAME:
        return packet[8:] if len(packet) > 8 else None
    elif ptype == TYPE_JPEG:
        return packet[16:] if len(packet) > 16 else None

    return None


def frame_type_name(ptype: int) -> str:
    """Human-readable frame type name."""
    names = {
        TYPE_I_FRAME: "I-frame",
        TYPE_JPEG: "JPEG",
        TYPE_P_FRAME: "P-frame",
        TYPE_AUDIO: "audio",
        TYPE_INFO: "info",
    }
    return names.get(ptype, f"unknown(0x{ptype:02X})")
