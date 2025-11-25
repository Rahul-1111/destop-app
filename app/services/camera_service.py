"""
Camera service for capturing video frames from HMI screen.
"""

import cv2
import numpy as np
import threading
import warnings
from datetime import datetime
from typing import Optional
import time

import logging
logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

from app.core.config import settings  # Update import path as per your project

class CameraService:
    """Service class for handling camera operations."""

    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index or settings.CAMERA_INDEX
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_running = False
        self.current_frame: Optional[np.ndarray] = None
        self.frame_lock = threading.Lock()
        self._capture_thread: Optional[threading.Thread] = None

    def start_camera(self) -> bool:
        """Start the camera capture."""
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                return False

            # Set camera properties
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.CAMERA_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.CAMERA_HEIGHT)
            self.cap.set(cv2.CAP_PROP_FPS, settings.CAMERA_FPS)

            self.is_running = True
            self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            return True
        except Exception:
            return False

    def stop_camera(self):
        """Stop the camera capture."""
        self.is_running = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
            self.cap = None

    def _capture_loop(self):
        """Main camera capture loop."""
        while self.is_running and self.cap and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
                if ret:
                    frame = cv2.resize(frame, (settings.CAMERA_WIDTH, settings.CAMERA_HEIGHT))
                    frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    with self.frame_lock:
                        self.current_frame = frame_gray.copy()
                time.sleep(1.0 / settings.CAMERA_FPS)
            except Exception:
                break

    def get_current_frame(self) -> Optional[np.ndarray]:
        """Get the most recent camera frame."""
        with self.frame_lock:
            return self.current_frame.copy() if self.current_frame is not None else None

    def save_frame(self, frame: np.ndarray, filename: str) -> bool:
        """Save a frame to file."""
        try:
            success = cv2.imwrite(filename, frame)
            return True if success else False
        except Exception:
            return False

    def get_camera_info(self) -> dict:
        """Get camera information and status."""
        if not self.cap:
            return {
                "is_connected": False,
                "camera_index": self.camera_index,
                "width": None,
                "height": None,
                "fps": None
            }
        return {
            "is_connected": self.cap.isOpened() if self.cap else False,
            "camera_index": self.camera_index,
            "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self.cap else None,
            "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if self.cap else None,
            "fps": self.cap.get(cv2.CAP_PROP_FPS) if self.cap else None
        }

    def extract_roi(self, frame: np.ndarray, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
        """Extract region of interest from frame."""
        try:
            if frame is None:
                return None
            height, width = frame.shape[:2]
            x = max(0, min(x, width - 1))
            y = max(0, min(y, height - 1))
            w = min(w, width - x)
            h = min(h, height - y)
            roi = frame[y:y+h, x:x+w]
            return roi
        except Exception:
            return None

# Global camera service instance
camera_service = CameraService()
