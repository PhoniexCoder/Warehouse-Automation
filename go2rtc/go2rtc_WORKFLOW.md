# go2rtc Full Workflow — TVS NVR → YOLO Inference Pipeline

## Architecture Overview

```
TVS NVR (192.168.1.35:34567)
    │
    │ DVRIP protocol (TCP, proprietary binary)
    │ Auth: XMMD5/SofiaHash challenge-response
    │
    ▼
┌─────────────────────────────────────┐
│         go2rtc.exe (v1.9.14)        │
│  Location: C:\go2rtc\               │
│  Config:  C:\go2rtc\go2rtc.yaml     │
│                                     │
│  ┌───────────────────────────────┐  │
│  │  DVRIP Client (built-in)      │  │
│  │  - SofiaHash auth             │  │
│  │  - Monitor stream (Claim +    │  │
│  │    Start commands)            │  │
│  │  - H.264/H.265 over TCP       │  │
│  └──────────┬────────────────────┘  │
│             │                        │
│     ┌───────┴───────┐               │
│     │   Stream Bus   │               │
│     └───┬───┬───┬───┘               │
│         │   │   │                    │
│   ┌─────┘   │   └─────┐             │
│   ▼         ▼         ▼             │
│ RTSP:554  WebRTC:8555  HTTP API     │
│                     (1476)           │
└─────────┬───────────────────────────┘
          │
          ▼
┌──────────────────────────────────────┐
│  Python Application                  │
│                                      │
│  VideoStream class                   │
│  ┌────────────────────────────────┐  │
│  │  cv2.VideoCapture(RTSP URL)    │  │
│  │  + auto-reconnect              │  │
│  │  + watchdog thread             │  │
│  │  + frame buffer (queue)        │  │
│  │  + hardware decode (D3D11)     │  │
│  │  + stats tracking              │  │
│  └──────────┬─────────────────────┘  │
│             │                         │
│             ▼                         │
│  ┌────────────────────────────────┐  │
│  │  YOLOv8 / Inference Pipeline   │  │
│  │  - object detection            │  │
│  │  - box counting                │  │
│  │  - ByteTrack tracking          │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

---

## Step-by-Step Workflow

### 1. Installation

**Location:** `C:\go2rtc\`

Download go2rtc v1.9.14+ from: https://github.com/AlexxIT/go2rtc

The installer (`install.bat` / `install.ps1`):
- Creates `C:\go2rtc\` directory structure
- Downloads `go2rtc_win64.zip` and extracts `go2rtc.exe`
- Copies `go2rtc.yaml` configuration
- Creates `start.bat` and `start.ps1` launchers

### 2. Configuration (`go2rtc.yaml`)

```yaml
api:
  listen: ":1476"
  origins:
    - "*"

rtsp:
  listen: ":554"

webrtc:
  listen: ":8555"

ffmpeg:
  bin: "C:\\FFmpeg\\ffmpeg-master-latest-win64-gpl\\bin\\ffmpeg.exe"

streams:
  warehouse_main:
    # DVRIP directly from NVR (no ffmpeg, no RTSP from camera)
    source: "dvrip://uxdp:cw8adc@192.168.1.35:34567?channel=0"

  warehouse_main_rtsp:
    # Restream the DVRIP source as RTSP
    source: "#warehouse_main"

  warehouse_main_webrtc:
    # WebRTC for browser viewing
    source: "#warehouse_main"
```

**Key points:**
- `dvrip://` scheme — go2rtc has a **built-in DVRIP client** (no external tools needed)
- Channel 0 = first camera. Change for multi-camera setups
- `#warehouse_main` references another stream by name (no re-fetch from NVR)
- Ports: RTSP=554, WebRTC=8555, HTTP API=1476

### 3. Starting go2rtc

**PowerShell:**
```powershell
# Must run from C:\go2rtc directory
Push-Location C:\go2rtc
.\go2rtc.exe
```

