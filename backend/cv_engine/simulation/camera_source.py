import logging
import random
from dataclasses import dataclass

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)

SCENE_CONFIGS = {
    "entry": {
        "bg_color": (100, 110, 120),
        "spawn_interval": 45,
        "box_speed_range": (0.8, 1.5),
        "box_size_range": (80, 140, 60, 100),
        "qr_valid_ratio": 1.0,
        "motion_blur": 0.0,
        "max_boxes": 4,
        "description": "Boxes enter from top, clear QR codes",
    },
    "conveyor": {
        "bg_color": (60, 65, 70),
        "spawn_interval": 35,
        "box_speed_range": (1.5, 3.0),
        "box_size_range": (100, 160, 70, 110),
        "qr_valid_ratio": 0.8,
        "motion_blur": 0.4,
        "max_boxes": 5,
        "description": "Boxes move left-to-right, motion blur, mixed QR",
    },
    "storage": {
        "bg_color": (80, 75, 70),
        "spawn_interval": 60,
        "box_speed_range": (0.3, 0.6),
        "box_size_range": (90, 130, 70, 100),
        "qr_valid_ratio": 0.7,
        "motion_blur": 0.0,
        "max_boxes": 8,
        "description": "Slow-moving boxes on shelves, partial QR",
    },
    "exit": {
        "bg_color": (110, 115, 105),
        "spawn_interval": 40,
        "box_speed_range": (1.0, 2.0),
        "box_size_range": (70, 130, 60, 100),
        "qr_valid_ratio": 0.5,
        "motion_blur": 0.2,
        "max_boxes": 6,
        "description": "Mixed valid/invalid QR, overlapping boxes",
    },
}


@dataclass
class SimulatedBox:
    qr_data: str
    has_qr: bool
    x: float
    y: float
    w: int
    h: int
    vx: float
    vy: float
    color: tuple


class SimulatedCameraSource:
    def __init__(
        self,
        camera_id: str,
        scene: str = "entry",
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
    ) -> None:
        if scene not in SCENE_CONFIGS:
            raise ValueError(f"Unknown scene: {scene}. Choose from {list(SCENE_CONFIGS)}")

        self.camera_id = camera_id
        self.scene = scene
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_num = 0
        self._connected = True

        self.cfg = SCENE_CONFIGS[scene]
        self.boxes: list[SimulatedBox] = []
        self._qr_counter = 0
        self._box_spawn_counter = random.randint(0, self.cfg["spawn_interval"])

        LOGGER.info(
            "SimulatedSource [%s] scene=%s %dx%d",
            camera_id, scene, width, height,
        )

    def read(self):
        if not self._connected:
            return False, None, None

        self.frame_num += 1
        self._box_spawn_counter += 1

        frame = self._draw_background()

        if (
            self._box_spawn_counter >= self.cfg["spawn_interval"]
            and len(self.boxes) < self.cfg["max_boxes"]
        ):
            self._box_spawn_counter = 0
            self._spawn_box()

        detections: list[dict] = []
        stale: list[SimulatedBox] = []

        for box in self.boxes:
            box.x += box.vx
            box.y += box.vy

            if (
                box.x + box.w < -80
                or box.x > self.width + 80
                or box.y + box.h < -80
                or box.y > self.height + 80
            ):
                stale.append(box)
                continue

            x1, y1, x2, y2 = int(box.x), int(box.y), int(box.x + box.w), int(box.y + box.h)

            cv2.rectangle(frame, (x1, y1), (x2, y2), box.color, -1)
            border = tuple(max(0, int(c * 0.6)) for c in box.color)
            cv2.rectangle(frame, (x1, y1), (x2, y2), border, 2)

            # QR codes and conveyor belt indicators removed for clean stream view
            detections.append({
                "bbox": [x1, y1, x2, y2],
                "confidence": round(random.uniform(0.85, 0.99), 4),
                "class": "Large_Box" if box.w >= 130 else "Regular_Box",
            })

        for box in stale:
            self.boxes.remove(box)

        if self.cfg["motion_blur"] > 0 and random.random() < self.cfg["motion_blur"]:
            ksize = random.choice([3, 5])
            kernel = np.zeros((ksize, ksize), dtype=np.float32)
            kernel[:, ksize // 2] = 1.0 / ksize
            frame = cv2.filter2D(frame, -1, kernel)

        return True, frame, detections

    def _draw_background(self):
        bg = self.cfg["bg_color"]
        frame = np.full((self.height, self.width, 3), bg, dtype=np.uint8)

        dim = tuple(max(0, int(c * 0.75)) for c in bg)
        for y in range(0, self.height, 60):
            cv2.line(frame, (0, y), (self.width, y), dim, 1)

        # Removed simulated conveyor wheels and storage lines for a clean scene background
        return frame

    def _spawn_box(self) -> None:
        self._qr_counter += 1
        qr_data = f"BOX-{1000 + self._qr_counter}"
        has_qr = random.random() < self.cfg["qr_valid_ratio"]

        w = random.randint(self.cfg["box_size_range"][0], self.cfg["box_size_range"][1])
        h = random.randint(self.cfg["box_size_range"][2], self.cfg["box_size_range"][3])
        speed = random.uniform(*self.cfg["box_speed_range"])

        if self.scene == "entry":
            x = random.uniform(100, self.width - w - 100)
            y = -h - 10
            vx = random.uniform(-0.3, 0.3)
            vy = speed

        elif self.scene == "conveyor":
            x = -w - 10
            y = random.uniform(self.height // 2 - 120, self.height // 2 + 30)
            vx = speed
            vy = random.uniform(-0.2, 0.2)

        elif self.scene == "storage":
            x = random.uniform(50, self.width - w - 50)
            y = random.choice([180 - h, 440 - h])
            vx = random.uniform(-0.15, 0.15)
            vy = random.uniform(-0.05, 0.25)

        else:
            x = random.uniform(self.width // 2 - 350, self.width // 2 + 50)
            y = -h - 10
            vx = random.uniform(-0.3, 0.3)
            vy = speed

        color = (
            random.randint(80, 200),
            random.randint(80, 200),
            random.randint(80, 200),
        )

        self.boxes.append(SimulatedBox(
            qr_data=qr_data,
            has_qr=has_qr,
            x=x, y=y, w=w, h=h,
            vx=vx, vy=vy,
            color=color,
        ))

    @property
    def is_open(self) -> bool:
        return self._connected

    def release(self) -> None:
        self._connected = False
