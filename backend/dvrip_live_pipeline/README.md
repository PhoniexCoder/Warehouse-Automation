# Native DVRIP Box Counter Pipeline

Live box/package detection and counting directly from TVS/XM NVR cameras
using the native DVRIP protocol — **no RTSP, no go2rtc, no FFmpeg required.**

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Step 1: Draw detection zone (first time only)
python main2.py --dvrip --channel 6 --conf 0.55 --set-rect

# Step 2: Run counting pipeline
python main2.py --dvrip --channel 6 --conf 0.55 --exit-bottom
```

## Files

| File | Description |
|------|-------------|
| `main2.py` | Main entry point — set-rect, YOLO detection, IOU tracking, counting |
| `tvs_dvrip.py` | Native DVRIP protocol client, H.265 parser, and decoder |
| `dvrip_adapter.py` | cv2.VideoCapture-compatible wrapper for DVRIP streams |
| `dvrip_capture.py` | Production-grade threaded capture with auto-reconnect |
| `box_model.pt` | Custom-trained YOLO model (class: Carton) |
| `box_model.onnx` | ONNX export for faster inference (auto-detected) |
| `requirements.txt` | Python dependencies |

## Camera Configuration

Default NVR settings (edit `main2.py` line 20 to change):

```python
CAMERA_USER, CAMERA_PASS, CAMERA_IP, CAMERA_CH = "uxdp", "cw8adc", "192.168.1.35", 3
```

## Command Line Options

```
python main2.py --dvrip --channel 6 --conf 0.55 --set-rect --exit-bottom
```

| Flag | Description |
|------|-------------|
| `--dvrip` | Use native DVRIP protocol (required for live NVR) |
| `--channel N` | Camera channel number |
| `--conf 0.55` | YOLO detection confidence threshold |
| `--count-conf 0.55` | Minimum confidence for counting |
| `--set-rect` | Interactive ROI drawing mode |
| `--exit-bottom` | Enable line-crossing counting |
| `--imgsz 1280` | YOLO inference resolution |
| `--detect-every 3` | Run detection every N frames |
| `--hd` | Display at 1920x1080 |

Also works with video files and RTSP:

```bash
python main2.py --video "path/to/video.mp4" --set-rect --exit-bottom
python main2.py --live --channel 6 --set-rect --exit-bottom
```

## How It Works

1. Connects to NVR via TCP on port 34567 (DVRIP protocol)
2. Authenticates using SofiaHash (XMMD5) password hashing
3. Opens a data socket with MonitorClaim + MonitorStart
4. Parses proprietary `00 00 01 XX` video framing
5. Extracts H.265 Annex-B NAL units and decodes with PyAV
6. Runs YOLO inference for box detection
7. Tracks objects using IOU matching across frames
8. Counts boxes crossing the configured count line
9. Sends keepalive packets every 10s to prevent NVR disconnect
10. Auto-reconnects if the data connection drops

## Requirements

- Python 3.8+
- NVIDIA GPU with CUDA (for YOLO inference)
- Network access to NVR on port 34567
