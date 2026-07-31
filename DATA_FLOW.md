# Live Stream Counting & Detection — Full Data Flow

System: warehouse box counting via YOLO on GPU, **direct DVRIP / RTSP camera feed**
(no go2rtc), web-served annotated streams.

---

## 1. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          AI ENGINE  (backend/server.py)                  │
│  uvicorn 0.0.0.0:8000                                                    │
│                                                                          │
│  Main process                                                           │
│  ├─ StreamManager  →  CameraStream / RtspCameraStream  (capture)         │
│  ├─ CameraManager  →  per-camera CameraWorker processes  (detection)     │
│  ├─ EventConsumer  →  detection events (queue → processing)             │
│  ├─ VMS sync thread  →  polls business backend, (re)starts streams       │
│  └─ FastAPI endpoints →  WS live stream, MJPEG, health, reset            │
│                                                                          │
│  Shared RAM: FrameStore (JPEG + raw frames per camera)                   │
└──────────────────────────────────────────────────────────────────────────┘
        │                          ▲
        │ DVRIP / RTSP             │ JSON (counts, health)
        ▼                          │
┌───────────────┐         ┌─────────────────────┐
│  NVR / camera │         │ BUSINESS BACKEND    │
│  (host:34567) │         │ (0.0.0.0:8001, Django/FastAPI) │
└───────────────┘         └─────────────────────┘
```

| Component | Process | Responsibility |
|---|---|---|
| `StreamManager` / `CameraStream` / `RtspCameraStream` | capture thread(s) in main process | Connect directly to camera (DVRIP via FFmpeg, or native RTSP), decode → JPEG → RAM FrameStore + WebSocket subscribers. Never blocks. |
| `CameraManager` | parent + 1 worker process per camera | Spawn/monitor/restart `CameraWorker` processes; shared `Manager.dict()` health + reset flags. |
| `CameraWorker` | 1 process per camera | Pull newest frame from FrameStore, run YOLO, track, filter by ROI, count line crossings, draw annotations, publish annotated JPEG to FrameStore. |
| `EventConsumer` | thread | Drain detection events from the queue. |
| FastAPI | async event loop | Serve WS / MJPEG / health / cameras / reset endpoints. Never does heavy work. |

---

## 2. Startup Sequence

### 2.1 Server boot (`backend/server.py`)
1. Forces `multiprocessing` start method to **spawn**, sets OpenCV FFmpeg capture options (TCP transport, timeouts).
2. Creates `CameraManager`, `FrameStore`, `StreamManager`.
3. Validates `INTERNAL_API_KEY` is set (required for cross-service auth).
4. Startup: `create_tables()` → `camera_manager.start_all()` (creates Manager, EventConsumer, monitor thread) → starts the **VMS sync thread**.
5. Shutdown: `stream_manager.stop_all()` → `camera_manager.stop_all()`.

### 2.2 VMS sync loop (`sync_cameras_loop`)
Every 10 s, polls the business backend
`GET /api/v1/cameras/internal/active` (with `X-Internal-Key`), then:

1. For each active camera, routes by URL scheme via `_route_camera`:
   - `dvrip://user:pass@host:port/channel` → `stream_manager.start_camera(...)` → `CameraStream` (direct DVRIP).
   - `rtsp://...` → `stream_manager.start_camera_rtsp(...)` → `RtspCameraStream` (direct RTSP).
   - anything else → skipped with warning. **go2rtc is never involved.**
2. Starts/restarts the detection worker with config `{source_type: "file_store", model_path, roi, count_line, detection_conf, count_conf, ...}`.
3. Worker restarts when `_config_hash` changes (model / ROI / count_line / source / thresholds). `_config_hash` covers `model_path, roi, count_line, source_type, source, detection_conf, count_conf`.
4. Dead cameras are retried on the next pass.
5. Cameras no longer active (or streams no longer active) are stopped.

---

## 3. Capture — direct DVRIP / RTSP (`stream_manager.py`)

