from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class DetectionResult:
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_id: int = 0

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return self.x1, self.y1, self.x2, self.y2

    def contains_point(self, px: float, py: float) -> bool:
        return self.x1 <= px <= self.x2 and self.y1 <= py <= self.y2


@dataclass
class QRResult:
    data: str
    polygon: list[tuple[int, int]] = field(default_factory=list)
    center_x: float = 0.0
    center_y: float = 0.0

    @property
    def center(self) -> tuple[float, float]:
        return self.center_x, self.center_y


@dataclass
class TrackedObject:
    track_id: int
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float = 0.0
    qr_data: Optional[str] = None
    counted: bool = False

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return self.x1, self.y1, self.x2, self.y2

    def contains_point(self, px: float, py: float) -> bool:
        return self.x1 <= px <= self.x2 and self.y1 <= py <= self.y2


@dataclass
class DetectionRecord:
    tracking_id: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    qr_data: Optional[str] = None
    counted_status: bool = False
    box_x: int = 0
    box_y: int = 0
    box_width: int = 0
    box_height: int = 0