**Expected console output:**
```
[rtsp] Listen on :554
[webrtc] Listen on :8555
[dvrip] Connected to 192.168.1.35:34567
[warehouse_main] Stream started
```

### 4. What Happens Internally (DVRIP Protocol)

When go2rtc connects via DVRIP:

1. **TCP connect** to `192.168.1.35:34567`
2. **Login handshake:**
   - Server sends a random challenge (nonce) + base64-encoded hash iteration seed
   - go2rtc computes `XMMD5 = MD5(MD5(username:realm:password) + ":" + nonce + ":" + MD5(username:realm:password))` (SofiaHash)
   - Sends login packet with hashed credentials
3. **Claim monitor stream** — DVRIP JSON command: `{"SessionID":"...","Type":"OPlay","Sequence":3,"Command":"Claim","Params":{"Channel":0,"StreamType":"Main","TransMode":"TCP"}}`
4. **Start monitor** — JSON command: `{"SessionID":"...","Type":"OPlay","Sequence":4,"Command":"Start","Params":{"Channel":0,"StreamType":"Main","TransMode":"TCP"}}`
5. **Receive raw H.264/H.265** — proprietary binary frames with 20-byte DVRIP headers:
   - `0xFFFFFFFF` frame delimiter
   - Stream type byte
   - Timestamp (6 bytes, millisecond offset)
   - Packet length (4 bytes)
   - H.264/H.265 Annex-B payload (starts with 00 00 00 01 NAL)

This is the **same protocol** that XMEye app uses — no RTSP/ONVIF needed from the camera side.

### 5. RTSP Output

Once go2rtc has the DVRIP stream, it re-encapsulates it as standard RTSP:

```
rtsp://localhost:554/warehouse_main
```

This is what Python consumes. The VideoStream class opens this URL via `cv2.VideoCapture`.

### 6. Python Side — VideoStream Class

**File:** `video_stream.py`

```python
from video_stream import VideoStream

stream = VideoStream("rtsp://localhost:554/warehouse_main")
# Or use Go2RTCManager to start/stop go2rtc programmatically:
from video_stream import Go2RTCManager
manager = Go2RTCManager("C:\\go2rtc")
manager.start()
```

**Threading model (3 threads):**
1. **Main thread** — your inference loop calls `stream.read()`
2. **Reader thread** — continuously reads from `cv2.VideoCapture`, pushes to a `queue.Queue`
3. **Watchdog thread** — every 5s checks if frames are still arriving; triggers reconnect if stale

**Key features:**
- `buffer_size=30` — frame queue capacity (trade-off: larger = smoother, smaller = lower latency)
- `hardware_decode=True` — sets `cv2.CAP_PROP_HW_ACCELERATION = D3D11`
- `max_reconnect_attempts=5` — with `reconnect_delay=2.0s` between tries
- `enable_watchdog=True` — automatically detects stale streams and reconnects
- `timeout=10` — if no frame arrives for 10s, watchdog triggers reconnect

### 7. Full Integration (Go2RTCManager + VideoStream + YOLO)

**File:** `integration_example.py`

```python
from video_stream import VideoStream, Go2RTCManager

# 1. Start go2rtc if not already running
go2rtc = Go2RTCManager("C:\\go2rtc")
if not go2rtc.is_running():
    go2rtc.start()
    time.sleep(3)

# 2. Open RTSP stream (go2rtc must be running first)
stream = VideoStream("rtsp://localhost:554/warehouse_main")

# 3. Read frames in loop
while stream.is_open():
    ret, frame = stream.read()
    if ret:
        # Run YOLO inference
        results = model(frame)
```

### 8. Alternative: Native DVRIP (Bypass go2rtc)

For cases where go2rtc is not desired, the project also includes a **pure-Python DVRIP client**:

- `tvs_dvrip.py` — standalone DVRIP client (SofiaHash auth, monitor stream, H.265 parsing)
- `dvrip_capture.py` — `cv2.VideoCapture`-compatible adapter using `tvs_dvrip` + PyAV decoder
- `dvrip_adapter.py` — simplified wrapper

