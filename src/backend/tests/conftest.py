"""Shared pytest fixtures for backend tests.

Strategy
--------
We point ``settings.database_url`` at an ephemeral in-memory aiosqlite URL
**before** importing anything that touches ``src.db.client``. Each test then
runs against its own freshly-created engine/schema so tests are fully
isolated.

We also force ``DEMO_MODE=true`` so that workers never try to call Claude or
BrowserUse during integration tests.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure project root is on sys.path so that ``import src.backend...`` works
# regardless of where pytest is invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Put a fresh per-session SQLite file somewhere writable. Using a real file
# (instead of :memory:) means each session opened by the code-under-test sees
# the same data, even across worker tasks. The schema is dropped + recreated
# per test to isolate state.
_TMP_DB = Path(tempfile.gettempdir()) / "storefront_reviewer_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()

# Force demo mode + test DB BEFORE importing db/client or backend modules.
os.environ["DEMO_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def db():
    """Build a fresh schema in the in-memory DB for each test.

    Yields the ``src.db.client`` module for convenience. The schema is dropped
    + recreated each test so state does not leak between tests.
    """
    # Import lazily so env vars above take effect.
    from src.db import client as db_client
    from src.db.schema import Base

    async with db_client.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield db_client

    async with db_client.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def app(db):
    """Build the FastAPI app after the DB schema is ready."""
    from src.backend.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP client backed by httpx + ASGI transport."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
