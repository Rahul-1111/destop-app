"""
Database configuration and session management.
"""
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

# REMOVE LOGGING COMPLETELY
import logging
logging.disable(logging.CRITICAL)
import warnings
warnings.filterwarnings("ignore")
logging.getLogger("uvicorn").disabled = True
logging.getLogger("sqlalchemy").disabled = True

from .config import settings

# Create SQLAlchemy engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # For SQLite
)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for models
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)

class Part(Base):
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True, index=True)
    part_code = Column(String, unique=True, index=True)
    part_name = Column(String, index=True)

    # --- Angle Limits (Float) ---
    angle1_min = Column(Float, nullable=True)
    angle1_max = Column(Float, nullable=True)
    angle2_min = Column(Float, nullable=True)
    angle2_max = Column(Float, nullable=True)

    # --- Weight Limits (Float) ---
    weight1_min = Column(Float, nullable=True)
    weight1_max = Column(Float, nullable=True)
    weight2_min = Column(Float, nullable=True)
    weight2_max = Column(Float, nullable=True)


