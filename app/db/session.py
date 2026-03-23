from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_bind(session: Session) -> Engine | Connection:
    bind = session.get_bind()
    if bind is None:
        raise RuntimeError("database bind is unavailable")
    return bind


def ping_database(session: Session) -> None:
    session.execute(select(1)).scalar_one()
