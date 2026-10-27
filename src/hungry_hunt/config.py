"""Runtime settings, read from the environment and an optional .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite:///hunt.db"
    user_id: str = "poojitha"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    assess_max_calls: int = 300
    assess_interval_s: float = 6.2
    smtp_user: str = ""
    smtp_password: str = ""
    digest_to: str = ""
    review_base_url: str = "http://localhost:5173"
    review_token: str = ""
    digest_max_jobs: int = 120
    fetch_concurrency: int = 24
    fetch_per_host: int = 16
    remote_ok: bool = True
    max_years_bar: int = 2
    max_posted_age_days: int = 14
    resume_tex: str = "./resume.tex"
    track_days: int = 14
    track_require_forwarded: bool = True
    log_level: str = "INFO"
    log_format: str = "plain"
