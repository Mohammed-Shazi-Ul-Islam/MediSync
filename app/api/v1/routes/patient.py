import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.patient import Patient
from app.models.user import User, UserRole
from app.schemas.patient import PatientCreate, PatientResponse, PatientUpdate
from app.utils.dependencies import get_current_user, require_role

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.post(
    "",
    response_model=PatientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a patient profile",
)
def create_patient_profile(
    data: PatientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a patient profile linked to the authenticated user account.
    Each user account can have only one patient profile.
    Must be completed before submitting symptom reports.
    """
    existing = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A patient profile already exists for this account",
        )

    patient = Patient(
        user_id=current_user.id,
        full_name=data.full_name,
        age=data.age,
        gender=data.gender,
        phone=data.phone,
        email=data.email,
        medical_history=data.medical_history,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get(
    "/me",
    response_model=PatientResponse,
    summary="Get my patient profile",
)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve the patient profile for the currently authenticated user."""
    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found. Please create one via POST /patients",
        )
    return patient


@router.patch(
    "/me",
    response_model=PatientResponse,
    summary="Update my patient profile",
)
def update_my_profile(
    data: PatientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update the patient profile for the authenticated user."""
    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(patient, field, value)

    db.commit()
    db.refresh(patient)
    return patient


@router.get(
    "/{patient_id}",
    response_model=PatientResponse,
    summary="Get patient by ID (doctors/admins only)",
)
def get_patient_by_id(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR, UserRole.ADMIN)),
):
    """
    Fetch any patient profile by UUID.
    Restricted to doctors and admins — patients cannot look up other patients.
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )
    return patient
