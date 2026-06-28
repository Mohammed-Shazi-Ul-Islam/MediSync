"""
app/models/__init__.py

Imports all models here so that:
1. Alembic's env.py only needs to import this one module to register all
   models with Base.metadata for migration auto-generation.
2. SQLAlchemy relationship() string references ("Patient", "SymptomReport")
   resolve correctly because all models are loaded into the same metadata.
"""

from app.models.user import User, UserRole  # noqa: F401
from app.models.patient import Patient, Gender  # noqa: F401
from app.models.intake import SymptomReport, SeverityHint, ReportStatus  # noqa: F401

__all__ = [
    "User",
    "UserRole",
    "Patient",
    "Gender",
    "SymptomReport",
    "SeverityHint",
    "ReportStatus",
]
