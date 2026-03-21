from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL — must use asyncpg driver scheme
    DATABASE_URL: str = "postgresql+asyncpg://fleet:devpassword@localhost:5432/fleet"

    # Semaphore REST API
    SEMAPHORE_URL: str = "http://localhost:3001"
    SEMAPHORE_API_KEY: str = "dev-semaphore-key"

    # JWT signing secret (operators + CI tokens)
    FLEET_JWT_SECRET: str = "dev-jwt-secret-change-in-production"
    FLEET_JWT_ALGORITHM: str = "HS256"
    FLEET_JWT_EXPIRE_MINUTES: int = 480  # 8 hours

    # Prometheus + Loki proxy
    PROMETHEUS_URL: str = "http://localhost:9090"
    LOKI_URL: str = "http://localhost:3100"
    ALERTMANAGER_URL: str = "http://localhost:9093"

    FLEET_ENV: str = "development"
    FLEET_API_URL: str = "http://localhost:8000"

    # Operator login credentials (single admin user for V1)
    OPERATOR_USERNAME: str = "admin"
    OPERATOR_PASSWORD: str = "change-me-immediately"

    # Semaphore template IDs — match these to your Semaphore project setup
    SEMAPHORE_PROJECT_ID: int = 1
    SEMAPHORE_DEPLOY_TEMPLATE_ID: int = 1
    SEMAPHORE_ROLLBACK_TEMPLATE_ID: int = 2
    SEMAPHORE_RESTART_TEMPLATE_ID: int = 3
    SEMAPHORE_DIAGNOSTICS_TEMPLATE_ID: int = 4
    SEMAPHORE_LOGS_TEMPLATE_ID: int = 5


settings = Settings()
