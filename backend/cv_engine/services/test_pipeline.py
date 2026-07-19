"""End-to-end DVRIP pipeline test.

Tests: DVRIP connect → login → OPMonitor → packet read → FFmpeg decode → JPEG output.

Run from Windows dev machine (NVR at 192.168.1.35 must be reachable):
    python backend\cv_engine\services\test_pipeline.py

Or with specific channel:
    python backend\cv_engine\services\test_pipeline.py --channel 0
    python backend\cv_engine\services\test_pipeline.py --channel 3
"""

import sys
import os
import time
import argparse
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cv_engine.services.dvrip_client import DVRIPClient, DVRIPAuthError, DVRIPConnectionError
from cv_engine.services.dvrip_frames import TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG, frame_type_name
from cv_engine.services.ffmpeg_decoder import FfmpegDecoder


def main():
    parser = argparse.ArgumentParser(description="DVRIP pipeline test")
    parser.add_argument("--host", default="192.168.1.35", help="NVR host")
    parser.add_argument("--port", type=int, default=34567, help="NVR port")
    parser.add_argument("--user", default="uxdp", help="Username")
    parser.add_argument("--password", default="cw8adc", help="Password")
    parser.add_argument("--channel", type=int, default=0, help="Channel number")
    parser.add_argument("--frames", type=int, default=30, help="Number of video frames to capture")
    parser.add_argument("--save-dir", default=None, help="Directory to save JPEG frames (optional)")
    args = parser.parse_args()

    print("=" * 60)
    print("DVRIP PIPELINE TEST")
    print("=" * 60)
    print(f"NVR:     {args.host}:{args.port}")
    print(f"Auth:    {args.user}:****")
    print(f"Channel: {args.channel}")
    print(f"Target:  {args.frames} frames")
    print()

    # Step 1: Connect
    print("[1/4] Connecting to NVR...")
    t0 = time.time()
    client = DVRIPClient(
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        timeout=10,
    )

    try:
        client.connect(channel=args.channel)
    except DVRIPAuthError as e:
        print(f"  FAILED: Auth error: {e}")
        print("  Possible causes: wrong credentials, account locked")
        return 1
    except DVRIPConnectionError as e:
        print(f"  FAILED: Connection error: {e}")
        return 1

    connect_time = time.time() - t0
    print(f"  OK ({connect_time:.2f}s)")

    # Step 2: Read packets
    print(f"\n[2/4] Reading first packet to detect codec...")
    t1 = time.time()
    codec = "h264"
    width, height = 1920, 1080
    packet_count = 0
    video_count = 0
    audio_count = 0
    first_frame_time = None
    decoder = None

    try:
        for ptype, payload, meta in client.iter_packets():
            packet_count += 1

            if first_frame_time is None:
                first_frame_time = time.time() - t1
                print(f"  First packet in {first_frame_time:.2f}s")

            if ptype in (TYPE_I_FRAME, TYPE_P_FRAME, TYPE_JPEG):
                video_count += 1

                # Detect codec from first I-frame
                if ptype == TYPE_I_FRAME and "codec" in meta:
                    codec_byte = meta["codec"]
                    if codec_byte in (3, 0x12, 0x13):
                        codec = "h265"
                    else:
                        codec = "h264"
                    width = meta.get("width", 1920)
                    height = meta.get("height", 1080)
                    print(f"  Detected: codec={codec}, resolution={width}x{height}")

                # Step 3: Decode with FFmpeg
                if decoder is None:
                    print(f"\n[3/4] Starting FFmpeg decoder ({codec})...")
                    decoder = FfmpegDecoder(width=width, height=height, codec=codec)
                    if not decoder.start():
                        print("  FAILED: Could not start FFmpeg decoder")
                        client.close()
                        return 1
                    print(f"  OK (file-based mode)")

                t2 = time.time()
                jpeg = decoder.decode(payload)
                decode_time = time.time() - t2

                if jpeg:
                    print(f"  [{video_count}/{args.frames}] decoded in {decode_time*1000:.0f}ms "
                          f"({frame_type_name(ptype)}) {len(payload)}B -> {len(jpeg)}B JPEG")

                    # Optionally save to disk
                    if args.save_dir:
                        os.makedirs(args.save_dir, exist_ok=True)
                        path = os.path.join(args.save_dir, f"frame_{video_count:04d}.jpg")
                        with open(path, "wb") as f:
                            f.write(jpeg)
                else:
                    print(f"  [{video_count}/{args.frames}] decode FAILED "
                          f"({frame_type_name(ptype)}) {len(payload)}B")

                if video_count >= args.frames:
                    break

            elif ptype in (0xFA, 0xF9):
                audio_count += 1

    except KeyboardInterrupt:
        print("\n  Interrupted by user")
    except Exception as e:
        print(f"\n  Error: {type(e).__name__}: {e}")

    total_time = time.time() - t0

    # Step 4: Summary
    print(f"\n[4/4] Summary")
    print(f"  Packets received:  {packet_count} ({video_count} video, {audio_count} audio)")
    print(f"  Video frames decoded: {video_count}/{args.frames}")
    print(f"  Total time: {total_time:.1f}s")
    if video_count > 0:
        fps = video_count / total_time
        print(f"  Effective FPS: {fps:.1f}")

    if decoder:
        print(f"  Decoder stats: {decoder.stats}")
        decoder.stop()

    client.close()

    if video_count > 0:
        print(f"\n  PIPELINE WORKING!")
        if args.save_dir:
            print(f"  Frames saved to: {os.path.abspath(args.save_dir)}")
        return 0
    else:
        print(f"\n  PIPELINE FAILED - no video decoded")
        return 1


if __name__ == "__main__":
    sys.exit(main())