```
StreamManager.start_camera(camera_id, host, port, username, password, channel)
  └─ CameraStream (thread)
       ├─ NvrConnectionScheduler: per-NVR connection cap (avoid hitting NVR limits)
       ├─ _connect(): FFmpeg av.open(dvrip://.../ch=channel) — direct to NVR
       ├─ _read_loop(): decode H.264/H.265 → BGR → JPEG
       └─ _distribute_jpeg(): publish_bytes → RAM FrameStore (+ WS subscribers)

StreamManager.start_camera_rtsp(camera_id, rtsp_url)
  └─ RtspCameraStream (thread)
       └─ FFmpeg av.open(rtsp://...) → JPEG → FrameStore (+ WS subscribers)
```

Key properties:
- **Capture and detection never block each other.** Streams decode in the main
  process; detection runs in separate worker processes.
- Both stream types write the same RAM `FrameStore`, so detection workers are
  source-agnostic (`source_type: "file_store"`).
- `NvrConnectionScheduler` throttles concurrent connections per NVR host.

---

## 4. Detection & Counting — `CameraWorker` (1 process per camera)

### 4.1 Main loop
```
while running:
    _check_reset_flag()          # zero counters if reset requested
    ret, frame = _read_frame()   # FrameStore latest raw / JPEG decode
        └─ black-frame guard: >98% pixels <15 → treated as video loss
    if frame:
        events, vis_boxes = _process_frame(frame)
        publish annotated JPEG → FrameStore (for WS / MJPEG)
        put events on event_queue
        every 30 frames: report health (frames, counted, line_count, …)
    else:
        reconnect with exponential backoff; report "reconnecting"/"dead"
    sleep to hit target_fps
```

### 4.2 `_process_frame`
1. `_apply_roi()` — zero out pixels outside the configured ROI polygon (normalized points → pixel mask).
2. Run `BoxDetector.detect()` (YOLO ONNX) — conf threshold `detection_conf`.
3. ROI center test — drop boxes whose center falls outside the ROI polygon.
4. `BoxProcessor.process_detections()` → `ObjectTracker.update()` (ByteTrack).
5. `_update_line_counter()` — if `count_line` configured (2 normalized points):
   `LineCounter.set_line(p1, p2)` then `update(tracked)`; counts a box when its
   center crosses the segment, direction-aware, **once per track** → `line_count`.
6. New-track counting — a track seen for the first time with
   `confidence ≥ count_conf` increments `total_count` and emits a detection event.
7. Builds `vis_boxes` (x1,y1,x2,y2,label,confidence) for the overlay.

### 4.3 Counting semantics
| Counter | Mechanism |
|---|---|
| `total_count` | Legacy count: incremented on **new track** with conf ≥ `count_conf`. |
| `line_count` | Visual count-line stat: `LineCounter` segment mode counts a box each time its center **crosses the configured segment**, once per track. |

`LineCounter` supports both modes at runtime — horizontal line (`line_y` +
hysteresis → `total_count`) and 2-point segment (`p1`, `p2` → `line_count`) —
chosen by the presence of `count_line` points.

### 4.4 Overlay
- ROI polygon (yellow outline), count-line segment (**magenta**).
- Per-box green rectangle + `#<track> <conf%>` label.
- `Count: N` (red) and `Line: N` (magenta) text.

---

## 5. Worker Supervision & Reset (`camera_manager.py`)

- `CameraManager` keeps shared `Manager.dict()` `_health` and `_reset_flags`.
- Monitor thread checks every 2 s: dead worker → restart with 15 s backoff;
  health stale >45 s → restart. `status: "dead"` (init failed) → never restarted.
- **Reset flow:**
```
Business backend:  POST /cameras/{camera_uuid}/reset
   └─ AI engine:    POST /api/v1/reset/{camera_id}   (X-Internal-Key)
        └─ CameraManager.reset_camera(camera_id) → sets _reset_flags[camera_id]
             └─ CameraWorker._check_reset_flag() → reset_state()
                  - clears _seen_tracks, DuplicateGuard, LineCounter(s)
                  - health counted / line_count → 0
```

---

## 6. Serving (`server.py` endpoints)

