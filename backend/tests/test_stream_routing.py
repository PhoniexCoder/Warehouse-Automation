import os
import sys

os.environ["INTERNAL_API_KEY"] = "test-key"

import pytest

from server import _parse_dvrip_url, _route_camera


@pytest.fixture
def fake_stream_manager(monkeypatch):
    calls = {"dvrip": [], "rtsp": [], "video": []}

    class FakeStreamManager:
        def start_camera(self, **kwargs):
            calls["dvrip"].append(kwargs)

        def start_camera_rtsp(self, **kwargs):
            calls["rtsp"].append(kwargs)

        def start_camera_video(self, **kwargs):
            calls["video"].append(kwargs)

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


def test_route_file_url_absolute_path(fake_stream_manager, tmp_path):
    import server

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 16)

    ok = _route_camera("cam-6", f"file://{video.as_posix()}")
    assert ok is True
    assert fake_stream_manager["video"] == [{
        "camera_id": "cam-6",
        "file_path": video.as_posix(),
    }]
    assert fake_stream_manager["dvrip"] == []
    assert fake_stream_manager["rtsp"] == []


def test_route_mp4_relative_to_media_dir(fake_stream_manager, tmp_path, monkeypatch):
    import server

    video = tmp_path / "warehouse_normal.mp4"
    video.write_bytes(b"\x00" * 16)
    monkeypatch.setattr(server, "MEDIA_DIR", tmp_path.as_posix())

    ok = _route_camera("cam-7", "warehouse_normal.mp4")
    assert ok is True
    assert len(fake_stream_manager["video"]) == 1
    call = fake_stream_manager["video"][0]
    assert call["camera_id"] == "cam-7"
    assert os.path.normpath(call["file_path"]) == os.path.normpath(str(video))


def test_route_mp4_case_insensitive(fake_stream_manager, tmp_path, monkeypatch):
    import server

    video = tmp_path / "WAREHOUSE_NORMAL.MP4"
    video.write_bytes(b"\x00" * 16)
    monkeypatch.setattr(server, "MEDIA_DIR", tmp_path.as_posix())

    ok = _route_camera("cam-8", "WAREHOUSE_NORMAL.MP4")
    assert ok is True
    assert len(fake_stream_manager["video"]) == 1
    call = fake_stream_manager["video"][0]
    assert call["camera_id"] == "cam-8"
    assert os.path.normpath(call["file_path"]) == os.path.normpath(str(video))


def test_route_file_url_without_media_dir_prefix(fake_stream_manager, tmp_path, monkeypatch):
    import server

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 16)
    monkeypatch.setattr(server, "MEDIA_DIR", tmp_path.as_posix())

    ok = _route_camera("cam-9", "file://clip.mp4")
    assert ok is True
    assert len(fake_stream_manager["video"]) == 1
    call = fake_stream_manager["video"][0]
    assert call["camera_id"] == "cam-9"
    assert os.path.normpath(call["file_path"]) == os.path.normpath(str(video))


def test_route_video_file_missing_skipped(fake_stream_manager, tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "MEDIA_DIR", tmp_path.as_posix())

    ok = _route_camera("cam-10", "nope.mp4")
    assert ok is False
    assert fake_stream_manager["video"] == []


def test_route_mp4_extension_not_file_scheme(fake_stream_manager, tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "MEDIA_DIR", tmp_path.as_posix())

    ok = _route_camera("cam-11", "script.mp4?token=x")
    assert ok is False
    assert fake_stream_manager["video"] == []
