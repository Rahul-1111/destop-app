"""
Desktop main application for HMI Balance Machine OCR System.
(replaces FastAPI API server)
"""
import warnings
import os
import sys

# Remove logging and warnings
import logging
logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

from app.core.config import settings
from app.core.database import create_tables
from app.services.camera_service import camera_service

def main():
    """Main entry for desktop/CLI"""
    print(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}...")

    # Startup
    create_tables()
    try:
        camera_service.start_camera()
        print("Camera service started.")
    except Exception as e:
        print("Warning: Camera service failed to start", str(e))

    # Main loop (replace with actual GUI or CLI logic)
    print("Ready - run your CLI/desktop UI here.")
    print("Press Ctrl+C to exit.")

    try:
        while True:
            # Example: just keep running, or launch your GUI/QMainWindow here
            pass
    except KeyboardInterrupt:
        print("Shutting down...")

    # Shutdown
    try:
        camera_service.stop_camera()
        print("Camera service stopped.")
    except Exception:
        pass
    print("Goodbye.")

if __name__ == "__main__":
    main()
