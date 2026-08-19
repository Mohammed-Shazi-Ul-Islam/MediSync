from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.
    Using pydantic-settings ensures type safety and automatic validation.
    @lru_cache ensures this is only instantiated once (singleton pattern).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Allow extra vars from docker-compose .env (e.g. POSTGRES_USER)
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_name: str = "MediSync"
    app_version: str = "0.1.0"
    debug: bool = False

    # ── Security ──────────────────────────────────────────────────────────────
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str

    # ── Redis + Celery ────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── Gemini AI ─────────────────────────────────────────────────────────────
    gemini_api_key: str = ""

    # ── ChromaDB (Module 02 — RAG Vector Store) ───────────────────────────
    chroma_persist_dir: str = "./chroma_data"
    chroma_collection_name: str = "medical_kb"

    # ── Specialist Router (Module 03 — Rule + AI Hybrid) ─────────────────
    chroma_specialist_collection_name: str = "specialist_profiles"
    router_rule_confidence_threshold: float = 0.80   # Below this, semantic layer runs
    router_top_k_specialist_docs: int = 3             # ChromaDB neighbours to retrieve

    # ── Twilio SMS ────────────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # ── SMTP Email (Module 04) ────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@medisync.io"

    # ── Notification Escalation (Module 04) ──────────────────────────────────
    notification_escalation_minutes: int = 5   # Minutes before an unaccepted case escalates
    notification_max_escalations: int = 3       # Max times a case escalates before admin alert

    # ── Rate Limiting (Module 06) ─────────────────────────────────────────────
    rate_limit_enabled: bool = True
    # Requests per minute per IP (global catch-all)
    rate_limit_global_per_minute: int = 100
    # Auth endpoints (login, refresh) — tighter to prevent brute force
    rate_limit_auth_per_minute: int = 10
    # Intake submit — prevent symptom-report spam per authenticated user
    rate_limit_intake_per_minute: int = 5
    # Admin endpoints — generous but still rate-limited
    rate_limit_admin_per_minute: int = 60


@lru_cache()
def get_settings() -> Settings:
    """
    Cached settings instance — imported and used via Depends(get_settings)
    in FastAPI routes, or called directly in non-route code.
    """
    return Settings()
