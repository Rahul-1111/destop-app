from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
import logging
logging.disable(logging.CRITICAL)
import warnings
warnings.filterwarnings("ignore")
logging.getLogger("uvicorn").disabled = True
logging.getLogger("sqlalchemy").disabled = True

from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # For SQLite
)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    """Part model - ANGLE THRESHOLDS REMOVED"""
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True, index=True)
    part_code = Column(String, unique=True, index=True)
    part_name = Column(String, index=True)
    
    # ✅ ONLY WEIGHT LIMITS
    weight1_min = Column(Float, nullable=True)
    weight1_max = Column(Float, nullable=True)
    weight2_min = Column(Float, nullable=True)
    weight2_max = Column(Float, nullable=True)