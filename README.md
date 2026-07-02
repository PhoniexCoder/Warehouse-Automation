# Warehouse AI — Phase 1 MVP

AI-powered warehouse monitoring and box counting system. Detects boxes from video/RTSP streams, decodes QR codes, tracks objects across frames, and counts them when crossing a virtual line.

## Architecture

```
Video Input → YOLO Detection → QR Decode → Spatial Association
                                                    ↓
              SQLite ← Detection Logger ← Line Counter ← ByteTrack Tracking
                                                    ↓
                                            FastAPI (GET/POST)
                                                    ↓
                                           OpenCV Display Overlay
```

## Quick Start

### Install

```bash
pip install -r requirements.txt
```

Download a YOLO model:

```bash
python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"
mv yolo11n.pt models/
```

### Run

```bash
# Webcam
python backend/main.py --source 0

# Video file
python backend/main.py --source videos/sample.mp4

# RTSP stream
python backend/main.py --source rtsp://user:pass@192.168.1.100:554/stream1

# API only (no video processing)
python backend/main.py --api-only

# No display window (headless)
python backend/main.py --source videos/sample.mp4 --no-display
```

### Docker

```bash
docker compose -f docker/docker-compose.yml up warehouse-ai-cpu
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/log-detection` | Manually log a detection |
| GET | `/detections` | List logged detections |
| GET | `/current-count` | Get current box count |
| GET | `/health` | Health check |

## Project Structure

```
warehouse-ai/
├── backend/
│   ├── cv_engine/
│   │   ├── config/settings.py      # Configuration constants
│   │   ├── models/detection_models.py  # Data classes
│   │   ├── services/
│   │   │   ├── detector.py         # YOLO box detection
│   │   │   ├── qr_reader.py        # QR decode (OpenCV + pyzbar)
│   │   │   ├── tracker.py          # ByteTrack tracking
│   │   │   ├── association.py      # QR-to-box spatial linking
│   │   │   ├── line_counter.py     # Virtual line crossing
│   │   │   └── logger.py           # Detection persistence
│   │   ├── database.py             # SQLite CRUD
│   │   └── pipeline.py             # Pipeline orchestrator
│   ├── main.py                     # FastAPI + video loop
│   └── tests/
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── models/          # YOLO weights
├── videos/          # Sample videos
├── data/            # SQLite database
└── requirements.txt
```

## Tests

```bash
pip install pytest pytest-mock
cd backend && python -m pytest tests/ -v
```
