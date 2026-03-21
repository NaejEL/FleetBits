from contextlib import asynccontextmanager
import logging
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.db import AsyncSessionLocal, Base, engine
from app.services.passwords import hash_password

_log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
# Lifespan: create tables on fresh dev start (Alembic handles prod)
# and seed first admin from env vars when users table is empty.
# ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.FLEET_ENV == "development":
        async with engine.begin() as conn:
            import app.models  # noqa: F401 — populate Base.metadata
            await conn.run_sync(Base.metadata.create_all)

    await _seed_admin()
    yield
    await engine.dispose()


async def _seed_admin() -> None:
    """Create the bootstrap admin account when the users table is empty.

    Reads OPERATOR_USERNAME + OPERATOR_PASSWORD from settings.
    Does nothing if any user already exists.
    """
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        try:
            count = await db.scalar(select(func.count()).select_from(User))
            if count and count > 0:
                return

            admin = User(
                user_id=str(uuid.uuid4()),
                username=settings.OPERATOR_USERNAME,
                password_hash=hash_password(settings.OPERATOR_PASSWORD),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            await db.commit()
            _log.info("Seeded bootstrap admin user: %s", settings.OPERATOR_USERNAME)
        except Exception:  # noqa: BLE001 — table may not exist on very first cold start
            await db.rollback()


# ──────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Fleet API",
    version="0.1.0",
    description="FleetBits fleet management API — inventory, deployments, hotfixes, audit.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.FLEET_ENV == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Expose /metrics for Prometheus scraping (no auth — internal network only)
Instrumentator().instrument(app).expose(app, include_in_schema=False)

# ──────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────

@app.get("/healthz", tags=["meta"])
async def healthz():
    return {"status": "ok", "env": settings.FLEET_ENV}


@app.get("/.well-known/openid-configuration", include_in_schema=False)
async def oidc_discovery():
    """Minimal OIDC discovery stub — enables tools like Vault and Dex to consume
    the Fleet API as a JWT issuer without a full OIDC provider."""
    base = settings.FLEET_API_URL.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/api/v1/auth/login",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "response_types_supported": ["token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": [settings.FLEET_JWT_ALGORITHM],
        "scopes_supported": ["openid"],
    }


# ──────────────────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────────────────

from app.routers import (  # noqa: E402
    audit,
    auth,
    deployments,
    devices,
    hotfixes,
    observability,
    operations,
    overrides,
    profiles,
    sites,
    zones,
)

_V1 = "/api/v1"

app.include_router(auth.router, prefix=_V1)
app.include_router(sites.router, prefix=_V1)
app.include_router(zones.router, prefix=_V1)
app.include_router(profiles.router, prefix=_V1)
app.include_router(devices.router, prefix=_V1)
app.include_router(devices.services_router, prefix=_V1)
app.include_router(deployments.router, prefix=_V1)
app.include_router(hotfixes.router, prefix=_V1)
app.include_router(overrides.router, prefix=_V1)
app.include_router(operations.router, prefix=_V1)
app.include_router(observability.router, prefix=_V1)
app.include_router(audit.router, prefix=_V1)
