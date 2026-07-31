import logging
from typing import Optional

LOGGER = logging.getLogger(__name__)


class LineCounter:
    """Tracks object crossings.

    Two modes:
    - Horizontal line (line_y): counts objects whose center moves from above
      to below the line (one-directional).
    - Segment line (p1, p2): counts objects whose center crosses a directed
      line segment in either direction (side-of-line sign change).
    """

    def __init__(
        self,
        line_y: int = 400,
        hysteresis: int = 5,
        p1: Optional[tuple] = None,
        p2: Optional[tuple] = None,
    ) -> None:
        self._line_y = line_y
        self._hysteresis = hysteresis
        self._p1 = tuple(p1) if p1 else None
        self._p2 = tuple(p2) if p2 else None
        self._prev_centers: dict[int, float] = {}
        self._crossed_ids: set[int] = set()
        self._total_count: int = 0
        self._prev_sides: dict[int, float] = {}
        self._segment_crossed_ids: set[int] = set()
        self._segment_count: int = 0

    @property
    def line_y(self) -> int:
        return self._line_y

    @line_y.setter
    def line_y(self, value: int) -> None:
        self._line_y = value

    @property
    def total_count(self) -> int:
        return self._total_count

    @total_count.setter
    def total_count(self, value: int) -> None:
        self._total_count = value

    @property
    def line_count(self) -> int:
        return self._segment_count

    @property
    def crossed_ids(self) -> set[int]:
        return self._crossed_ids.copy()

    def set_line(self, p1: tuple, p2: tuple) -> None:
        """Configure the segment crossing line (pixel coordinates)."""
        self._p1 = (float(p1[0]), float(p1[1]))
        self._p2 = (float(p2[0]), float(p2[1]))

    def reset(self) -> None:
        """Zero all counts and tracking state."""
        self._prev_centers.clear()
        self._crossed_ids.clear()
        self._total_count = 0
        self._prev_sides.clear()
        self._segment_crossed_ids.clear()
        self._segment_count = 0

    def update(self, tracked_objects: list[dict]) -> int:
        if self._p1 is not None and self._p2 is not None:
            return self._update_segment(tracked_objects)
        return self._update_horizontal(tracked_objects)

    def _update_horizontal(self, tracked_objects: list[dict]) -> int:
        newly_crossed = 0

        for obj in tracked_objects:
            tid = obj["track_id"]
            y1 = obj["bbox"][1]
            y2 = obj["bbox"][3]
            center_y = (y1 + y2) / 2.0

            if tid in self._crossed_ids:
                obj["counted"] = True
                continue

            prev_center = self._prev_centers.get(tid)

            if prev_center is None:
                self._prev_centers[tid] = center_y
                obj["counted"] = False
                continue

            prev_above = prev_center < self._line_y
            now_below = center_y >= self._line_y + self._hysteresis

            if prev_above and now_below:
                self._crossed_ids.add(tid)
                self._total_count += 1
                obj["counted"] = True
                newly_crossed += 1
                LOGGER.debug("Counted track_id=%s (center %.1f -> %.1f, line=%d)",
                             tid, prev_center, center_y, self._line_y)
            else:
                obj["counted"] = False

            self._prev_centers[tid] = center_y

        return newly_crossed

    def _update_segment(self, tracked_objects: list[dict]) -> int:
        newly_crossed = 0

        for obj in tracked_objects:
            tid = obj["track_id"]
            bbox = obj["bbox"]
            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0

            if tid in self._segment_crossed_ids:
                obj["counted"] = True
                continue

            side = self._side((cx, cy))
            prev_side = self._prev_sides.get(tid)

            if prev_side is None:
                self._prev_sides[tid] = side
                obj["counted"] = False
                continue

            # Sign change across the line, with hysteresis clear of the line
            if prev_side * side < 0 and abs(side) >= self._hysteresis:
                self._segment_crossed_ids.add(tid)
                self._segment_count += 1
                obj["counted"] = True
                newly_crossed += 1
                LOGGER.debug("Line-crossed track_id=%s (side %.1f -> %.1f)",
                             tid, prev_side, side)
            else:
                obj["counted"] = False

            self._prev_sides[tid] = side

        return newly_crossed

    def _side(self, point: tuple) -> float:
        """Signed distance side of a point relative to the directed segment."""
        px, py = point
        x1, y1 = self._p1
        x2, y2 = self._p2
        return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
