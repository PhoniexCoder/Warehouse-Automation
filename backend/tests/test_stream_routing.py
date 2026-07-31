import os
import sys

os.environ["INTERNAL_API_KEY"] = "test-key"

import pytest

from server import _parse_dvrip_url, _route_camera


@pytest.fixture
def fake_stream_manager(monkeypatch):
    calls = {"dvrip": [], "rtsp": []}

    class FakeStreamManager:
        def start_camera(self, **kwargs):
            calls["dvrip"].append(kwargs)

        def start_camera_rtsp(self, **kwargs):
            calls["rtsp"].append(kwargs)

    import server
    monkeypatch.setattr(server, "stream_manager", FakeStreamManager())
    return calls


def test_parse_dvrip_url():
    info = _parse_dvrip_url("dvrip://admin:secret@192.168.1.35:34567/3")
    assert info == {
        "username": "admin",
        "password": "secret",
        "host": "192.168.1.35",
        "port": 34567,
        "channel": 3,
    }


def test_parse_dvrip_url_malformed():
    assert _parse_dvrip_url("dvrip://nope") is None
    assert _parse_dvrip_url("rtsp://192.168.1.35:554/stream") is None
    assert _parse_dvrip_url("") is None


def test_route_dvrip_urls_to_camera_stream(fake_stream_manager):
    ok = _route_camera(
        "cam-1",
        "dvrip://admin:secret@192.168.1.35:34567/3",
    )
    assert ok is True
    assert len(fake_stream_manager["dvrip"]) == 1
    assert fake_stream_manager["dvrip"][0] == {
        "camera_id": "cam-1",
        "host": "192.168.1.35",
        "port": 34567,
        "username": "admin",
        "password": "secret",
        "channel": 3,
    }
    assert fake_stream_manager["rtsp"] == []


def test_route_rtsp_urls_to_rtsp_stream(fake_stream_manager):
    ok = _route_camera("cam-2", "rtsp://user:pass@192.168.1.35:554/stream")
    assert ok is True
    assert len(fake_stream_manager["rtsp"]) == 1
    assert fake_stream_manager["rtsp"][0] == {
        "camera_id": "cam-2",
        "rtsp_url": "rtsp://user:pass@192.168.1.35:554/stream",
    }
    assert fake_stream_manager["dvrip"] == []


def test_route_malformed_dvrip_skipped(fake_stream_manager):
    ok = _route_camera("cam-3", "dvrip://broken")
    assert ok is False
    assert fake_stream_manager["dvrip"] == []
    assert fake_stream_manager["rtsp"] == []


def test_route_unsupported_scheme_skipped(fake_stream_manager):
    ok = _route_camera("cam-4", "http://example.com/stream")
    assert ok is False
    assert fake_stream_manager["dvrip"] == []
    assert fake_stream_manager["rtsp"] == []


def test_route_empty_url_skipped(fake_stream_manager):
    ok = _route_camera("cam-5", "")
    assert ok is False
    assert fake_stream_manager["dvrip"] == []
    assert fake_stream_manager["rtsp"] == []
