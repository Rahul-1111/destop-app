from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List, Tuple
import warnings
import logging

logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

from app.models.readings import BalanceReading
from app.schemas.readings import BalanceReadingCreate
from app.core.database import Part

class DataService:
    """Service class for database operations on balance readings and parts."""

    # ==================== BALANCE READING METHODS ====================

    def create_reading(self, db: Session, reading_data: BalanceReadingCreate) -> BalanceReading:
        """Create a new balance reading record."""
        try:
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
        angle1_min=None,  # Ignored (for backward compatibility)
        angle1_max=None,  # Ignored
        angle2_min=None,  # Ignored
        angle2_max=None,  # Ignored
        weight1_min=None,
        weight1_max=None,
        weight2_min=None,
        weight2_max=None
    ):
        """Add new part - ANGLE THRESHOLDS IGNORED"""
        part = Part(
            part_code=part_code,
            part_name=part_name,
            # ❌ NO angle fields - removed from database
            weight1_min=weight1_min,
            weight1_max=weight1_max,
            weight2_min=weight2_min,
            weight2_max=weight2_max
        )
        db.add(part)
        db.commit()
        db.refresh(part)
        return part

    def get_all_parts(self, db: Session):
        """Get a list of all parts."""
        try:
            return db.query(Part).all()
        except Exception:
            return []

# Global data service instance
data_service = DataService()
