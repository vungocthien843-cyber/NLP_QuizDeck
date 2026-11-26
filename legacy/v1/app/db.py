"""Kết nối PostgreSQL (SQLAlchemy 2.x + psycopg 3)."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """Dependency cho FastAPI: mỗi request một session."""
    with SessionLocal() as session:
        yield session
