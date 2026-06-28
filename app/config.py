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

    # ── Twilio SMS ────────────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""


@lru_cache()
def get_settings() -> Settings:
    """
    Cached settings instance — imported and used via Depends(get_settings)
    in FastAPI routes, or called directly in non-route code.
    """
    return Settings()