| Method | Path | Function |
|---|---|---|
| WS | `/api/v1/stream/ws/{camera_id}` | Binary frames (4-byte LE length + annotated JPEG) from FrameStore. `?key=` optional. |
| GET | `/api/v1/stream/{camera_id}` | MJPEG fallback (for `<img>` tags) — reads annotated JPEG from FrameStore. |
| GET | `/api/v1/cameras` | Worker health + stream status (`X-Internal-Key`). |
| POST | `/api/v1/reset/{camera_id}` | Zero counters via reset flag (`X-Internal-Key`). |

`/api/v1/cameras/internal/active` and the reset proxy live on the **business
backend**; the AI engine's own routes are internal-key protected.

---

## 7. Frame Lifecycle (end to end)

```
NVR / camera (dvrip:// or rtsp://)
   ▼
CameraStream / RtspCameraStream (FFmpeg decode → JPEG)   [main process]
   ▼
RAM FrameStore (publish_bytes / latest_raw_frame)
   ▼
CameraWorker: _read_frame → YOLO detect → ROI filter → track   [worker process]
   ▼
count_line crossing? → line_count += 1          | new track? → total_count += 1
   ▼
draw overlays → publish_annotated → FrameStore
   ▼
WS / MJPEG endpoint → browser dashboard (frontend)
   ▼
health / counts surfaced in dashboard camera cards
```

---

## 8. Failure Handling

| Failure | Behaviour |
|---|---|
| NVR / camera unreachable | Stream thread reconnects with backoff; worker reports `reconnecting`, then `dead` after 60 attempts. |
| Worker crashes | Monitor thread restarts it (15 s backoff). `init_failed` → not restarted. |
| Health stale >45 s | Monitor thread restarts the worker. |
| Black frame / video-loss text overlay | Dark-frame guard treats as no frame → reconnect path. |
| No annotated frame yet | WS/MJPEG wait for FrameStore (no raw fallback on WS). |
| Model not configured | Worker runs stream-only mode (no detection). |
| `INTERNAL_API_KEY` missing | Server refuses to boot. |

---

## 9. Config

Camera config pushed from the business backend (`Camera` model) via the sync loop:

| Key | Source | Meaning |
|---|---|---|
| `stream_url` | Camera | `dvrip://user:pass@host:port/channel` or `rtsp://…` — used for capture routing only. |
| `model_path` | Camera | YOLO weights; `""` → stream-only mode. |
| `roi` | Camera | Normalized polygon points `[{x,y}, …]` (≥3). |
| `count_line` | Camera | Normalized segment `[{x,y}, …]` (exactly 2) for `line_count`. |
| `detection_conf` / `count_conf` | AI engine | YOLO conf; new-track counting threshold. |
| `target_fps` | AI engine | Worker loop pacing (default 5). |

## 10. File Map

| File | Responsibility |
|---|---|
| `backend/server.py` | FastAPI app, VMS sync loop, `_route_camera`, WS/MJPEG/reset endpoints. |
| `backend/cv_engine/orchestration/camera_manager.py` | Worker process pool, health/reset flags, monitor+restart. |
| `backend/cv_engine/orchestration/camera_worker.py` | YOLO detection, tracking, ROI, count-line, overlays, reset. |
| `backend/cv_engine/orchestration/stream_manager.py` | `CameraStream` (DVRIP) + `RtspCameraStream` (RTSP) capture threads. |
| `backend/cv_engine/orchestration/frame_store.py` | RAM store: JPEG + latest raw frame per camera. |
| `backend/cv_engine/orchestration/event_consumer.py` | Detection event drain. |
| `backend/cv_engine/services/line_counter.py` | Line counting: horizontal (`line_y`) and segment (`p1`,`p2`) modes. |
| `backend/cv_engine/services/duplicate_guard.py` | Anti-double-count guard (`reset()`). |
| `backend/cv_engine/services/detector.py` | YOLO ONNX inference (BoxDetector). |
| `backend/cv_engine/services/tracker.py` | ObjectTracker (ByteTrack). |
| `business-backend/app/routes/cameras.py` | Camera CRUD, internal/active list, reset proxy. |
| `business-backend/app/models/camera.py` | `Camera` model incl. `roi`, `count_line`, `model_path`. |
| `frontend/src/app/dashboard/cameras/page.tsx` | Camera cards: ROI/Count-Line badges, Reset Count, live WS streams. |
