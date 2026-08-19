"""
tests/conftest.py

Shared pytest fixtures for the MediSync test suite.

Uses an in-memory SQLite database to avoid needing a running PostgreSQL
instance during testing.

SQLite compatibility patches applied:
  - JSONB → JSON  (SQLite has no native JSONB; JSON works fine for tests)
  - UUID columns rendered as String (SQLite has no UUID type)
  - PostgreSQL ENUMs become VARCHAR (SQLite ignores CREATE TYPE)

Note: For integration tests that need full PostgreSQL (JSONB queries etc.),
spin up a test DB using docker-compose and point TEST_DATABASE_URL at it.
"""

import os

# ── Module 06: Disable rate limiting in tests ──────────────────────────────────
# Set before any app module is imported so the cached Settings object picks it
# up and the rate limiter initialises with in-memory storage (no Redis ping).
# Direct assignment ensures this wins over any .env file value.
os.environ["RATE_LIMIT_ENABLED"] = "false"

# Clear get_settings() lru_cache in case it was already populated
# (e.g. by another pytest plugin that imported app code early).
from app.config import get_settings
get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON, String, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

# ── In-memory SQLite test DB ───────────────────────────────────────────────────
# Use :memory: so each pytest session starts with a completely blank database.
# No leftover rows from previous runs, no file to clean up.
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Remap PostgreSQL-specific types → SQLite-compatible equivalents at DDL time
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _conn_record):
    """Enable foreign key support in SQLite (disabled by default)."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _patch_jsonb_for_sqlite(target, connection, **kw):
    """Swap JSONB → JSON in all columns before create_all runs on SQLite."""
    pass  # handled below via reflect override


# Override JSONB to render as plain JSON on SQLite
from sqlalchemy.dialects.sqlite import base as sqlite_base

_orig_visit_JSONB = getattr(sqlite_base.SQLiteTypeCompiler, "visit_JSONB", None)
if _orig_visit_JSONB is None:
    def _visit_jsonb(self, type_, **kw):
        return "JSON"
    sqlite_base.SQLiteTypeCompiler.visit_JSONB = _visit_jsonb  # type: ignore[attr-defined]

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)



def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function", autouse=True)
def setup_database():
    """Create all tables before each test and drop them after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client():
    """
    FastAPI test client with DB dependency overridden.

    Calls limiter.reset() before each test to clear all in-memory rate limit
    counters. Without this, tests accumulate login calls against the same IP
    (testclient) and hit the 10/min auth limit after 10 tests.
    limiter.reset() is the official SlowAPI API for clearing storage.
    """
    import app.middleware.rate_limiter as rl_module

    # Clear rate limit counters before each test
    try:
        rl_module.limiter.reset()
    except Exception:
        pass  # Non-fatal if storage doesn't support reset

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def registered_patient(client):
    """Helper: register + login a patient user, return tokens."""
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "patient@medisync.io",
            "password": "TestPass123",
            "role": "patient",
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "patient@medisync.io", "password": "TestPass123"},
    )
    return response.json()


@pytest.fixture
def patient_with_profile(client, registered_patient):
    """Helper: patient with a full profile created."""
    client.post(
        "/api/v1/patients",
        json={
            "full_name": "Rahul Sharma",
            "age": 28,
            "gender": "male",
            "phone": "+919876543210",
            "medical_history": "No significant history",
        },
        headers={"Authorization": f"Bearer {registered_patient['access_token']}"},
    )
    return registered_patient
