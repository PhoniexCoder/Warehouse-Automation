import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import argparse
import logging
import sys

import cv2
import numpy as np

from cv_engine.database import (
    create_tables,
    save_detection,
    save_duplicate_event,
    save_invalid_qr,
)
from cv_engine.services.box_processor import BoxProcessor
from cv_engine.services.duplicate_guard import DuplicateGuard
from cv_engine.services.inference_engine import InferenceEngine
from cv_engine.services.tracker import ObjectTracker
from cv_engine.services.line_counter import LineCounter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
LOGGER = logging.getLogger("main")

LINE_COLOR = (0, 255, 0)
LINE_THICKNESS = 2
COUNTED_BBOX_COLOR = (0, 255, 255)
UNCOUNTED_BBOX_COLOR = (0, 200, 255)
TEXT_COLOR = (255, 255, 255)
TEXT_BG = (0, 0, 0)
LABEL_SCALE = 0.55
LABEL_THICKNESS = 1
COUNTER_FONT_SCALE = 0.9
COUNTER_FONT_THICKNESS = 2
FPS_SCALE = 0.55
FPS_THICKNESS = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warehouse AI — CV Pipeline")
    parser.add_argument("--source", type=str, default="0",
                        help="Video source: 0 (webcam), path/to/file.mp4, rtsp://...")
    parser.add_argument("--model", type=str, default="models/box_model.pt",
                        help="Path to trained YOLO model weights")
    parser.add_argument("--conf", type=float, default=0.5,
                        help="YOLO confidence threshold")
    parser.add_argument("--line-y", type=int, default=400,
                        help="Y position of the counting line")
    parser.add_argument("--display-width", type=int, default=1280,
                        help="Display resize width")
    parser.add_argument("--display-height", type=int, default=720,
                        help="Display resize height")
    parser.add_argument("--skip", type=int, default=2,
                        help="Process every Nth frame (1 = every frame)")
    parser.add_argument("--input-size", type=int, default=640,
                        help="Inference input size (pixels, longest side)")
    parser.add_argument("--tracker", type=str, default="bytetrack",
                        choices=["bytetrack", "deepsort"],
                        help="Tracking backend")
    parser.add_argument("--device", type=str, default="cpu",
                        help="YOLO device: cpu, cuda:0, mps, etc.")
    parser.add_argument("--no-display", action="store_true",
                        help="Run headless (no OpenCV window)")
    return parser.parse_args()


