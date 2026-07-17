import logging

LOGGER = logging.getLogger(__name__)


class LineCounter:
    def __init__(self, line_y: int = 400, hysteresis: int = 5) -> None:
        self._line_y = line_y
        self._hysteresis = hysteresis
        self._prev_centers: dict[int, float] = {}
        self._crossed_ids: set[int] = set()
        self._total_count: int = 0

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
    def crossed_ids(self) -> set[int]:
        return self._crossed_ids.copy()

    def update(self, tracked_objects: list[dict]) -> int:
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
