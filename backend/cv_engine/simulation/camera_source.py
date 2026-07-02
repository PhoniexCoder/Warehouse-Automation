import logging
import random
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
import qrcode

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
    qr_image: Optional[np.ndarray] = None


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

            if box.has_qr and box.qr_image is not None:
                self._overlay_qr(frame, box, x1, y1, x2, y2)

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

        if self.scene == "conveyor":
            for x in range(0, self.width, 80):
                cv2.circle(frame, (x, self.height // 2), 18, (40, 45, 50), -1)
                cv2.circle(frame, (x, self.height // 2), 14, (50, 55, 60), -1)

        elif self.scene == "storage":
            cv2.rectangle(frame, (0, 160), (self.width, 180), (55, 50, 45), -1)
            cv2.rectangle(frame, (0, 420), (self.width, 440), (55, 50, 45), -1)

        elif self.scene == "exit":
            door_w = 350
            dx = (self.width - door_w) // 2
            cv2.rectangle(frame, (dx, 0), (dx + door_w, 50), (60, 65, 55), -1)
            cv2.line(frame, (dx, 50), (dx, self.height), (50, 55, 45), 2)
            cv2.line(frame, (dx + door_w, 50), (dx + door_w, self.height), (50, 55, 45), 2)

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

        qr_img: Optional[np.ndarray] = None
        if has_qr:
            qr_img = self._generate_qr_image(qr_data, max(33, min(w, h) - 12))

        self.boxes.append(SimulatedBox(
            qr_data=qr_data,
            has_qr=has_qr,
            x=x, y=y, w=w, h=h,
            vx=vx, vy=vy,
            color=color,
            qr_image=qr_img,
        ))

    def _generate_qr_image(self, data: str, size: int = 50) -> Optional[np.ndarray]:
        try:
            qr = qrcode.QRCode(box_size=2, border=1)
            qr.add_data(data)
            qr.make(fit=True)
            pil_img = qr.make_image(fill_color="black", back_color="white")
            np_img = np.array(pil_img.convert("RGB"))
            return cv2.resize(np_img, (size, size), interpolation=cv2.INTER_NEAREST)
        except Exception as exc:
            LOGGER.warning("QR generation failed for %s: %s", data, exc)
            return None

    def _overlay_qr(self, frame: np.ndarray, box: SimulatedBox, x1: int, y1: int, x2: int, y2: int) -> None:
        if box.qr_image is None:
            return
        qr_h, qr_w = box.qr_image.shape[:2]
        margin = 6
        ox = min(x1 + margin, x2 - qr_w)
        oy = min(y1 + margin, y2 - qr_h)
        ox = max(ox, 0)
        oy = max(oy, 0)
        if ox + qr_w <= frame.shape[1] and oy + qr_h <= frame.shape[0]:
            frame[oy:oy + qr_h, ox:ox + qr_w] = box.qr_image

    @property
    def is_open(self) -> bool:
        return self._connected

    def release(self) -> None:
        self._connected = False
