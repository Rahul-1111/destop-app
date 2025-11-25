"""
Data service for database operations.
"""
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List, Tuple
import warnings
import logging

logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

from app.models.readings import BalanceReading
from app.schemas.readings import BalanceReadingCreate  # Use a dataclass, not pydantic, for desktop!
from app.core.database import Part

class DataService:
    """Service class for database operations on balance readings and parts."""

    # ==================== BALANCE READING METHODS ====================

    def create_reading(self, db: Session, reading_data: BalanceReadingCreate) -> BalanceReading:
        """Create a new balance reading record."""
        try:
            # Replace .dict() with vars() if using dataclass, or asdict() if imported from dataclasses
            db_reading = BalanceReading(**vars(reading_data))
            db.add(db_reading)
            db.commit()
            db.refresh(db_reading)
            return db_reading
        except Exception:
            db.rollback()
            raise

    def get_reading(self, db: Session, reading_id: int) -> Optional[BalanceReading]:
        """Get a balance reading by ID."""
        try:
            reading = db.query(BalanceReading).filter(BalanceReading.id == reading_id).first()
            return reading
        except Exception:
            return None

    def get_readings(self, db: Session, skip: int = 0, limit: int = 100) -> Tuple[List[BalanceReading], int]:
        """Get paginated list of balance readings."""
        try:
            query = db.query(BalanceReading)
            total = query.count()
            readings = query.order_by(desc(BalanceReading.created_at)).offset(skip).limit(limit).all()
            return readings, total
        except Exception:
            return [], 0

    # ==================== PARTS METHODS ====================

    def add_part(
        self,
        db: Session,
        part_code: str,
        part_name: str,
        angle1_min: float = None,
        angle1_max: float = None,
        angle2_min: float = None,
        angle2_max: float = None,
        weight1_min: float = None,
        weight1_max: float = None,
        weight2_min: float = None,
        weight2_max: float = None
    ):
        """Insert a new part into the parts table, with optional min/max values."""
        try:
            part = Part(
                part_code=part_code,
                part_name=part_name,
                angle1_min=angle1_min,
                angle1_max=angle1_max,
                angle2_min=angle2_min,
                angle2_max=angle2_max,
                weight1_min=weight1_min,
                weight1_max=weight1_max,
                weight2_min=weight2_min,
                weight2_max=weight2_max
            )
            db.add(part)
            db.commit()
            db.refresh(part)
            return part
        except Exception:
            db.rollback()
            raise

    def get_all_parts(self, db: Session):
        """Get a list of all parts."""
        try:
            return db.query(Part).all()
        except Exception:
            return []

# Global data service instance
data_service = DataService()
