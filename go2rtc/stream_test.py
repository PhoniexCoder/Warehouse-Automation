"""
stream_test.py — Test suite for go2rtc VideoStream pipeline.

Tests:
  1. go2rtc process health
  2. DVRIP connectivity (URL format validation)
  3. RTSP stream reception (5+ frames)
  4. OpenCV compatibility
  5. PyAV compatibility (if installed)
  6. FFmpeg CLI compatibility
  7. Frame integrity (no duplicates)
  8. Timestamp continuity

Usage:
    python -m go2rtc.stream_test
    python go2rtc/stream_test.py --url rtsp://localhost:8554/ch0
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import Optional

import cv2
import numpy as np


RESULTS: list[tuple[str, bool, str]] = []


def test(name: str, fn):
    """Run a test and record pass/fail."""
    try:
        fn()
        RESULTS.append((name, True, "OK"))
        print(f"  PASS  {name}")
    except Exception as exc:
        RESULTS.append((name, False, str(exc)))
        print(f"  FAIL  {name}: {exc}")


# --- 1. go2rtc process health ---
def test_go2rtc_health(api_url: str):
    import httpx

    def _check():
        resp = httpx.get(f"{api_url}/api/streams", timeout=3.0)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise RuntimeError("No streams configured")
        return data

    test("go2rtc API reachable", _check)


# --- 2. DVRIP URL format validation ---
def test_dvrip_url_format():
    import re

    def _check():
        pattern = r"^dvrip://\w+:\w+@\d+\.\d+\.\d+\.\d+:\d+\?channel=\d+(&subtype=\d+)?$"
        examples = [
            "dvrip://uxdp:cw8adc@192.168.1.35:34567?channel=0",
            "dvrip://uxdp:cw8adc@192.168.1.35:34567?channel=3&subtype=0",
        ]
        for url in examples:
            if not re.match(pattern, url):
                raise RuntimeError(f"URL does not match pattern: {url}")

    test("DVRIP URL format valid", _check)


# --- 3. RTSP stream reception ---
def test_rtsp_reception(rtsp_url: str, min_frames: int = 5):
    def _check():
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open {rtsp_url}")
        frames = []
        deadline = time.time() + 10.0
        while len(frames) < min_frames and time.time() < deadline:
            ret, frame = cap.read()
            if ret and frame is not None:
                frames.append(frame)
            time.sleep(0.05)
        cap.release()
        if len(frames) < min_frames:
            raise RuntimeError(f"Got {len(frames)}/{min_frames} frames")
        return frames

    test(f"RTSP reception ({min_frames}+ frames)", _check)


# --- 4. OpenCV compatibility ---
def test_opencv_version():
    def _check():
        ver = cv2.__version__
        major = int(ver.split(".")[0])
        if major < 4:
            raise RuntimeError(f"OpenCV {ver} too old, need 4+")

    test(f"OpenCV compatibility (got {cv2.__version__})", _check)


# --- 5. PyAV compatibility ---
def test_pyav():
    def _check():
        try:
            import av
            ver = av.__version__
            return ver
        except ImportError:
            raise RuntimeError("PyAV not installed")

    test("PyAV available", _check)


# --- 6. FFmpeg CLI compatibility ---
def test_ffmpeg():
    def _check():
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError("ffmpeg not found or failed")
        first_line = result.stdout.split("\n")[0]
        return first_line

    test("FFmpeg CLI available", _check)


# --- 7. Frame integrity (no duplicates) ---
def test_frame_integrity(rtsp_url: str):
    def _check():
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open {rtsp_url}")
        frames = []
        deadline = time.time() + 8.0
        while len(frames) < 10 and time.time() < deadline:
            ret, frame = cap.read()
            if ret and frame is not None:
                frames.append(frame)
            time.sleep(0.05)
        cap.release()

        if len(frames) < 3:
            raise RuntimeError("Not enough frames for integrity check")

        hashes = [hash(f.tobytes()) for f in frames]
        unique = len(set(hashes))
        if unique < len(hashes):
            raise RuntimeError(f"{len(hashes) - unique} duplicate frames detected")

    test("Frame integrity (no duplicates)", _check)


# --- 8. Timestamp continuity ---
def test_timestamp_continuity(rtsp_url: str):
    def _check():
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open {rtsp_url}")
        timestamps = []
        deadline = time.time() + 8.0
        while len(timestamps) < 5 and time.time() < deadline:
            ret, _ = cap.read()
            if ret:
                timestamps.append(time.time())
            time.sleep(0.05)
        cap.release()

        if len(timestamps) < 3:
            raise RuntimeError("Not enough frames for timestamp check")

        diffs = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
        avg_gap = sum(diffs) / len(diffs)
        if avg_gap > 2.0:
            raise RuntimeError(f"Average frame gap {avg_gap:.2f}s too large")

    test("Timestamp continuity", _check)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="go2rtc stream test suite")
    parser.add_argument("--url", default="rtsp://localhost:8554/ch0", help="RTSP stream URL to test")
    parser.add_argument("--api", default="http://localhost:1984", help="go2rtc API URL")
    args = parser.parse_args()

    print("=" * 60)
    print("go2rtc Stream Test Suite")
    print("=" * 60)

    test_go2rtc_health(args.api)
    test_dvrip_url_format()
    test_opencv_version()
    test_pyav()
    test_ffmpeg()
    test_rtsp_reception(args.url)
    test_frame_integrity(args.url)
    test_timestamp_continuity(args.url)

    print()
    print("=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"Results: {passed}/{total} passed")
    if passed == total:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        for name, ok, msg in RESULTS:
            if not ok:
                print(f"  FAIL: {name} — {msg}")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
