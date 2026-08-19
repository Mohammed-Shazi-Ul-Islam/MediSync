"""
tests/test_intake.py

Tests for Module 01 — Patient Intake API.
Covers: auth, patient profile CRUD, symptom report submission, polling.
"""

# ── Auth Tests ─────────────────────────────────────────────────────────────────

class TestAuth:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_register_patient(self, client):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "new@test.com", "password": "TestPass123", "role": "patient"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "new@test.com"
        assert data["role"] == "patient"
        assert "id" in data

    def test_register_duplicate_email(self, client):
        payload = {"email": "dup@test.com", "password": "TestPass123", "role": "patient"}
        client.post("/api/v1/auth/register", json=payload)
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 409

    def test_register_weak_password(self, client):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "weak@test.com", "password": "short", "role": "patient"},
        )
        assert response.status_code == 422

    def test_login_success(self, client, registered_patient):
        assert "access_token" in registered_patient
        assert "refresh_token" in registered_patient
        assert registered_patient["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        client.post(
            "/api/v1/auth/register",
            json={"email": "user@test.com", "password": "TestPass123"},
        )
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@test.com", "password": "WrongPass"},
        )
        assert response.status_code == 401

    def test_refresh_token(self, client, registered_patient):
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": registered_patient["refresh_token"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        # New refresh token should be different (rotation)
        assert data["refresh_token"] != registered_patient["refresh_token"]

    def test_get_me(self, client, registered_patient):
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {registered_patient['access_token']}"},
        )
        assert response.status_code == 200
        assert response.json()["email"] == "patient@medisync.io"

    def test_protected_route_without_token(self, client):
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401  # HTTPBearer returns 401 when Authorization header is missing


# ── Patient Profile Tests ──────────────────────────────────────────────────────

class TestPatientProfile:
    def test_create_profile(self, client, registered_patient):
        response = client.post(
            "/api/v1/patients",
            json={
                "full_name": "Priya Nair",
                "age": 32,
                "gender": "female",
                "phone": "+919876543211",
            },
            headers={"Authorization": f"Bearer {registered_patient['access_token']}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["full_name"] == "Priya Nair"
        assert data["age"] == 32

    def test_create_duplicate_profile(self, client, patient_with_profile):
        response = client.post(
            "/api/v1/patients",
            json={
                "full_name": "Duplicate",
                "age": 25,
                "gender": "male",
                "phone": "+919999999999",
            },
            headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
        )
        assert response.status_code == 409

    def test_get_my_profile(self, client, patient_with_profile):
        response = client.get(
            "/api/v1/patients/me",
            headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "Rahul Sharma"

    def test_update_profile(self, client, patient_with_profile):
        response = client.patch(
            "/api/v1/patients/me",
            json={"age": 29, "medical_history": "Hypertension"},
            headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["age"] == 29
        assert data["medical_history"] == "Hypertension"

    def test_invalid_phone_number(self, client, registered_patient):
        response = client.post(
            "/api/v1/patients",
            json={
                "full_name": "Test User",
                "age": 25,
                "gender": "male",
                "phone": "123",  # Too short
            },
            headers={"Authorization": f"Bearer {registered_patient['access_token']}"},
        )
        assert response.status_code == 422

    def test_invalid_age(self, client, registered_patient):
        response = client.post(
            "/api/v1/patients",
            json={
                "full_name": "Test User",
                "age": 200,  # Out of range
                "gender": "male",
                "phone": "+919876543210",
            },
            headers={"Authorization": f"Bearer {registered_patient['access_token']}"},
        )
        assert response.status_code == 422


# ── Intake / Symptom Report Tests ──────────────────────────────────────────────

from unittest.mock import patch, MagicMock

class TestSymptomIntake:
    def test_submit_report_free_text(self, client, patient_with_profile):
        with patch("app.workers.tasks.analyze_symptom_report.delay", return_value=MagicMock(id="fake-task-id")):
            response = client.post(
                "/api/v1/intake",
                json={
                    "raw_text": "I have severe chest pain and shortness of breath since 2 hours",
                    "severity_hint": "severe",
                    "duration": "2 hours",
                },
                headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
            )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] in ["pending", "processing"]
        assert data["raw_text"] == "I have severe chest pain and shortness of breath since 2 hours"
        assert data["severity_hint"] == "severe"
        assert "id" in data

    def test_submit_report_with_structured_symptoms(self, client, patient_with_profile):
        with patch("app.workers.tasks.analyze_symptom_report.delay", return_value=MagicMock(id="fake-task-id")):
            response = client.post(
                "/api/v1/intake",
                json={
                    "raw_text": "Headache and fever since yesterday",
                    "structured_symptoms": {
                        "symptoms": ["headache", "fever"],
                        "location": "head",
                        "temperature": "101F",
                    },
                    "severity_hint": "moderate",
                    "duration": "1 day",
                },
                headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
            )
        assert response.status_code == 202
        data = response.json()
        assert data["structured_symptoms"]["symptoms"] == ["headache", "fever"]

    def test_submit_report_too_short(self, client, patient_with_profile):
        response = client.post(
            "/api/v1/intake",
            json={"raw_text": "Pain"},  # Too short — fails Pydantic validation before hitting Celery
            headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
        )
        assert response.status_code == 422

    def test_get_report_status(self, client, patient_with_profile):
        # Submit a report (mock Celery dispatch)
        with patch("app.workers.tasks.analyze_symptom_report.delay", return_value=MagicMock(id="fake-task-id")):
            submit = client.post(
                "/api/v1/intake",
                json={"raw_text": "I have been experiencing dizziness and nausea all morning"},
                headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
            )
        report_id = submit.json()["id"]

        # Poll for status
        response = client.get(
            f"/api/v1/intake/{report_id}",
            headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
        )
        assert response.status_code == 200
        assert response.json()["id"] == report_id

    def test_list_my_reports(self, client, patient_with_profile):
        # Submit 2 reports (mock Celery dispatch)
        with patch("app.workers.tasks.analyze_symptom_report.delay", return_value=MagicMock(id="fake-task-id")):
            for text in [
                "I have a persistent cough and mild fever for 3 days",
                "My left knee has been hurting after running yesterday",
            ]:
                client.post(
                    "/api/v1/intake",
                    json={"raw_text": text},
                    headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
                )

        response = client.get(
            "/api/v1/intake/my-reports",
            headers={"Authorization": f"Bearer {patient_with_profile['access_token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["reports"]) == 2

    def test_submit_without_patient_profile(self, client, registered_patient):
        """Should return 404 if no patient profile exists yet."""
        with patch("app.workers.tasks.analyze_symptom_report.delay", return_value=MagicMock(id="fake-task-id")):
            response = client.post(
                "/api/v1/intake",
                json={"raw_text": "I have severe chest pain since this morning"},
                headers={"Authorization": f"Bearer {registered_patient['access_token']}"},
            )
        assert response.status_code == 404

