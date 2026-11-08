from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
    verify_session_ttl_seconds: int = 60  # fail fast with a clear reason instead of a long silent wait
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # Vision
    models_dir: Path = BACKEND_DIR / "models"
    # Parallel inference workers; 0 = one per physical core (logical CPUs / 2, at least 2).
    inference_workers: int = Field(0, validate_default=True)
    inference_device: str = "cpu"  # OpenVINO / ONNX Runtime / OpenCV on CPU only; no GPU is used or required
    face_model: str = "intel-fr-0095"  # intel-fr-0095 (default) | sface-2021dec — changing it requires re-enrolment
    detect_max_side: int = 320  # frames are downscaled to this for detection only; alignment uses full resolution
    embed_max_frames: int = 6  # a verification session stops embedding once it holds this many frontal embeddings
    detector_score_threshold: float = 0.8
    # Calibrated on LFW for intel-fr-0095: 0.45 ≈ FAR 5e-5 per comparison (SFace at its old 0.42 was ≈ 1e-4).
    match_accept_threshold: float = 0.45
    match_margin: float = 0.08
    duplicate_enrol_threshold: float = 0.55
    pad_live_threshold: float = 0.45  # median live-probability that passes on passive evidence alone
    pad_spoof_threshold: float = 0.20  # median below this (after pad_reject_min_frames) is a clear spoof; in between → step-up head-turn
    pad_reject_min_frames: int = 14  # frames of evidence required before a session is rejected as spoof
    pad_min_frames: int = 3
    embed_min_frames: int = 3
    motion_min_frames: int = 5  # frames of landmark history needed before the frozen-stream check can pass
    min_face_size: int = 80  # px in the streamed frame; ~1 m from a laptop webcam
    max_stream_fps: float = 15.0  # server cap sits above the 10 fps clients send
    verify_sessions_per_minute: int = 120  # per client IP; raise behind a shared office NAT
    keep_enrol_thumbnail: bool = True

    # Attendance defaults (overridable in app_settings table)
    org_timezone: str = "Europe/London"
    day_start: str = "04:00"
    work_start: str = "09:00"
    work_end: str = "17:30"
    late_grace_minutes: int = 10
    duplicate_scan_seconds: int = 120
    auto_close_after_hours: int = 16

    @field_validator("inference_workers")
    @classmethod
    def _auto_workers(cls, v: int) -> int:
        return v if v > 0 else max(2, (os.cpu_count() or 4) // 2)

    @property
    def is_prod(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
