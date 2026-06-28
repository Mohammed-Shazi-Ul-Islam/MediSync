import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.models.patient import Gender


# ── Request Schemas ────────────────────────────────────────────────────────────

class PatientCreate(BaseModel):
    full_name: str
    age: int
    gender: Gender
    phone: str
    email: EmailStr | None = None
    medical_history: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """
        Accept international format: +919876543210 or 9876543210.
        Strips spaces, dashes, and parentheses before validating.
        """
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[1-9]\d{9,14}$", cleaned):
            raise ValueError(
                "Invalid phone number. Use format: +919876543210 or 9876543210"
            )
        return cleaned

    @field_validator("age")
    @classmethod
    def validate_age(cls, v: int) -> int:
        if not (0 < v <= 120):
            raise ValueError("Age must be between 1 and 120")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Full name must be at least 2 characters")
        return v


class PatientUpdate(BaseModel):
    """For partial updates — all fields optional."""
    full_name: str | None = None
    age: int | None = None
    phone: str | None = None
    email: EmailStr | None = None
    medical_history: str | None = None


# ── Response Schemas ───────────────────────────────────────────────────────────

class PatientResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    age: int
    gender: Gender
    phone: str
    email: str | None
    medical_history: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
