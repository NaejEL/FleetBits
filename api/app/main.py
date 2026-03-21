from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.db import Base, engine
from app.services.token import TokenPayload, decode_token

# ──────────────────────────────────────────────────────────
# Lifespan: create tables on fresh dev start (Alembic handles prod)
# ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.FLEET_ENV == "development":
        async with engine.begin() as conn:
            import app.models  # noqa: F401 — populate Base.metadata
            await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


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
# Auth dependency (also exported from app.dependencies — kept here for import convenience)
# ──────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> TokenPayload:
    try:
        return decode_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ──────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────

@app.get("/healthz", tags=["meta"])
async def healthz():
    return {"status": "ok", "env": settings.FLEET_ENV}


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