These use **no RTSP, no go2rtc, no FFmpeg** — connect directly to the NVR over raw TCP.

### 9. Testing

**File:** `stream_test.py`

Run: `python stream_test.py`

Tests:
1. go2rtc startup
2. DVRIP connectivity (URL format)
3. RTSP stream reception (5+ frames)
4. OpenCV compatibility
5. PyAV compatibility (if installed)
6. FFmpeg compatibility
7. Frame integrity (no duplicates)
8. Timestamp continuity

**File:** `benchmark_streams.py`

Run: `python benchmark_streams.py`

Measures: FPS, bandwidth (Mbps), decode latency (ms), frame drop rate (%)

### 10. Monitoring & Debugging

**HTTP API (go2rtc):**
```bash
# List all streams
curl http://localhost:1476/api/streams

# Get specific stream info
curl http://localhost:1476/api/streams/warehouse_main
```

**WebRTC (browser viewing):**
Open `http://localhost:1476/webrtc?src=warehouse_main`

**Logs:**
- go2rtc console output (stdout)
- `C:\go2rtc\go2rtc.log` (if redirect configured)
- `pipeline.log` (Python application log)
- `VideoStream.stats.to_dict()` — programmatic stats

### 11. Troubleshooting Checklist

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `[dvrip] connect: dial tcp 192.168.1.35:34567: connectex: No connection could be made` | NVR unreachable | Check IP, network, firewall |
| `go2rtc.exe not found` | Not installed | Run `C:\go2rtc\install.bat` |
| Frames not arriving (Python) | go2rtc not running | Start go2rtc first, then VideoStream |
| `Access Denied C:\Windows\System32\go2rtc.yaml` | Wrong working directory | Run from `C:\go2rtc\` |
| Low FPS / frame drops | Buffer too small or network | Increase `buffer_size`, check WiFi vs Ethernet |
| `[warehouse_main] stream error` | DVRIP credentials wrong | Verify username/password in `go2rtc.yaml` |

### 12. Required Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 34567 | TCP (DVRIP) | NVR → go2rtc (inbound to NVR) |
| 554 | TCP (RTSP) | go2rtc → Python (outbound) |
| 8555 | TCP/UDP (WebRTC) | go2rtc → browser |
| 1476 | TCP (HTTP) | go2rtc API |

### 13. Key Files Reference

| File | Purpose |
|------|---------|
| `C:\go2rtc\go2rtc.exe` | go2rtc binary (v1.9.14) |
| `C:\go2rtc\go2rtc.yaml` | Stream configuration |
| `C:\go2rtc\start.bat` | Windows batch launcher |
| `C:\go2rtc\install.bat` | Automated installer |
| `video_stream.py` | VideoStream + Go2RTCManager classes |
| `integration_example.py` | Full pipeline example (YOLO + ByteTrack) |
| `stream_test.py` | Test suite (7+ tests) |
| `benchmark_streams.py` | Performance benchmarking |
| `tvs_dvrip.py` | Native DVRIP client (bypass go2rtc) |
| `DVRIP_PROTOCOL.md` | DVRIP protocol documentation |

### 14. Summary: What Makes It Work

```
NVR (DVRIP) → go2rtc (converts to RTSP) → Python VideoStream (reads & buffers) → YOLO (detects boxes)
```

The **critical dependency chain** is:

1. **NVR must be accessible** on `192.168.1.35:34567`
2. **go2rtc must be running** *before* Python tries to connect
3. **DVRIP credentials** in `go2rtc.yaml` must match NVR
4. **Channel number** in config must match the camera you want
5. **Python consumes `rtsp://localhost:554/warehouse_main`** — the stream name must match config

If any link breaks, the pipeline fails. The `Go2RTCManager` class helps manage the go2rtc lifecycle from Python, and the `VideoStream` watchdog handles reconnection transparently.
