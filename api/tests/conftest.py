"""Shared pytest fixtures for FleetBits API security tests."""

import pytest
import pytest_asyncio
from sqlalchemy import ARRAY
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.user import User
from app.models.site import Site
from app.models.zone import Zone
from app.models.device import Device
from app.models.profile import Profile
from app.services.token import create_operator_token, hash_token


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(INET, "sqlite")
def _compile_inet_sqlite(_type, _compiler, **_kw):
    return "TEXT"


@pytest_asyncio.fixture
async def test_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    yield engine

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_user(test_db):
    """Create an admin user for testing."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="admin_test",
            email="admin@test.local",
            password_hash="dummy_hash",
            role="admin",
            site_scope=None,
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def site_scoped_user(test_db):
    """Create a site-scoped (non-admin) user for testing."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="scoped_test",
            email="scoped@test.local",
            password_hash="dummy_hash",
            role="operator",
            site_scope="site-a",
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def test_sites(test_db):
    """Create test sites."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        sites = [
            Site(site_id="site-a", name="Site A", timezone="UTC"),
            Site(site_id="site-b", name="Site B", timezone="UTC"),
        ]
        session.add_all(sites)
        await session.commit()
        return sites


@pytest_asyncio.fixture
async def test_zones(test_db, test_sites):
    """Create test zones in the sites."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        zones = [
            Zone(zone_id="zone-a1", site_id="site-a", name="Zone A-1", criticality="high"),
            Zone(zone_id="zone-a2", site_id="site-a", name="Zone A-2", criticality="standard"),
            Zone(zone_id="zone-b1", site_id="site-b", name="Zone B-1", criticality="high"),
        ]
        session.add_all(zones)
        await session.commit()
        return zones


@pytest_asyncio.fixture
async def test_profiles(test_db):
    """Create test profiles."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        profiles = [
            Profile(
                profile_id="profile-default",
                name="Default Profile",
                baseline_stack={},
            ),
            Profile(
                profile_id="profile-custom",
                name="Custom Profile",
                baseline_stack={"components": [{"name": "extra", "artifactType": "deb"}]},
            ),
        ]
        session.add_all(profiles)
        await session.commit()
        return profiles


@pytest_asyncio.fixture
async def test_devices(test_db, test_zones, test_profiles):
    """Create test devices in zones."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        devices = [
            Device(
                device_id="device-a1-1",
                zone_id="zone-a1",
                site_id="site-a",
                profile_id="profile-default",
                role="kiosk",
                hostname="device-a1-1",
                ring=0,
            ),
            Device(
                device_id="device-a2-1",
                zone_id="zone-a2",
                site_id="site-a",
                profile_id="profile-default",
                role="kiosk",
                hostname="device-a2-1",
                ring=0,
            ),
            Device(
                device_id="device-b1-1",
                zone_id="zone-b1",
                site_id="site-b",
                profile_id="profile-custom",
                role="videowall",
                hostname="device-b1-1",
                ring=1,
            ),
        ]
        session.add_all(devices)
        await session.commit()
        return devices


@pytest_asyncio.fixture
async def admin_token(admin_user):
    """Generate a token for the admin user."""
    return create_operator_token(
        sub=admin_user.username,
        role=admin_user.role,
        site_scope=admin_user.site_scope,
    )


@pytest_asyncio.fixture
async def scoped_token(site_scoped_user):
    """Generate a token for the site-scoped user."""
    return create_operator_token(
        sub=site_scoped_user.username,
        role=site_scoped_user.role,
        site_scope=site_scoped_user.site_scope,
    )


@pytest_asyncio.fixture
async def device_token(test_db, test_devices):
    """Create and persist a device bearer token for device-a1-1."""
    raw_token = "device-a1-token"
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        result = await session.execute(
            select(Device).where(Device.device_id == "device-a1-1")
        )
        device = result.scalar_one()
        device.device_token_hash = hash_token(raw_token)
        await session.commit()
    return raw_token


def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "security: mark test as a security-specific regression test"
    )
