import asyncio
import hashlib
import logging
import os
from pathlib import Path

import httpx

LOGGER = logging.getLogger(__name__)

GO2RTC_API_URL = os.getenv("GO2RTC_API_URL", "http://host.docker.internal:1984")
GO2RTC_CONFIG_PATH = os.getenv("GO2RTC_CONFIG_PATH", "/config/go2rtc.yaml")
GO2RTC_CONTAINER = os.getenv("GO2RTC_CONTAINER", "go2rtc")
DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "unix:///var/run/docker.sock")


_YAML_HEADER = """\
log:
  level: info

api:
  listen: ":1984"
  origins:
    - "*"

rtsp:
  listen: ":8554"

webrtc:
  listen: ":8555"

streams:
"""


def generate_yaml(cameras: list[dict]) -> str:
    """Generate go2rtc.yaml content from a list of camera dicts.

    Each camera dict must have 'id' (UUID str) and 'stream_url'.
    Uses dict format: `  cam_id: { source: "dvrip://..." }` per go2rtc convention.
    """
    lines = [_YAML_HEADER.rstrip()]
    for cam in cameras:
        cam_id = cam["id"]
        url = cam.get("stream_url", "")
        if not url:
            continue
        lines.append(f'  {cam_id}:')
        lines.append(f'    source: "{url}"')
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


async def restart_go2rtc() -> bool:
    """Restart the go2rtc Docker container via Docker Engine API.

    go2rtc only reads its config file at startup, so a restart is required
    after writing a new config. Uses the Docker socket mounted into the
    business-backend container.
    """
    try:
        socket_path = DOCKER_SOCKET.replace("unix://", "")
        # Use httpx with unix socket transport
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        async with httpx.AsyncClient(transport=transport, timeout=10.0) as client:
            # Restart the go2rtc container (SIGTERM then SIGKILL after 10s)
            resp = await client.post(
                f"http://localhost/containers/{GO2RTC_CONTAINER}/restart?t=5",
            )
            if resp.status_code == 204:
                LOGGER.info("go2rtc container restarted successfully")
                return True
            LOGGER.warning("go2rtc restart failed: %s %s", resp.status_code, resp.text[:200])
            return False
    except FileNotFoundError:
        LOGGER.warning("Docker socket not found at %s — cannot auto-restart go2rtc. "
                        "Please restart manually: docker restart %s",
                        DOCKER_SOCKET, GO2RTC_CONTAINER)
        return False
    except Exception as e:
        LOGGER.warning("go2rtc restart error: %s", e)
        return False


async def sync_cameras(cameras: list[dict]) -> str:
    """Full sync: write go2rtc config and restart to apply.

    1. Generate and write go2rtc.yaml from DB cameras
    2. Restart go2rtc so it picks up the new config
    3. Return config hash

    go2rtc reads its config only at startup, so restart is required
    for DVRIP streams. The container restarts in ~2 seconds.
    """
    old_hash = write_config(cameras)

    # Restart go2rtc to apply new config
    restarted = await restart_go2rtc()
    if restarted:
        LOGGER.info("go2rtc sync complete: %d cameras, restarting", len(cameras))
    else:
        LOGGER.warning("go2rtc sync: config written but restart failed — "
                       "streams won't update until manual restart")

    return old_hash
