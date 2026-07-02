from typing import Optional


class AssociationEngine:
    def associate(
        self,
        qr_results: list[dict],
        detections: list[dict],
    ) -> list[dict]:
        if not qr_results or not detections:
            return detections

        matched_track_ids: set[int] = set()
        mutable = list(detections)

        for qr in qr_results:
            qr_cx = (qr["bbox"][0] + qr["bbox"][2]) / 2.0
            qr_cy = (qr["bbox"][1] + qr["bbox"][3]) / 2.0

            best_idx: Optional[int] = None
            best_dist: float = float("inf")

            for idx, det in enumerate(mutable):
                track_id = det.get("track_id")
                if track_id is not None and track_id in matched_track_ids:
                    continue
                if det.get("counted", False):
                    continue

                x1, y1, x2, y2 = det["bbox"]
                if not (x1 <= qr_cx <= x2 and y1 <= qr_cy <= y2):
                    continue

                det_cx = (x1 + x2) / 2.0
                det_cy = (y1 + y2) / 2.0
                dist = (qr_cx - det_cx) ** 2 + (qr_cy - det_cy) ** 2

                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx

            if best_idx is not None:
                mutable[best_idx]["qr_data"] = qr["data"]
                tid = mutable[best_idx].get("track_id")
                if tid is not None:
                    matched_track_ids.add(tid)

        return mutable

    def associate_detection(
        self,
        qr_results: list[dict],
        detections: list[dict],
    ) -> list[dict]:
        return self.associate(qr_results, detections)
