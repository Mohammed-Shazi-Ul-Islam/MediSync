"""
tests/test_doctor_dashboard.py

Module 05 — Doctor Dashboard API: unit + integration tests.

Tests run in-process using FastAPI's TestClient with a SQLite in-memory DB.
No Docker, no Celery, no Twilio, no SMTP required.

Coverage:
  - Doctor profile creation, retrieval, update
  - Queue endpoint (empty + populated states)
  - Accept / Reject / Status update flows
  - Analytics aggregation
  - RBAC: patient cannot call doctor endpoints
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.user import User, UserRole
from app.models.patient import Patient, Gender
from app.models.doctor import Doctor
from app.models.intake import SymptomReport, SeverityHint, ReportStatus
from app.models.case_assignment import CaseAssignment, AssignmentStatus
from app.services.auth_service import create_access_token

# ── In-memory SQLite test DB ───────────────────────────────────────────────────
# StaticPool forces all connections to share the SAME in-memory database so
# tables created by setup_db are visible to the FastAPI TestClient sessions.
SQLALCHEMY_TEST_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Hardcoded bcrypt hash for "Test1234!" — avoids calling passlib/bcrypt at
# module-load time, which crashes on passlib 1.7.4 + bcrypt >=4.1 due to an
# internal 73-byte password test that the newer bcrypt library rejects.
# Generated with: passlib.context.CryptContext(schemes=["bcrypt"]).hash("Test1234!")
_HASHED_TEST_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


# ── Fixtures: users, doctor, patient, report ──────────────────────────────────

def _make_user(db, email: str, role: UserRole) -> User:
    user = User(
        email=email,
        hashed_password=_HASHED_TEST_PASSWORD,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_doctor(db, user: User, specialty: str = "cardiologist") -> Doctor:
    doc = Doctor(
        user_id=user.id,
        full_name="Dr. Test Doctor",
        specialty=specialty,
        phone=f"+9187654{uuid.uuid4().int % 10000:04d}",
        is_available=True,
        max_concurrent_cases=5,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _make_patient(db, user: User) -> Patient:
    p = Patient(
        user_id=user.id,
        full_name="Test Patient",
        age=30,
        gender=Gender.MALE,
        phone=f"+9199999{uuid.uuid4().int % 10000:04d}",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_report(db, patient: Patient) -> SymptomReport:
    r = SymptomReport(
        patient_id=patient.id,
        raw_text="I have severe chest pain and shortness of breath",
        severity_hint=SeverityHint.SEVERE,
        status=ReportStatus.TRIAGED,
        urgency_level="critical",
        specialist_recommendation="cardiologist",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _make_assignment(db, report: SymptomReport, doctor: Doctor) -> CaseAssignment:
    a = CaseAssignment(
        report_id=report.id,
        doctor_id=doctor.id,
        status=AssignmentStatus.OFFERED,
        escalation_count=0,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


# ── Tests: Profile ─────────────────────────────────────────────────────────────

def test_create_doctor_profile(client, db):
    user = _make_user(db, "doc@test.com", UserRole.DOCTOR)
    headers = _auth_header(user)

    response = client.post(
        "/api/v1/doctors",
        json={
            "full_name": "Dr. John Smith",
            "specialty": "cardiologist",
            "phone": "+919876500001",
        },
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["specialty"] == "cardiologist"
    assert data["full_name"] == "Dr. John Smith"


def test_create_doctor_duplicate_profile(client, db):
    user = _make_user(db, "doc2@test.com", UserRole.DOCTOR)
    _make_doctor(db, user)
    headers = _auth_header(user)

    response = client.post(
        "/api/v1/doctors",
        json={"full_name": "Dr. Another", "specialty": "neurologist", "phone": "+919876500002"},
        headers=headers,
    )
    assert response.status_code == 409


def test_get_my_profile(client, db):
    user = _make_user(db, "doc3@test.com", UserRole.DOCTOR)
    _make_doctor(db, user, specialty="neurologist")
    headers = _auth_header(user)

    response = client.get("/api/v1/doctors/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["specialty"] == "neurologist"


def test_update_my_profile(client, db):
    user = _make_user(db, "doc4@test.com", UserRole.DOCTOR)
    _make_doctor(db, user)
    headers = _auth_header(user)

    response = client.patch(
        "/api/v1/doctors/me",
        json={"is_available": False, "department": "ICU"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["is_available"] is False
    assert response.json()["department"] == "ICU"


def test_patient_cannot_access_doctor_endpoint(client, db):
    patient_user = _make_user(db, "patient@test.com", UserRole.PATIENT)
    headers = _auth_header(patient_user)

    response = client.get("/api/v1/doctors/me", headers=headers)
    assert response.status_code == 403


# ── Tests: Queue ───────────────────────────────────────────────────────────────

def test_get_empty_queue(client, db):
    user = _make_user(db, "doc5@test.com", UserRole.DOCTOR)
    _make_doctor(db, user)
    headers = _auth_header(user)

    response = client.get("/api/v1/doctors/me/queue", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["cases"] == []


def test_get_queue_with_offered_case(client, db):
    # Setup doctor + patient + report + assignment
    doc_user = _make_user(db, "doc6@test.com", UserRole.DOCTOR)
    doctor = _make_doctor(db, doc_user)

    pat_user = _make_user(db, "pat@test.com", UserRole.PATIENT)
    patient = _make_patient(db, pat_user)
    report = _make_report(db, patient)
    _make_assignment(db, report, doctor)

    headers = _auth_header(doc_user)
    response = client.get("/api/v1/doctors/me/queue", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["cases"][0]["urgency_level"] == "critical"
    assert data["cases"][0]["assignment_status"] == "offered"


# ── Tests: Accept / Reject ─────────────────────────────────────────────────────

def test_accept_case(client, db):
    doc_user = _make_user(db, "doc7@test.com", UserRole.DOCTOR)
    doctor = _make_doctor(db, doc_user)
    pat_user = _make_user(db, "pat2@test.com", UserRole.PATIENT)
    patient = _make_patient(db, pat_user)
    report = _make_report(db, patient)
    assignment = _make_assignment(db, report, doctor)
    # Store a fake Celery task ID so the revoke branch is exercised
    assignment.celery_escalation_task_id = str(uuid.uuid4())
    db.commit()

    headers = _auth_header(doc_user)

    # Patch _get_celery so no Redis connection is needed, and notification so no SMTP.
    # notification_service is lazily imported inside accept_case, so patch at its source.
    with patch("app.services.doctor_service._get_celery") as mock_get_celery, \
         patch("app.services.notification_service.notification_service") as mock_notify:
        mock_celery_app = MagicMock()
        mock_get_celery.return_value = mock_celery_app
        mock_notify.notify_patient_case_accepted = MagicMock()

        response = client.post(
            f"/api/v1/doctors/me/queue/{report.id}/accept",
            json={"notes": "I'll take this case"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_reject_case_triggers_escalation(client, db):
    doc_user = _make_user(db, "doc8@test.com", UserRole.DOCTOR)
    doctor = _make_doctor(db, doc_user)
    pat_user = _make_user(db, "pat3@test.com", UserRole.PATIENT)
    patient = _make_patient(db, pat_user)
    report = _make_report(db, patient)
    assignment = _make_assignment(db, report, doctor)
    assignment.celery_escalation_task_id = str(uuid.uuid4())
    db.commit()

    headers = _auth_header(doc_user)

    # Mock escalate task at the site where doctor_service imports it (local import)
    # and mock _get_celery for the revoke branch
    with patch("app.services.doctor_service._get_celery") as mock_get_celery, \
         patch("app.services.doctor_service.escalate_unaccepted_case", create=True) as mock_escalate:
        mock_get_celery.return_value = MagicMock()
        mock_escalate.apply_async = MagicMock()

        # Patch the local import inside reject_case as well
        with patch("app.workers.tasks.escalate_unaccepted_case") as mock_task:
            mock_task.apply_async = MagicMock()

            response = client.post(
                f"/api/v1/doctors/me/queue/{report.id}/reject",
                json={"reason": "Out of my specialty"},
                headers=headers,
            )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["escalation_triggered"] is True



# ── Tests: Status Update ───────────────────────────────────────────────────────

def test_update_report_status_to_closed(client, db):
    doc_user = _make_user(db, "doc9@test.com", UserRole.DOCTOR)
    doctor = _make_doctor(db, doc_user)
    pat_user = _make_user(db, "pat4@test.com", UserRole.PATIENT)
    patient = _make_patient(db, pat_user)
    report = _make_report(db, patient)

    # Pre-set to ACCEPTED
    assignment = CaseAssignment(
        report_id=report.id,
        doctor_id=doctor.id,
        status=AssignmentStatus.ACCEPTED,
    )
    db.add(assignment)
    db.commit()

    headers = _auth_header(doc_user)
    response = client.patch(
        f"/api/v1/doctors/me/queue/{report.id}/status",
        json={"new_status": "closed", "notes": "Patient treated"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["new_status"] == "closed"


# ── Tests: Analytics ───────────────────────────────────────────────────────────

def test_analytics_empty(client, db):
    user = _make_user(db, "doc10@test.com", UserRole.DOCTOR)
    _make_doctor(db, user)
    headers = _auth_header(user)

    response = client.get("/api/v1/doctors/me/analytics", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_cases_offered"] == 0
    assert data["accept_rate_pct"] == 0.0
