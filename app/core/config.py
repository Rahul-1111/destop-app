"""
Core configuration settings for the HMI OCR application.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    # API Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "HMI Balance Machine OCR System"
    VERSION: str = "1.0.0"

    # Database
    DATABASE_URL: str = "sqlite:///./data/readings.db"

    # Camera
    CAMERA_INDEX: int = 0
    CAMERA_WIDTH: int = 640
    CAMERA_HEIGHT: int = 640
    CAMERA_FPS: int = 30

    # OCR
    OCR_ENGINE: str = "easyocr"
    OCR_CONFIDENCE_THRESHOLD: float = 0.5

    # ROI (Region of Interest) for FOUR readings
    ROI_ANGLE1_X: int = 101
    ROI_ANGLE1_Y: int = 434
    ROI_ANGLE1_W: int = 139
    ROI_ANGLE1_H: int = 81

    ROI_WEIGHT1_X: int = 56
    ROI_WEIGHT1_Y: int = 333
    ROI_WEIGHT1_W: int = 217
    ROI_WEIGHT1_H: int = 90

    ROI_ANGLE2_X: int = 445
    ROI_ANGLE2_Y: int = 417
    ROI_ANGLE2_W: int = 106
    ROI_ANGLE2_H: int = 57

    ROI_WEIGHT2_X: int = 420
    ROI_WEIGHT2_Y: int = 324
    ROI_WEIGHT2_W: int = 165
    ROI_WEIGHT2_H: int = 78

    # Directories
    DATA_DIR: str = "./data"
    STATIC_DIR: str = "./app/static"
    TEMPLATES_DIR: str = "./app/templates"

    # Pydantic v2 model config
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"                 # Prevents errors for unknown .env keys 
    )

settings = Settings()

# Ensure data dir exists
Path(settings.DATA_DIR).mkdir(exist_ok=True, parents=True)
