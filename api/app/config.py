from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL — must use asyncpg driver scheme
    DATABASE_URL: str = "postgresql+asyncpg://fleet:devpassword@localhost:5432/fleet"

    # Semaphore REST API
    SEMAPHORE_URL: str = "http://localhost:3001"
    SEMAPHORE_API_KEY: str = "dev-semaphore-key"

    # JWT signing secret (operators + CI tokens)
    FLEET_JWT_SECRET: str = Field(min_length=32)
    FLEET_JWT_ALGORITHM: str = "HS256"
    FLEET_JWT_EXPIRE_MINUTES: int = 480  # 8 hours

    # Prometheus + Loki proxy
    PROMETHEUS_URL: str = "http://localhost:9090"
    LOKI_URL: str = "http://localhost:3100"
    ALERTMANAGER_URL: str = "http://localhost:9093"

    # Secure telemetry ingestion (device -> fleet-api -> Prometheus/Loki)
    TELEMETRY_AUTH_REQUIRED: bool = True
    TELEMETRY_PROXY_TIMEOUT_SECONDS: float = 15.0

    FLEET_ENV: str = "development"
    FLEET_API_URL: str = "http://localhost:8000"
    ALLOW_ALL_ORIGINS: bool = False

    # Bootstrap admin credentials — used ONLY to seed the first admin user
    # when the fleet_user table is empty.  Change via the UI or API afterwards;
    # these env vars are ignored once any user exists in the database.
    OPERATOR_USERNAME: str = "admin"
    OPERATOR_PASSWORD: str = Field(min_length=12)

    # Login brute-force protection (API-side baseline)
    LOGIN_FAILURE_WINDOW_SECONDS: int = 900
    LOGIN_FAILURE_LOCK_THRESHOLD: int = 5
    LOGIN_FAILURE_LOCK_SECONDS: int = 900

    # Grafana admin credentials for user provisioning (server-side only)
    GRAFANA_INTERNAL_URL: str = "http://grafana:3000"
    GRAFANA_ADMIN_PASSWORD: str = ""
    # Auth proxy shared secret — Caddy injects this header to prevent forgery
    GRAFANA_PROXY_SECRET: str = ""

    # Semaphore template IDs — match these to your Semaphore project setup
    SEMAPHORE_PROJECT_ID: int = 1
    SEMAPHORE_DEPLOY_TEMPLATE_ID: int = 1
    SEMAPHORE_ROLLBACK_TEMPLATE_ID: int = 2
    SEMAPHORE_RESTART_TEMPLATE_ID: int = 3
    SEMAPHORE_DIAGNOSTICS_TEMPLATE_ID: int = 4
    SEMAPHORE_LOGS_TEMPLATE_ID: int = 5


settings = Settings()
