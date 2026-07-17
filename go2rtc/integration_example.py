"""
integration_example.py — Full pipeline: Go2RTCManager + VideoStream + YOLO.

Demonstrates the complete workflow described in go2rtc_WORKFLOW.md:

    NVR (DVRIP) → go2rtc (converts to RTSP) → VideoStream (reads & buffers) → YOLO (detects)

Usage:
    python -m go2rtc.integration_example --url rtsp://localhost:8554/ch0
    python go2rtc/integration_example.py --go2rtc-dir C:\go2rtc --url rtsp://localhost:554/warehouse_main
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from go2rtc.video_stream import Go2RTCManager, VideoStream


def run_pipeline(rtsp_url: str, go2rtc_dir: str | None = None, duration: float = 30.0) -> None:
    """Run the full detection pipeline."""
    # 1. Optionally start go2rtc (local development only)
    go2rtc: Go2RTCManager | None = None
    if go2rtc_dir:
        go2rtc = Go2RTCManager(go2rtc_dir)
        if not go2rtc.is_running():
            print("Starting go2rtc...")
            go2rtc.start()
            time.sleep(3)
        else:
            print("go2rtc already running")

    # 2. Open RTSP stream
    print(f"Connecting to {rtsp_url}...")
    stream = VideoStream(rtsp_url, buffer_size=30, enable_watchdog=True)

    if not stream.is_open():
        print("ERROR: Cannot open stream")
        if go2rtc:
            go2rtc.stop()
        return

    print(f"Stream open: {stream.width}x{stream.height} @ {stream.fps:.0f} fps")

    # 3. Load YOLO model (if available)
    model = None
    try:
        from ultralytics import YOLO
        model = YOLO("models/box_model.pt")
        print("YOLO model loaded")
    except Exception:
        print("YOLO model not available — running in passthrough mode")

    # 4. Read frames in loop
    deadline = time.time() + duration
    frame_count = 0
    detect_count = 0

    print(f"Running pipeline for {duration}s...")
    try:
        while stream.is_open() and time.time() < deadline:
            ret, frame = stream.read(timeout=2.0)
            if not ret or frame is None:
                continue

            frame_count += 1

            # Run YOLO inference
            if model is not None:
                results = model(frame, verbose=False)
                boxes = results[0].boxes
                if boxes is not None and len(boxes) > 0:
                    detect_count += 1
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        conf = float(box.conf[0])
                        cls = int(box.cls[0])
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"{conf:.2f}", (x1, y1 - 5),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # Display (if GUI available)
            try:
                cv2.imshow("go2rtc Pipeline", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            except cv2.error:
                pass

    except KeyboardInterrupt:
        print("Interrupted")

    # 5. Print stats
    print()
    print("Pipeline Stats:")
    stats = stream.stats.to_dict()
    for key, val in stats.items():
        print(f"  {key}: {val}")
    print(f"  frames_processed: {frame_count}")
    print(f"  detections: {detect_count}")

    stream.release()
    if go2rtc:
        go2rtc.stop()

    try:
        cv2.destroyAllWindows()
    except cv2.error:
        pass


def main():
    parser = argparse.ArgumentParser(description="go2rtc + YOLO integration example")
    parser.add_argument("--url", default="rtsp://localhost:8554/ch0", help="RTSP stream URL")
    parser.add_argument("--go2rtc-dir", default=None, help="go2rtc installation directory (optional)")
    parser.add_argument("--duration", type=float, default=30.0, help="Run duration in seconds")
    args = parser.parse_args()

    run_pipeline(args.url, args.go2rtc_dir, args.duration)


if __name__ == "__main__":
    main()