class Pipeline:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

        LOGGER.info("Loading inference engine (model=%s conf=%.2f)",
                     args.model, args.conf)
        self.engine = InferenceEngine(
            source=args.source,
            model_path=args.model,
            conf_threshold=args.conf,
            device=args.device,
            input_size=args.input_size,
            frame_skip=args.skip,
        )

        self.box_processor = BoxProcessor()
        self.tracker = ObjectTracker(method=args.tracker)
        self.line_counter = LineCounter(line_y=args.line_y)
        self.duplicate_guard = DuplicateGuard()

        create_tables()

    def process_frame(self, frame: np.ndarray) -> np.ndarray | None:
        display = cv2.resize(frame, (self.args.display_width, self.args.display_height))
        dh, dw = display.shape[:2]
        oh, ow = frame.shape[:2]
        sx = dw / ow
        sy = dh / oh

        detections, _ = self.engine.infer(frame)
        if detections is None:
            display = self._draw_fps(display)
            return display

        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            det["bbox"] = [int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy)]

        detections = self.box_processor.process_detections(display, detections)

        tracked_objects = self.tracker.update(detections, display)

        self.line_counter.update(tracked_objects)

        for obj in tracked_objects:
            tid = obj.get("track_id")
            if not (obj.get("counted") and tid is not None):
                continue

            x1, y1, x2, y2 = obj["bbox"]
            qr_data = obj.get("qr_data")

            if not self.duplicate_guard.is_new(tid, qr_data):
                save_duplicate_event(
                    tracking_id=tid,
                    qr_data=qr_data,
                    camera_id=self.args.source,
                    box_x=x1,
                    box_y=y1,
                    box_width=x2 - x1,
                    box_height=y2 - y1,
                )
                LOGGER.debug("Duplicate count event for track_id=%s", tid)
                continue

            self.duplicate_guard.mark_counted(tid, qr_data)

            if qr_data:
                save_detection(
                    tracking_id=tid,
                    qr_data=qr_data,
                    camera_id=self.args.source,
                    counted_status=True,
                    box_x=x1,
                    box_y=y1,
                    box_width=x2 - x1,
                    box_height=y2 - y1,
                )
                LOGGER.debug("Detection saved: track_id=%s qr=%s", tid, qr_data)
            else:
                save_invalid_qr(
                    tracking_id=tid,
                    camera_id=self.args.source,
                    box_x=x1,
                    box_y=y1,
                    box_width=x2 - x1,
                    box_height=y2 - y1,
                )
                LOGGER.debug("Invalid QR logged for track_id=%s", tid)

        display = self._draw_overlay(display, tracked_objects)
        display = self._draw_counting_line(display)
        display = self._draw_total_count(display)
        display = self._draw_fps(display)
        return display

    def _draw_overlay(self, frame: np.ndarray, objects: list[dict]) -> np.ndarray:
        for obj in objects:
            x1, y1, x2, y2 = obj["bbox"]
            track_id = obj["track_id"]
            counted = obj.get("counted", False)
            qr_data = obj.get("qr_data")

            color = COUNTED_BBOX_COLOR if counted else UNCOUNTED_BBOX_COLOR
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            label = f"ID: {track_id}"
            if qr_data:
                label += f" QR: {qr_data}"

            (text_w, text_h), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, LABEL_SCALE, LABEL_THICKNESS
            )
            text_x = x1
            text_y = y1 - 6 if y1 - 6 > text_h + 4 else y2 + text_h + 6

            cv2.rectangle(
                frame,
                (text_x, text_y - text_h - baseline - 2),
                (text_x + text_w + 4, text_y + baseline + 2),
                TEXT_BG,
                -1,
            )
            cv2.putText(
                frame,
                label,
                (text_x + 2, text_y - 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                LABEL_SCALE,
                TEXT_COLOR,
                LABEL_THICKNESS,
                cv2.LINE_AA,
            )
        return frame

    def _draw_counting_line(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        y = self.line_counter.line_y
        cv2.line(frame, (0, y), (w, y), LINE_COLOR, LINE_THICKNESS)
        cv2.putText(frame, "COUNT LINE", (w - 140, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, LINE_COLOR, 1, cv2.LINE_AA)
        return frame

    def _draw_total_count(self, frame: np.ndarray) -> np.ndarray:
        count = self.line_counter.total_count
        text = f"TOTAL COUNT: {count}"

        (text_w, text_h), baseline = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, COUNTER_FONT_SCALE, COUNTER_FONT_THICKNESS
        )
        pad = 10
        x, y = pad, pad + text_h + baseline + pad

        cv2.rectangle(frame, (x - 4, y - text_h - baseline - 4),
                      (x + text_w + 4, y + baseline + 4), (0, 0, 0), -1)
        cv2.putText(frame, text, (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, COUNTER_FONT_SCALE,
                    (0, 255, 255), COUNTER_FONT_THICKNESS, cv2.LINE_AA)
        return frame

    def _draw_fps(self, frame: np.ndarray) -> np.ndarray:
        fps = self.engine.optimizer.fps
        inf_ms = self.engine.optimizer.last_inference_time_ms
        stats = f"FPS: {fps:.1f}  Inf: {inf_ms:.0f}ms"
        cv2.putText(frame, stats, (frame.shape[1] - 200, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, FPS_SCALE, (200, 200, 200), FPS_THICKNESS, cv2.LINE_AA)
        return frame


def run_pipeline(args: argparse.Namespace) -> None:
    engine = InferenceEngine(
        source=args.source,
        model_path=args.model,
        conf_threshold=args.conf,
        device=args.device,
        input_size=args.input_size,
        frame_skip=1,
    )
    engine.open()
    if not engine.is_open:
        LOGGER.error("Failed to open video source: %s", args.source)
        sys.exit(1)

    src_info = args.source
    LOGGER.info("Opened video source: %s", src_info)
    LOGGER.info("Pipeline config: conf=%.2f, line_y=%d, skip=%d, tracker=%s, input_size=%d, display=%s",
                args.conf, args.line_y, args.skip, args.tracker, args.input_size, not args.no_display)

    pipeline = Pipeline(args)

    try:
        while True:
            frame = engine.read_frame()
            if frame is None:
                LOGGER.info("End of video stream")
                break

            display = pipeline.process_frame(frame)
            if display is None:
                continue

            if not args.no_display:
                cv2.imshow("Warehouse AI — Box Counter", display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    LOGGER.info("User requested stop (key pressed)")
                    break

    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
    finally:
        engine.release()
        cv2.destroyAllWindows()
        LOGGER.info("Pipeline stopped. Total boxes counted: %d", pipeline.line_counter.total_count)
        LOGGER.info("Performance stats: %s", pipeline.engine.optimizer.stats())


def main() -> None:
    args = parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
