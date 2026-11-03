from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FaceGate"
    environment: str = "development"  # development | production | test
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

    database_url: str = "postgresql+asyncpg://facegate:facegate@localhost:5432/facegate"

    # Secrets — generate with: python -c "import secrets;print(secrets.token_urlsafe(48))"
    secret_key: str = "dev-only-change-me-dev-only-change-me-dev-only"
    template_key: str = "dev-only-template-key-CHANGE-ME"  # base64 urlsafe 32 bytes in production
    cookie_secure: bool = False  # True behind HTTPS (production)
    cookie_domain: str | None = None

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    verification_token_seconds: int = 90
    verify_session_ttl_seconds: int = 120
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # Vision
    models_dir: Path = BACKEND_DIR / "models"
    inference_workers: int = 4
    detector_score_threshold: float = 0.8
    match_accept_threshold: float = 0.40
    match_margin: float = 0.08
    duplicate_enrol_threshold: float = 0.55
    pad_live_threshold: float = 0.80
    pad_min_frames: int = 4
    embed_min_frames: int = 3
    min_face_size: int = 110
    max_stream_fps: float = 8.0
    keep_enrol_thumbnail: bool = True

    # Attendance defaults (overridable in app_settings table)
    org_timezone: str = "Europe/London"
    day_start: str = "04:00"
    work_start: str = "09:00"
    work_end: str = "17:30"
    late_grace_minutes: int = 10
    duplicate_scan_seconds: int = 120
    auto_close_after_hours: int = 16

    @property
    def is_prod(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
