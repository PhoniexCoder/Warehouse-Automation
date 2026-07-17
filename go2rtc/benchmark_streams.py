"""
benchmark_streams.py — Performance benchmarking for go2rtc streams.

Measures: FPS, bandwidth (Mbps), decode latency (ms), frame drop rate (%).

Usage:
    python -m go2rtc.benchmark_streams --url rtsp://localhost:8554/ch0
    python go2rtc/benchmark_streams.py --url rtsp://localhost:8554/ch0 --duration 30
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np


def benchmark(rtsp_url: str, duration: float = 10.0, warmup: float = 2.0) -> dict:
    """Run benchmark and return stats."""
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {rtsp_url}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps_setting = cap.get(cv2.CAP_PROP_FPS)

    # Warmup
    print(f"Warming up for {warmup}s...")
    deadline = time.time() + warmup
    while time.time() < deadline:
        cap.read()

    # Benchmark
    print(f"Benchmarking for {duration}s...")
    frames = 0
    drops = 0
    latencies: list[float] = []
    frame_sizes: list[int] = []
    start = time.time()
    deadline = start + duration

    while time.time() < deadline:
        t0 = time.monotonic()
        ret, frame = cap.read()
        t1 = time.monotonic()

        if not ret or frame is None:
            drops += 1
            continue

        frames += 1
        latencies.append((t1 - t0) * 1000)  # ms
        frame_sizes.append(frame.nbytes)

    cap.release()
    elapsed = time.time() - start

    total_frames = frames + drops
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p99_latency = sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0
    avg_frame_bytes = sum(frame_sizes) / len(frame_sizes) if frame_sizes else 0
    bandwidth_mbps = (avg_frame_bytes * 8 * (frames / max(elapsed, 0.01))) / 1_000_000

    return {
        "url": rtsp_url,
        "resolution": f"{width}x{height}",
        "fps_setting": fps_setting,
        "duration_s": round(elapsed, 1),
        "frames_captured": frames,
        "frames_dropped": drops,
        "drop_rate_pct": round((drops / max(total_frames, 1)) * 100, 2),
        "effective_fps": round(frames / max(elapsed, 0.01), 1),
        "avg_latency_ms": round(avg_latency, 2),
        "p99_latency_ms": round(p99_latency, 2),
        "avg_frame_size_kb": round(avg_frame_bytes / 1024, 1),
        "bandwidth_mbps": round(bandwidth_mbps, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="go2rtc stream benchmark")
    parser.add_argument("--url", default="rtsp://localhost:8554/ch0", help="RTSP stream URL")
    parser.add_argument("--duration", type=float, default=10.0, help="Benchmark duration in seconds")
    parser.add_argument("--warmup", type=float, default=2.0, help="Warmup duration in seconds")
    args = parser.parse_args()

    print("=" * 60)
    print("go2rtc Stream Benchmark")
    print("=" * 60)

    try:
        results = benchmark(args.url, args.duration, args.warmup)
    except Exception as exc:
        print(f"Benchmark failed: {exc}")
        return 1

    print()
    for key, val in results.items():
        print(f"  {key:.<30} {val}")

    print()
    verdict = "GOOD" if results["drop_rate_pct"] < 1.0 and results["effective_fps"] > 1.0 else "ISSUES"
    print(f"Verdict: {verdict}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
