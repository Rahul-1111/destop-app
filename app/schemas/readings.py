from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class BalanceReadingCreate:
    part_name: Optional[str] = None
    angle1: Optional[float] = None
    weight1: Optional[float] = None
    angle2: Optional[float] = None
    weight2: Optional[float] = None
    is_valid: bool = True
    processing_error: Optional[str] = None

@dataclass
class BalanceReadingResponse:
    id: int
    created_at: datetime
    angle1: Optional[float] = None
    weight1: Optional[float] = None
    angle2: Optional[float] = None
    weight2: Optional[float] = None
    is_valid: bool = True
    processing_error: Optional[str] = None
    part_name: Optional[str] = None

@dataclass
class CameraStatus:
    is_connected: bool
    camera_index: int
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
