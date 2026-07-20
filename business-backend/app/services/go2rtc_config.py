import asyncio
import hashlib
import logging
import os
from pathlib import Path

import httpx

LOGGER = logging.getLogger(__name__)

GO2RTC_API_URL = os.getenv("GO2RTC_API_URL", "http://host.docker.internal:1984")
GO2RTC_CONFIG_PATH = os.getenv("GO2RTC_CONFIG_PATH", "/config/go2rtc.yaml")

_YAML_HEADER = """\
log:
  level: info

api:
  listen: ":1984"

rtsp:
  listen: ":8554"

webrtc:
  listen: ":8555"

streams:
"""


def generate_yaml(cameras: list[dict]) -> str:
    """Generate go2rtc.yaml content from a list of camera dicts.

    Each camera dict must have 'id' (UUID str) and 'stream_url'.
    Uses simple string format: `  cam_id: "dvrip://..."` (single source per camera).
    """
    lines = [_YAML_HEADER.rstrip()]
    for cam in cameras:
        cam_id = cam["id"]
        url = cam.get("stream_url", "")
        if not url:
            continue
        lines.append(f'  {cam_id}: "{url}"')
    if len(cameras) == 0:
        lines.append("  {}")
    return "\n".join(lines) + "\n"


def write_config(cameras: list[dict]) -> str:
    """Generate and write go2rtc.yaml, return the config hash."""
    content = generate_yaml(cameras)
    config_hash = hashlib.sha256(content.encode()).hexdigest()

    config_path = Path(GO2RTC_CONFIG_PATH)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    tmp = config_path.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.rename(config_path)

    LOGGER.info("go2rtc config written (%d cameras, hash=%s)", len(cameras), config_hash[:12])
    return config_hash


async def add_stream(camera_id: str, source_url: str) -> bool:
    """Add a stream to go2rtc via its REST API (POST /api/streams)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{GO2RTC_API_URL}/api/streams",
                json={"name": camera_id, "source": source_url},
            )
            if resp.status_code < 300:
                LOGGER.debug("go2rtc stream added: %s", camera_id)
                return True
            LOGGER.warning("go2rtc add_stream failed: %s %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        LOGGER.warning("go2rtc add_stream error: %s", e)
        return False


async def remove_stream(camera_id: str) -> bool:
    """Remove a stream from go2rtc via its REST API."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.delete(f"{GO2RTC_API_URL}/api/streams/{camera_id}")
            if resp.status_code < 300:
                LOGGER.debug("go2rtc stream removed: %s", camera_id)
                return True
            LOGGER.warning("go2rtc remove_stream failed: %s %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        LOGGER.warning("go2rtc remove_stream error: %s", e)
        return False


async def get_streams() -> dict:
    """GET all current streams from go2rtc."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{GO2RTC_API_URL}/api/streams")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        LOGGER.warning("go2rtc get_streams error: %s", e)
    return {}


async def sync_cameras(cameras: list[dict]) -> str:
    """Full sync: reconcile go2rtc streams with the database, rewrite config file.

    Returns the config hash after sync.
    """
    expected = {cam["id"]: cam["stream_url"] for cam in cameras if cam.get("stream_url")}
    actual = await get_streams()

    to_add = set(expected) - set(actual)
    to_remove = set(actual) - set(expected)

    for cam_id in to_add:
        await add_stream(cam_id, expected[cam_id])
    for cam_id in to_remove:
        await remove_stream(cam_id)

    if to_add or to_remove:
        LOGGER.info("go2rtc sync: added=%d removed=%d", len(to_add), len(to_remove))

    return write_config(cameras)
