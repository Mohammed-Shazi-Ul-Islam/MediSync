"""
tests/conftest.py

Shared pytest fixtures for the MediSync test suite.

Uses an in-memory SQLite database to avoid needing a running PostgreSQL
instance during testing. SQLite doesn't support JSONB or PostgreSQL-specific
enums, so we use String types for those in test mode.

Note: For integration tests that need full PostgreSQL (JSONB queries etc.),
spin up a test DB using docker-compose and point TEST_DATABASE_URL at it.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# ── Test Database ──────────────────────────────────────────────────────────────
TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
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
    """FastAPI test client with DB dependency overridden."""
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
            "email": "patient@medisync.test",
            "password": "TestPass123",
            "role": "patient",
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "patient@medisync.test", "password": "TestPass123"},
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
