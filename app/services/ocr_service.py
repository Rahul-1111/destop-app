import cv2
import numpy as np
import easyocr
import warnings
import re
from typing import Optional, Tuple, Dict
from app.core.config import settings  # Make sure this path matches your project layout

warnings.filterwarnings("ignore")

class OCRService:
    """Service class for optical character recognition operations."""

    def __init__(self):
        self.easyocr_reader = None
        self.confidence_threshold = settings.OCR_CONFIDENCE_THRESHOLD
        self._initialize_ocr_engine()

    def _initialize_ocr_engine(self):
        """Initialize the OCR engine."""
        self.easyocr_reader = easyocr.Reader(['en'], gpu=False)

    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for better OCR accuracy."""
        if image is None or image.size == 0:
            return image
        try:
            # Grayscale
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()
            # CLAHE for contrast
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            # Median blur for noise
            gray = cv2.medianBlur(gray, 3)
            return gray
        except Exception:
            return image

    def extract_text_easyocr(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text using EasyOCR."""
        try:
            if self.easyocr_reader is None:
                return "", 0.0

            # Convert to RGB if needed
            if len(image.shape) == 3 and image.shape[2] == 3:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            else:
                image_rgb = image

            results = self.easyocr_reader.readtext(
                image_rgb,
                allowlist='0123456789.-',
                paragraph=False,
                width_ths=0.7,
                height_ths=0.7
            )

            if results:
                best_result = max(results, key=lambda x: x[2])
                text, confidence = best_result[1], best_result[2]
                cleaned_text = self._clean_numeric_text(text)
                return cleaned_text, confidence
            else:
                return "", 0.0

        except Exception:
            return "", 0.0

    def _clean_numeric_text(self, text: str) -> str:
        """Clean extracted text to retain only numeric values."""
        if not text:
            return ""
        cleaned = re.sub(r'[^0-9.-]', '', text.strip())
        if cleaned.count('.') > 1:
            parts = cleaned.split('.')
            cleaned = parts[0] + '.' + ''.join(parts[1:])
        if '-' in cleaned:
            if cleaned.startswith('-'):
                cleaned = '-' + cleaned[1:].replace('-', '')
            else:
                cleaned = cleaned.replace('-', '')
        return cleaned

    def extract_numeric_value(self, image: np.ndarray) -> Tuple[Optional[float], float]:
        """Extract numeric value from image region."""
        if image is None or image.size == 0:
            return None, 0.0
        processed_image = self.preprocess_image(image)
        text, confidence = self.extract_text_easyocr(processed_image)
        try:
            if text and confidence >= self.confidence_threshold:
                numeric_value = float(text)
                return numeric_value, confidence
            else:
                return None, confidence
        except ValueError:
            return None, confidence

    def extract_balance_readings(self, frame: np.ndarray) -> Dict[str, Tuple[Optional[float], float]]:
        """Extract all balance readings from frame using predefined ROI coordinates."""
        readings = {}
        try:
            if frame is None:
                for reading_type in ['angle1', 'weight1', 'angle2', 'weight2']:
                    readings[reading_type] = (None, 0.0)
                return readings

            frame = cv2.resize(frame, (settings.CAMERA_WIDTH, settings.CAMERA_HEIGHT))
            roi_configs = {
                'angle1': (settings.ROI_ANGLE1_X, settings.ROI_ANGLE1_Y, settings.ROI_ANGLE1_W, settings.ROI_ANGLE1_H),
                'weight1': (settings.ROI_WEIGHT1_X, settings.ROI_WEIGHT1_Y, settings.ROI_WEIGHT1_W, settings.ROI_WEIGHT1_H),
                'angle2': (settings.ROI_ANGLE2_X, settings.ROI_ANGLE2_Y, settings.ROI_ANGLE2_W, settings.ROI_ANGLE2_H),
                'weight2': (settings.ROI_WEIGHT2_X, settings.ROI_WEIGHT2_Y, settings.ROI_WEIGHT2_W, settings.ROI_WEIGHT2_H)
            }

            for reading_type, (x, y, w, h) in roi_configs.items():
                pad = 8
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(frame.shape[1], x + w + pad)
                y2 = min(frame.shape[0], y + h + pad)
                roi = frame[y1:y2, x1:x2] if frame is not None else None
                if roi is not None and roi.size > 0:
                    value, confidence = self.extract_numeric_value(roi)
                    readings[reading_type] = (value, confidence)
                else:
                    readings[reading_type] = (None, 0.0)
        except Exception:
            for reading_type in ['angle1', 'weight1', 'angle2', 'weight2']:
                readings[reading_type] = (None, 0.0)
        return readings

# Global OCR service instance
ocr_service = OCRService()

# --- CLI usage example below ---

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python ocr_cli.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    image = cv2.imread(image_path)
    if image is None:
        print(f"Could not load image: {image_path}")
        sys.exit(1)

    readings = ocr_service.extract_balance_readings(image)
    print("Extracted readings from image:")
    for reading_type, (value, confidence) in readings.items():
        print(f"{reading_type:8}: {value} (confidence: {confidence:.2f})")
