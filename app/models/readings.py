"""
SQLAlchemy database models for balance machine readings.
"""
from sqlalchemy import Column, Integer, Float, String, DateTime, Boolean
from sqlalchemy.sql import func
from datetime import datetime, timezone, timedelta

from app.core.database import Base

def ist_now():
    # IST is UTC+5:30
    IST = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(IST)


class BalanceReading(Base):
    """
    Database model for storing balance machine readings.
    Contains two angle values and two weight values from HMI screen.
    """
    __tablename__ = "balance_readings"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=ist_now)
    part_name = Column(String(128), nullable=True)
    # Measurements from your HMI screen
    angle1 = Column(Float, nullable=True, comment="Correction Plane 1 Angle")
    weight1 = Column(Float, nullable=True, comment="Correction Plane 1 Amount") 
    angle2 = Column(Float, nullable=True, comment="Correction Plane 2 Angle")
    weight2 = Column(Float, nullable=True, comment="Correction Plane 2 Amount")
    
    # Processing status
    is_valid = Column(Boolean, default=True)
    processing_error = Column(String(500), nullable=True)
    
    
    
    def __repr__(self):
        return f"<BalanceReading(id={self.id}, angle1={self.angle1}, weight1={self.weight1})>"
