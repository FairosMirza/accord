from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration comes from environment variables prefixed ACCORD_."""

    model_config = SettingsConfigDict(env_prefix="ACCORD_", env_file=".env", extra="ignore")

    app_name: str = "Accord"
    environment: str = "development"  # development | test | demo | production
    base_url: str = "http://localhost:5173"

    database_url: str = "postgresql+psycopg://accord:accord@localhost:5433/accord"
    run_migrations_on_start: bool = True
    seed_demo_data: bool = False

    # Opaque session tokens are stored as HMAC hashes keyed with this secret.
    session_secret: str = Field(default="dev-only-change-me", min_length=16)
    session_ttl_hours: int = 12
    cookie_secure: bool = True
    cookie_name: str = "accord_session"

    # Demo mode adds one-click persona sign-in. Never enable in production.
    demo_mode: bool = False

    # Single sign-on (OpenID Connect). For Microsoft Entra ID the issuer is
    # https://login.microsoftonline.com/<tenant-id>/v2.0
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_scopes: str = "openid profile email"
    oidc_provider_name: str = "Microsoft"
    # Create an employee record on first sign-in for people not yet synced from the directory.
    oidc_jit_provisioning: bool = True
    allowed_email_domains: list[str] = []

    storage_backend: str = "local"  # local | gcs
    storage_local_path: str = "./var/uploads"
    gcs_bucket: str | None = None
    max_upload_mb: int = 15

    email_backend: str = "outbox"  # outbox (store only) | smtp
    email_from: str = "Accord <accord@orvane.example>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True

    # Shared secret for scheduler-triggered jobs (reminders).
    job_token: str | None = None

    base_currency: str = "USD"

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production and settings.demo_mode:
        raise RuntimeError("ACCORD_DEMO_MODE must not be enabled in production")
    if settings.is_production and settings.session_secret == "dev-only-change-me":
        raise RuntimeError("ACCORD_SESSION_SECRET must be set in production")
    return settings
