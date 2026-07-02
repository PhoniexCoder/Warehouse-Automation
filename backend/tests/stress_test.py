"""
Pipeline stress test harness.

Generates synthetic warehouse video scenarios with embedded QR codes and
known ground truth, then runs the full detection pipeline, collecting
performance metrics, detection accuracy, QR decode rates, tracker
consistency, and duplicate-count errors.

Usage:
    python -m tests.stress_test                    # run all scenarios
    python -m tests.stress_test --scenario low_light  # single scenario
    python -m tests.stress_test --frames 200       # override frame count
"""

import argparse
import json
import logging
import os
import sys
import time
import statistics
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Generator, Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cv_engine.services.detector import BoxDetector
from cv_engine.services.qr_reader import QRReader
from cv_engine.services.association import AssociationEngine
from cv_engine.services.tracker import ObjectTracker
from cv_engine.services.line_counter import LineCounter
from cv_engine.database import reset_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
LOGGER = logging.getLogger("stress_test")
LOG_DIR = Path(__file__).resolve().parent / "stress_logs"

try:
    from qrcode import QRCode as _QRCode, constants as _QRConst
except ImportError:
    _QRCode = None

# ---------------------------------------------------------------------------
# Synthetic frame generator
# ---------------------------------------------------------------------------

_FRAME_W = 640
_FRAME_H = 480
_BG_COLOR = 200
_BOX_COLORS = [
    (0, 0, 255),
    (0, 255, 0),
    (255, 0, 0),
    (0, 255, 255),
    (255, 0, 255),
]


def _make_qr_image(data: str, cell_size: int = 3) -> Optional[np.ndarray]:
    if _QRCode is None:
        return None
    qr = _QRCode(version=1, box_size=cell_size, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    arr = np.array(img.convert("RGB"), dtype=np.uint8)
    return arr


def _paste_image(
    canvas: np.ndarray, overlay: np.ndarray, x: int, y: int,
) -> np.ndarray:
    oh, ow = overlay.shape[:2]
    ch, cw = canvas.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(cw, x + ow)
    y2 = min(ch, y + oh)
    ox = x1 - x
    oy = y1 - y
    roi = overlay[oy : oy + (y2 - y1), ox : ox + (x2 - x1)]
    mask = np.all(roi < 50, axis=2)
    canvas[y1:y2, x1:x2][mask] = roi[mask]
    return canvas


def _empty_frame(h: int = _FRAME_H, w: int = _FRAME_W) -> np.ndarray:
    return np.full((h, w, 3), _BG_COLOR, dtype=np.uint8)


def _draw_box(
    frame: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color,
    label: str = "",
) -> None:
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, -1)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (30, 30, 30), 2)
    if label:
        cv2.putText(
            frame, label, (x1 + 6, y1 + 24),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA,
        )


# ---------------------------------------------------------------------------
# Scenario generators
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    name: str
    description: str
    total_frames: int
    processed_frames: int
    avg_fps: float
    avg_inference_ms: float
    avg_total_latency_ms: float
    detection_rate: float
    avg_detections_per_frame: float
    qr_decode_rate: float
    qr_false_positives: int
    tracker_consistency: float
    duplicate_errors: int
    max_consecutive_drops: int


def _gen_low_light(
    n_frames: int,
) -> Generator[tuple[np.ndarray, dict], None, None]:
    qr_img = _make_qr_image("LOW-LIGHT-001")
    for i in range(n_frames):
        frame = _empty_frame()
        _draw_box(frame, 120, 80, 360, 320, _BOX_COLORS[0], "LOW-LIGHT-001")
        if qr_img is not None:
            _paste_image(frame, qr_img, 180, 140)
        dark = cv2.convertScaleAbs(frame, alpha=0.25, beta=0)
        gt = {
            "boxes": [{"bbox": [120, 80, 360, 320], "label": "LOW-LIGHT-001"}],
            "qrs": [{"data": "LOW-LIGHT-001", "bbox": [180, 140, 180 + qr_img.shape[1], 140 + qr_img.shape[0]]}] if qr_img is not None else [],
        }
        yield dark, gt


