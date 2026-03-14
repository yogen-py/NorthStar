"""
Trust Database Connection — Phase 0
SQLAlchemy engine factory for SQLite (dev) / PostgreSQL (prod).
"""

import os
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, Text, Real, Integer, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

# ───────────────────────── Configuration ─────────────────────────
DB_URL = os.getenv("DB_URL", "sqlite:///./trust.db")

# ───────────────────────── Logging ───────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trust-db")

# ───────────────────────── SQLAlchemy Setup ──────────────────────
engine = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ClientTrust(Base):
    """ORM model for the client_trust table."""
    __tablename__ = "client_trust"

    client_id = Column(Text, primary_key=True)
    trust_score = Column(Real, default=0.8)
    anomaly_count = Column(Integer, default=0)
    rounds_participated = Column(Integer, default=0)
    last_update = Column(DateTime, nullable=True)


def init_db() -> None:
    """Create all tables in the database."""
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database initialized: {DB_URL}")


@contextmanager
def get_session():
    """Yield a SQLAlchemy session and handle cleanup."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ───────────────────────── Main ─────────────────────────────────

if __name__ == "__main__":
    init_db()
    logger.info("Trust DB schema created successfully.")
