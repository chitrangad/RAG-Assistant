"""Test fixtures and helpers."""

import pathlib

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.database import init_db, close_db

# Import app lazily to avoid triggering engine creation at import time


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    """Create an isolated test database engine/session-factory per test.

    Monkeypatches the global engine and session factory in src.database so that
    init_db(), close_db(), and get_db() all use the test database transparently.

    The try/except on close_db() handles the case where the FastAPI lifespan
    (triggered by ASGITransport in the client fixture) has already disposed
    the engine before this fixture's teardown runs.
    """
    # Ensure data directory exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    test_db_path = "./data/test_catalog.db"

    # Create a fresh, test-specific engine and session factory
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
    )
    test_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Patch the globals so all DB access uses the test engine
    monkeypatch.setattr("src.database.engine", test_engine)
    monkeypatch.setattr("src.database.async_session_factory", test_factory)
    # API modules bind the session factory at import time (module caching
    # means a stale binding would otherwise survive across tests), so repoint
    # admin's bound name at the per-test factory as well.
    monkeypatch.setattr("src.api.admin.async_session_factory", test_factory)

    await init_db()
    yield
    await close_db()

    # Clean up the test database file
    db_path = pathlib.Path(test_db_path)
    if db_path.exists():
        db_path.unlink()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing the FastAPI app."""
    from src.main import app  # Lazy import after engine patching

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