def _gen_motion_blur(
    n_frames: int,
) -> Generator[tuple[np.ndarray, dict], None, None]:
    qr_img = _make_qr_image("BLUR-001")
    for i in range(n_frames):
        frame = _empty_frame()
        offset_x = int(100 + 300 * (i / n_frames))
        _draw_box(frame, offset_x, 120, offset_x + 200, 340, _BOX_COLORS[1], "BLUR-001")
        if qr_img is not None:
            _paste_image(frame, qr_img, offset_x + 40, 170)
        k = 11
        kernel = np.zeros((k, k), dtype=np.float32)
        kernel[k // 2, :] = 1.0 / k
        blurred = cv2.filter2D(frame, -1, kernel)
        gt = {
            "boxes": [{"bbox": [offset_x, 120, offset_x + 200, 340], "label": "BLUR-001"}],
            "qrs": [{"data": "BLUR-001", "bbox": [offset_x + 40, 170, offset_x + 40 + qr_img.shape[1], 170 + qr_img.shape[0]]}] if qr_img is not None else [],
        }
        yield blurred, gt


def _gen_partial_visible(
    n_frames: int,
) -> Generator[tuple[np.ndarray, dict], None, None]:
    qr_img = _make_qr_image("PARTIAL-001")
    boxes_gt = []
    qrs_gt = []
    for i in range(n_frames):
        frame = _empty_frame()
        phase = (i % 60) / 60.0
        x1 = int(-80 + 240 * phase)
        y1 = 100
        x2 = x1 + 240
        y2 = y1 + 240
        _draw_box(frame, max(0, x1), y1, x2, y2, _BOX_COLORS[2], "PARTIAL-001")
        if qr_img is not None and x1 + 40 >= 0:
            _paste_image(frame, qr_img, max(0, x1 + 40), y1 + 60)
        gt = {
            "boxes": [{"bbox": [max(0, x1), y1, x2, y2], "label": "PARTIAL-001"}],
            "qrs": [{"data": "PARTIAL-001", "bbox": [max(0, x1 + 40), y1 + 60, max(0, x1 + 40) + qr_img.shape[1], y1 + 60 + qr_img.shape[0]]}] if qr_img is not None and x1 + 40 >= 0 else [],
        }
        yield frame, gt


def _gen_multiple_boxes(
    n_frames: int,
) -> Generator[tuple[np.ndarray, dict], None, None]:
    n_boxes = 5
    labels = [f"MULTI-{i:03d}" for i in range(n_boxes)]
    qr_imgs = [_make_qr_image(lbl) for lbl in labels]
    positions = [
        (50, 30, 180, 180),
        (250, 40, 380, 180),
        (430, 30, 560, 170),
        (80, 220, 220, 380),
        (340, 220, 500, 400),
    ]
    box_positions = list(positions)

    for i in range(n_frames):
        frame = _empty_frame()
        boxes_gt = []
        qrs_gt = []
        for idx, ((bx1, by1, bx2, by2), color, lbl, qr) in enumerate(
            zip(box_positions, _BOX_COLORS, labels, qr_imgs)
        ):
            offset = int(15 * (i % 30) / 30.0) if i % 2 == 0 else 0
            cx = (bx1 + bx2) // 2
            cy = (by1 + by2) // 2
            nx1 = bx1 + offset if idx % 2 == 0 else bx1 - offset
            ny1 = by1 + offset if idx % 3 == 0 else by1 - offset
            nx2 = nx1 + (bx2 - bx1)
            ny2 = ny1 + (by2 - by1)
            _draw_box(frame, nx1, ny1, nx2, ny2, color, lbl)
            boxes_gt.append({"bbox": [nx1, ny1, nx2, ny2], "label": lbl})
            if qr is not None:
                qx = nx1 + (nx2 - nx1 - qr.shape[1]) // 2
                qy = ny1 + 30
                _paste_image(frame, qr, qx, qy)
                qrs_gt.append({
                    "data": lbl,
                    "bbox": [qx, qy, qx + qr.shape[1], qy + qr.shape[0]],
                })
        gt = {"boxes": boxes_gt, "qrs": qrs_gt}
        yield frame, gt


def _gen_overlapping(
    n_frames: int,
) -> Generator[tuple[np.ndarray, dict], None, None]:
    qr_a = _make_qr_image("OVERLAP-A")
    qr_b = _make_qr_image("OVERLAP-B")
    for i in range(n_frames):
        frame = _empty_frame()
        offset = int(40 * ((i % 30) / 30.0))
        _draw_box(frame, 120, 100, 400, 340, _BOX_COLORS[3], "OVERLAP-A")
        _draw_box(frame, 180 + offset, 140, 440 + offset, 380, _BOX_COLORS[4], "OVERLAP-B")
        if qr_a is not None:
            _paste_image(frame, qr_a, 160, 140)
        if qr_b is not None:
            _paste_image(frame, qr_b, 240 + offset, 190)
        gt = {
            "boxes": [
                {"bbox": [120, 100, 400, 340], "label": "OVERLAP-A"},
                {"bbox": [180 + offset, 140, 440 + offset, 380], "label": "OVERLAP-B"},
            ],
            "qrs": [
                {"data": "OVERLAP-A", "bbox": [160, 140, 160 + qr_a.shape[1], 140 + qr_a.shape[0]]},
                {"data": "OVERLAP-B", "bbox": [240 + offset, 190, 240 + offset + qr_b.shape[1], 190 + qr_b.shape[0]]},
            ] if qr_a is not None and qr_b is not None else [],
        }
        yield frame, gt


# ---------------------------------------------------------------------------
# Metrics Collector
# ---------------------------------------------------------------------------

@dataclass
class FrameMetrics:
    inference_ms: float = 0.0
    total_latency_ms: float = 0.0
    n_detections: int = 0
    qr_decoded: list[str] = field(default_factory=list)
    qr_in_gt: list[str] = field(default_factory=list)
    track_ids: list[int] = field(default_factory=list)
    duplicate_count: bool = False


class MetricsCollector:
    def __init__(self) -> None:
        self._frames: list[FrameMetrics] = []

    def record(self, m: FrameMetrics) -> None:
        self._frames.append(m)

    @property
    def count(self) -> int:
        return len(self._frames)

    def avg_fps(self) -> float:
        if self.count < 2:
            return 0.0
        total_time = sum(f.total_latency_ms for f in self._frames) / 1000.0
        return self.count / total_time if total_time > 0 else 0.0

    def avg_inference_ms(self) -> float:
        vals = [f.inference_ms for f in self._frames if f.inference_ms > 0]
        return statistics.mean(vals) if vals else 0.0

    def avg_total_latency_ms(self) -> float:
        vals = [f.total_latency_ms for f in self._frames if f.total_latency_ms > 0]
        return statistics.mean(vals) if vals else 0.0

    def detection_rate(self) -> float:
        if not self._frames:
            return 0.0
        with_dets = sum(1 for f in self._frames if f.n_detections > 0)
        return with_dets / len(self._frames)

    def avg_detections_per_frame(self) -> float:
        if not self._frames:
            return 0.0
        return statistics.mean(f.n_detections for f in self._frames)

    def qr_decode_rate(self) -> float:
        total_expected = sum(len(f.qr_in_gt) for f in self._frames)
        if total_expected == 0:
            return 1.0
        total_decoded = sum(len(f.qr_decoded) for f in self._frames)
        return total_decoded / total_expected

    def qr_false_positives(self) -> int:
        fps = 0
        for f in self._frames:
            decoded_set = set(f.qr_decoded)
            gt_set = set(f.qr_in_gt)
            fps += len(decoded_set - gt_set)
        return fps

    def tracker_consistency(self) -> float:
        track_appearances: dict[int, int] = {}
        for f in self._frames:
            for tid in f.track_ids:
                track_appearances[tid] = track_appearances.get(tid, 0) + 1
        if not track_appearances:
            return 1.0
        max_appearances = max(track_appearances.values())
        total_tracks = sum(track_appearances.values())
        avg_lifetime = total_tracks / len(track_appearances)
        ideal = max_appearances * len(track_appearances)
        return avg_lifetime / (self.count) if self.count > 0 else 1.0

    def duplicate_errors(self) -> int:
        return sum(1 for f in self._frames if f.duplicate_count)

    def max_consecutive_drops(self) -> int:
        best = 0
        curr = 0
        for f in self._frames:
            if f.n_detections == 0 and not f.track_ids:
                curr += 1
                best = max(best, curr)
            else:
                curr = 0
        return best

    def to_result(self, name: str, description: str) -> ScenarioResult:
        return ScenarioResult(
            name=name,
            description=description,
            total_frames=len(self._frames),
            processed_frames=self.count,
            avg_fps=round(self.avg_fps(), 1),
            avg_inference_ms=round(self.avg_inference_ms(), 1),
            avg_total_latency_ms=round(self.avg_total_latency_ms(), 1),
            detection_rate=round(self.detection_rate(), 3),
            avg_detections_per_frame=round(self.avg_detections_per_frame(), 2),
            qr_decode_rate=round(self.qr_decode_rate(), 3),
            qr_false_positives=self.qr_false_positives(),
            tracker_consistency=round(self.tracker_consistency(), 3),
            duplicate_errors=self.duplicate_errors(),
            max_consecutive_drops=self.max_consecutive_drops(),
        )


# ---------------------------------------------------------------------------
# Stress Test Runner
# ---------------------------------------------------------------------------

SCENARIOS = {
    "low_light": ("Darkened frames (alpha=0.25)", _gen_low_light),
    "motion_blur": ("Horizontal motion blur (kernel=11)", _gen_motion_blur),
    "partial_visible": ("Boxes entering/exiting frame edges", _gen_partial_visible),
    "multiple_boxes": ("Five independent boxes with QR codes", _gen_multiple_boxes),
    "overlapping": ("Two boxes with partial overlap", _gen_overlapping),
}


class StressTestRunner:
    def __init__(self, n_frames: int = 150, log_dir: Path = LOG_DIR) -> None:
        self._n_frames = n_frames
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)

        LOGGER.info("Initialising pipeline components for stress test ...")
        self._detector = None
        self._qr_reader = QRReader()
        self._tracker = ObjectTracker(method="deepsort")
        self._association = AssociationEngine()
        self._line_counter = LineCounter(line_y=400)

    def _ensure_detector(self) -> BoxDetector:
        if self._detector is None:
            model_candidates = [
                Path.cwd() / "models" / "best.pt",
                Path.cwd().parent / "models" / "best.pt",
                Path(__file__).resolve().parents[2] / "models" / "best.pt",
            ]
            model_path = None
            for p in model_candidates:
                if p.exists():
                    model_path = str(p)
                    break
            if model_path is None:
                LOGGER.warning("models/best.pt not found — detector stress tests will be limited")
                self._detector = None
            else:
                from cv_engine.services.detector import BoxDetector
                self._detector = BoxDetector(model_path=model_path, device="cpu")
        return self._detector

    # ------------------------------------------------------------------
    # Component-level stress tests (directly test tracker, association,
    # line counter with realistic synthetic data)
    # ------------------------------------------------------------------

    def _run_tracker_stress(self) -> ScenarioResult:
        LOGGER.info("Running component stress: tracker_consistency")
        self._tracker.reset()
        n_frames = 100
        collector = MetricsCollector()
        box_1 = [100, 100, 200, 200]
        box_2 = [300, 100, 400, 200]
        step_x = [2, -2]
        for i in range(n_frames):
            m = FrameMetrics()
            box_1[0] += step_x[0]
            box_1[2] += step_x[0]
            box_2[0] += step_x[1]
            box_2[2] += step_x[1]
            dets = [
                {"bbox": list(box_1), "confidence": 0.9, "class": "Regular_Box"},
                {"bbox": list(box_2), "confidence": 0.85, "class": "Regular_Box"},
            ]
            dummy = np.zeros((480, 640, 3), dtype=np.uint8)
            tracked = self._tracker.update(dets, dummy)
            m.n_detections = len(tracked)
            m.track_ids = [t["track_id"] for t in tracked]
            m.inference_ms = 0.0
            m.total_latency_ms = 0.0
            collector.record(m)
        result = collector.to_result(
            "tracker_stress", "100 frames, 2 moving boxes, DeepSORT",
        )
        LOGGER.info("  Done — consistency=%.3f, avg_tracks=%.1f",
                     result.tracker_consistency,
                     result.avg_detections_per_frame)
        return result

    def _run_association_stress(self) -> ScenarioResult:
        LOGGER.info("Running component stress: association_accuracy")
        n_frames = 100
        collector = MetricsCollector()
        box = [100, 100, 300, 300]
        for i in range(n_frames):
            m = FrameMetrics()
            offset = (i % 30) * 2
            qr_bbox = [150 + offset, 150, 250 + offset, 250]
            qr_center_x = (qr_bbox[0] + qr_bbox[2]) / 2.0
            inside = (box[0] <= qr_center_x <= box[2])
            dets = [{"bbox": list(box), "confidence": 0.9, "track_id": 101}]
            qrs = [{"data": "STRESS-QR", "bbox": qr_bbox}]
            result = self._association.associate(qrs, dets)
            m.qr_in_gt = ["STRESS-QR"]
            if inside and result[0].get("qr_data") == "STRESS-QR":
                m.qr_decoded = ["STRESS-QR"]
            elif not inside and result[0].get("qr_data") is None:
                m.qr_decoded = []
            m.n_detections = 1
            m.inference_ms = 0.0
            m.total_latency_ms = 0.0
            collector.record(m)
        result = collector.to_result(
            "association_stress", "100 frames, QR slides in/out of box",
        )
        LOGGER.info("  Done — QR rate=%.1f%%", result.qr_decode_rate * 100)
        return result

    def _run_counter_stress(self) -> ScenarioResult:
        LOGGER.info("Running component stress: line_crossing")
        n_frames = 100
        collector = MetricsCollector()
        self._line_counter.reset()
        for i in range(n_frames):
            m = FrameMetrics()
            y = 200 + i * 5
            tracked = [{"track_id": 201, "bbox": [100, y, 200, y + 80]}]
            self._line_counter.update(tracked)
            already = self._line_counter.is_counted(201)
            if already:
                m.duplicate_count = False
            m.n_detections = 1
            m.track_ids = [201]
            m.inference_ms = 0.0
            m.total_latency_ms = 0.0
            collector.record(m)
        result = collector.to_result(
            "counter_stress", "100 frames, single box crossing line_y=400",
        )
        LOGGER.info("  Done — dupes=%d, final_count=%d",
                     result.duplicate_errors, self._line_counter.total_count)
        return result

    def _run_empty_throughput(self) -> ScenarioResult:
        LOGGER.info("Running component stress: empty_throughput")
        collector = MetricsCollector()
        for i in range(200):
            m = FrameMetrics()
            t0 = time.perf_counter()
            _ = self._qr_reader.detect_qr(np.zeros((480, 640, 3), dtype=np.uint8))
            m.total_latency_ms = (time.perf_counter() - t0) * 1000
            m.inference_ms = m.total_latency_ms
            collector.record(m)
        result = collector.to_result(
            "empty_throughput", "200 frames, empty input, QRReader only",
        )
        LOGGER.info("  Done — latency=%.2fms", result.avg_total_latency_ms)
        return result

    def run_scenario(
        self,
        name: str,
        generator,
        description: str,
    ) -> ScenarioResult:
        LOGGER.info("Running scenario: %s — %s", name, description)
        collector = MetricsCollector()
        frame_count = 0

        det = self._ensure_detector()
        self._line_counter.reset()
        self._tracker.reset()
        reset_database()

        cap_gen = generator(self._n_frames)

        for raw_frame, gt in cap_gen:
            frame_count += 1
            m = FrameMetrics()
            m.qr_in_gt = [q["data"] for q in gt.get("qrs", [])]

            t_start = time.perf_counter()

            inference_ms = 0.0
            detections = []
            if det is not None:
                t_inf = time.perf_counter()
                detections = det.detect(raw_frame)
                inference_ms = (time.perf_counter() - t_inf) * 1000

            m.n_detections = len(detections)
            m.inference_ms = inference_ms

            tracked = self._tracker.update(detections, raw_frame)
            m.track_ids = [t["track_id"] for t in tracked]

            qr_results = self._qr_reader.detect_qr(raw_frame)
            m.qr_decoded = [r["data"] for r in qr_results]

            tracked = self._association.associate(qr_results, tracked)

            self._line_counter.update(tracked)

            before_count = self._line_counter.total_count
            self._line_counter.update(tracked)
            after_count = self._line_counter.total_count
            m.duplicate_count = (after_count > before_count)

            m.total_latency_ms = (time.perf_counter() - t_start) * 1000

            collector.record(m)

            if frame_count % 50 == 0:
                LOGGER.info("  [%s] frame %d/%d", name, frame_count, self._n_frames)

        result = collector.to_result(name, description)
        LOGGER.info("  Done — FPS=%.1f, det_rate=%.1f%%, QR=%.1f%%, dupes=%d",
                     result.avg_fps, result.detection_rate * 100,
                     result.qr_decode_rate * 100, result.duplicate_errors)
        return result

    def run_all(self) -> dict[str, ScenarioResult]:
        results: dict[str, ScenarioResult] = {}
        for name, (desc, gen) in SCENARIOS.items():
            try:
                results[name] = self.run_scenario(name, gen, desc)
            except Exception as exc:
                LOGGER.exception("Scenario %s failed: %s", name, exc)
                results[name] = self._empty_result(name, desc)
        component_tests = [
            ("tracker_stress", self._run_tracker_stress),
            ("association_stress", self._run_association_stress),
            ("counter_stress", self._run_counter_stress),
            ("empty_throughput", self._run_empty_throughput),
        ]
        for name, fn in component_tests:
            try:
                results[name] = fn()
            except Exception as exc:
                LOGGER.exception("Component test %s failed: %s", name, exc)
                results[name] = self._empty_result(name, "")
        return results

    @staticmethod
    def _empty_result(name: str, desc: str) -> ScenarioResult:
        return ScenarioResult(
            name=name, description=desc,
            total_frames=0, processed_frames=0,
            avg_fps=0.0, avg_inference_ms=0.0, avg_total_latency_ms=0.0,
            detection_rate=0.0, avg_detections_per_frame=0.0,
            qr_decode_rate=0.0, qr_false_positives=0,
            tracker_consistency=0.0, duplicate_errors=0,
            max_consecutive_drops=0,
        )

    def generate_report(
        self,
        results: dict[str, ScenarioResult],
    ) -> dict:
        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "config": {
                "frames_per_scenario": self._n_frames,
                "frame_size": f"{_FRAME_W}x{_FRAME_H}",
            },
            "scenarios": {},
            "summary": {},
        }

        fps_list = []
        det_rate_list = []
        qr_rate_list = []
        dupe_total = 0
        inf_list = []
        lat_list = []

        for name, r in results.items():
            s = asdict(r)
            s.pop("name", None)
            s.pop("description", None)
            report["scenarios"][name] = s
            if r.processed_frames > 0:
                fps_list.append(r.avg_fps)
                det_rate_list.append(r.detection_rate)
                qr_rate_list.append(r.qr_decode_rate)
                dupe_total += r.duplicate_errors
                inf_list.append(r.avg_inference_ms)
                lat_list.append(r.avg_total_latency_ms)

        overall_qr = statistics.mean(qr_rate_list) if qr_rate_list else 0.0
        report["summary"] = {
            "scenarios_run": len(results),
            "average_fps": round(statistics.mean(fps_list), 1) if fps_list else 0.0,
            "average_inference_ms": round(statistics.mean(inf_list), 1) if inf_list else 0.0,
            "average_total_latency_ms": round(statistics.mean(lat_list), 1) if lat_list else 0.0,
            "overall_detection_rate": round(statistics.mean(det_rate_list), 3) if det_rate_list else 0.0,
            "overall_qr_decode_rate": round(overall_qr, 3),
            "qr_decode_percentage": f"{overall_qr * 100:.1f}%",
            "total_duplicate_errors": dupe_total,
            "worst_fps": round(min(fps_list), 1) if fps_list else 0.0,
            "best_fps": round(max(fps_list), 1) if fps_list else 0.0,
        }
        return report

    def save_report(self, report: dict) -> Path:
        path = self._log_dir / "stress_report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        LOGGER.info("Report saved: %s", path)
        return path

    def save_logs(self, results: dict[str, ScenarioResult]) -> None:
        summary_lines = [
            "=" * 60,
            "WAREHOUSE AI — STRESS TEST REPORT",
            "=" * 60,
            f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Frames per scenario: {self._n_frames}",
            "",
        ]
        for name, r in results.items():
            summary_lines.append(f"\n--- {name}: {r.description} ---")
            summary_lines.append(f"  Frames processed:   {r.processed_frames}")
            summary_lines.append(f"  Avg FPS:            {r.avg_fps:.1f}")
            summary_lines.append(f"  Avg inference ms:   {r.avg_inference_ms:.1f}")
            summary_lines.append(f"  Avg total latency:  {r.avg_total_latency_ms:.1f}")
            summary_lines.append(f"  Detection rate:     {r.detection_rate*100:.1f}%")
            summary_lines.append(f"  Avg dets/frame:     {r.avg_detections_per_frame:.2f}")
            summary_lines.append(f"  QR decode rate:     {r.qr_decode_rate*100:.1f}%")
            summary_lines.append(f"  QR false positives: {r.qr_false_positives}")
            summary_lines.append(f"  Tracker consistency:{r.tracker_consistency:.3f}")
            summary_lines.append(f"  Duplicate errors:   {r.duplicate_errors}")
            summary_lines.append(f"  Max consecutive drops:{r.max_consecutive_drops}")

        path = self._log_dir / "stress_report.txt"
        path.write_text("\n".join(summary_lines), encoding="utf-8")
        LOGGER.info("Log saved: %s", path)

    def print_summary(self, results: dict[str, ScenarioResult]) -> None:
        print(f"\n{'='*60}")
        print(f"  WAREHOUSE AI — STRESS TEST RESULTS")
        print(f"{'='*60}")
        header = f"{'Scenario':<20} {'FPS':<7} {'Inf(ms)':<9} {'Det%':<7} {'QR%':<7} {'Dupes':<7} {'Drop':<5}"
        print(header)
        print("-" * len(header))
        for name, r in results.items():
            print(
                f"{name:<20} {r.avg_fps:<7.1f} {r.avg_inference_ms:<9.1f} "
                f"{r.detection_rate*100:<6.1f}% {r.qr_decode_rate*100:<6.1f}% "
                f"{r.duplicate_errors:<7} {r.max_consecutive_drops:<5}"
            )
        print("-" * len(header))

        fps_list = [r.avg_fps for r in results.values() if r.processed_frames > 0]
        qr_list = [r.qr_decode_rate for r in results.values() if r.processed_frames > 0]
        dupe_total = sum(r.duplicate_errors for r in results.values())
        if fps_list:
            print(f"\n  Average FPS:          {statistics.mean(fps_list):.1f}")
        if qr_list:
            print(f"  Overall QR decode:    {statistics.mean(qr_list)*100:.1f}%")
        print(f"  Total duplicate errs: {dupe_total}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Warehouse AI — Stress Test Harness")
    parser.add_argument("--scenario", type=str, default=None,
                        choices=list(SCENARIOS.keys()) + ["all"],
                        help="Run a specific scenario or all")
    parser.add_argument("--frames", type=int, default=150,
                        help="Number of frames per scenario")
    parser.add_argument("--log-dir", type=str, default=str(LOG_DIR),
                        help="Output directory for logs and report")
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    runner = StressTestRunner(n_frames=args.frames, log_dir=log_dir)

    if args.scenario and args.scenario != "all":
        desc, gen = SCENARIOS[args.scenario]
        results = {args.scenario: runner.run_scenario(args.scenario, gen, desc)}
    else:
        results = runner.run_all()

    runner.print_summary(results)
    report = runner.generate_report(results)
    runner.save_report(report)
    runner.save_logs(results)

    return report


if __name__ == "__main__":
    main()
