"""SQLAlchemy declarative base and common column type factories."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.sqlite import CHAR as SQLiteUUID
from sqlalchemy.orm import DeclarativeBase, mapped_column


def gen_uuid() -> str:
    """Generate a UUID string for primary keys."""
    return str(uuid.uuid4())


def now_utc() -> datetime:
    """Return current UTC datetime (naive, for SQLite compatibility)."""
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# --- Column factory functions (each call creates a NEW mapped_column) ---

def pk_column():
    """Primary key UUID column."""
    return mapped_column(
        SQLiteUUID(36), primary_key=True, default=gen_uuid, nullable=False
    )


def created_at_column():
    """Timestamp column set on creation."""
    return mapped_column(DateTime, default=now_utc, nullable=False)


def updated_at_column():
    """Timestamp column updated on every change."""
    return mapped_column(
        DateTime, default=now_utc, onupdate=now_utc, nullable=False
    )


def required_string_column(**kwargs):
    """Non-nullable string column."""
    return mapped_column(String, nullable=False, **kwargs)


def optional_string_column(**kwargs):
    """Nullable string column."""
    return mapped_column(String, nullable=True, **kwargs)
