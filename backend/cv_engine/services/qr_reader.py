import logging

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)

try:
    from pyzbar.pyzbar import decode as _pyzbar_decode
    _HAS_PYZBAR = True
except ImportError:
    _HAS_PYZBAR = False
    LOGGER.warning("pyzbar not installed — QR fallback disabled")


class QRReaderError(Exception):
    pass


class QRReader:
    def __init__(self) -> None:
        self._detector = cv2.QRCodeDetector()

    def detect_qr(self, cropped_box: np.ndarray) -> dict:
        if cropped_box is None or cropped_box.size == 0 or cropped_box.ndim < 2:
            return {"success": False, "qr_data": None}

        result = self._try_decode(cropped_box)

        if not result["success"]:
            preprocessed = self._preprocess_for_blurry(cropped_box)
            for pp in preprocessed:
                result = self._try_decode(pp)
                if result["success"]:
                    break

        if not result["success"]:
            rotated = self._rotate_image(cropped_box)
            for rot in rotated:
                result = self._try_decode(rot)
                if result["success"]:
                    break

        return result

    def _try_decode(self, image: np.ndarray) -> dict:
        if image.shape[0] < 10 or image.shape[1] < 10:
            return {"success": False, "qr_data": None}

        data = self._decode_opencv(image)
        if data:
            return {"success": True, "qr_data": data}

        if _HAS_PYZBAR:
            data = self._decode_pyzbar(image)
            if data:
                return {"success": True, "qr_data": data}

        return {"success": False, "qr_data": None}

    def _decode_opencv(self, image: np.ndarray) -> str | None:
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            decoded_text, points, _ = self._detector.detectAndDecode(gray)
            if decoded_text and points is not None and len(points) > 0:
                return decoded_text.strip()
        except cv2.error:
            pass
        return None

    def _decode_pyzbar(self, image: np.ndarray) -> str | None:
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            barcodes = _pyzbar_decode(gray)
            for barcode in barcodes:
                if barcode.type != "QRCODE":
                    continue
                data = barcode.data.decode("utf-8").strip()
                if data:
                    return data
        except Exception:
            pass
        return None

    @staticmethod
    def _preprocess_for_blurry(image: np.ndarray) -> list[np.ndarray]:
        variations: list[np.ndarray] = []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        variations.append(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR))

        _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)
        variations.append(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR))

        sharp = cv2.filter2D(gray, -1, np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]]))
        variations.append(cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR))

        return variations

    @staticmethod
    def _rotate_image(image: np.ndarray) -> list[np.ndarray]:
        rotations: list[np.ndarray] = []
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        for angle in (90, 180, 270):
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR)
            rotations.append(rotated)
        return rotations
