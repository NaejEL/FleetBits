"""Shared pytest fixtures for FleetBits API security tests."""

import os

# app/config.py builds Settings() at import time and refuses to build without
# FLEET_JWT_SECRET, FLEET_DOMAIN and OPERATOR_PASSWORD (that refusal is itself
# under test — see tests/test_device_identity_contract.py). A fresh checkout has
# no .env, so `./.venv/bin/python -m pytest` could not even import the app.
#
# These are placeholders, not secrets: the suite runs entirely against in-memory
# SQLite and never reaches a real backing service. setdefault never overrides a
# value supplied by the environment, so CI and docker compose keep theirs.
os.environ.setdefault("FLEET_JWT_SECRET", "pytest-placeholder-not-a-secret-000000000000")
os.environ.setdefault("FLEET_DOMAIN", "fleet.test.invalid")
os.environ.setdefault("OPERATOR_PASSWORD", "pytest-placeholder")

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
async def unscoped_operator_user(test_db):
    """Create a non-admin user whose token carries no site scope.

    ``TokenPayload`` allows this shape, and it is the fail-closed case: there is
    no site to confine such a caller to, so it must be refused rather than
    served fleet-wide data.
    """
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="unscoped_test",
            email="unscoped@test.local",
            password_hash="dummy_hash",
            role="operator",
            site_scope=None,
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def ci_bot_user(test_db):
    """Create a ``ci_bot`` user in the shape `ApiKeyCreate` mints by default.

    ``app/schemas/user.py`` defaults ``ApiKeyCreate.role`` to ``"ci_bot"`` with
    ``site_scope=None``, and the UI submits that default, so this — not the
    scoped variant — is what a CI key actually looks like. The role is
    fleet-wide by nature: confining it would make the ring-0 rules of
    ``deployments.py`` unreachable.
    """
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="ci_bot_test",
            email="ci-bot@test.local",
            password_hash="dummy_hash",
            role="ci_bot",
            site_scope=None,
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def viewer_user(test_db):
    """Create a fleet-wide ``viewer``: a read-only role with no site scope."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="viewer_test",
            email="viewer@test.local",
            password_hash="dummy_hash",
            role="viewer",
            site_scope=None,
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def trailing_newline_scope_user(test_db):
    """Create a user whose ``site_scope`` ends in a newline.

    ``re.match(r"...$", "site-a\n")`` succeeds — ``$`` also matches just before
    a trailing newline — so this value used to pass label validation and be
    interpolated, newline included, into a server-built expression.
    """
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="trailing_newline_test",
            email="trailing-newline@test.local",
            password_hash="dummy_hash",
            role="operator",
            site_scope="site-a\n",
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def scoped_ci_bot_user(test_db):
    """Create a ``ci_bot`` that *does* carry a site scope.

    A fleet-wide role is not an exemption: a key issued with a scope stays
    confined to it. This guards the half of decision 2 that must not be undone
    while restoring the scope-less shape.
    """
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="ci_bot_scoped_test",
            email="ci-bot-scoped@test.local",
            password_hash="dummy_hash",
            role="ci_bot",
            site_scope="site-a",
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def scoped_viewer_user(test_db):
    """Create a ``viewer`` that carries a site scope — confined like any other role."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="viewer_scoped_test",
            email="viewer-scoped@test.local",
            password_hash="dummy_hash",
            role="viewer",
            site_scope="site-a",
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def unknown_role_user(test_db):
    """Create a user whose role is outside ``VALID_ROLES``.

    ``fleet_user.role`` is an unconstrained ``Text`` column and the JWT carries
    the role verbatim, so an unrecognised role is a shape the predicate has to
    answer for. The fleet-wide set is an allow-list, so the answer is a refusal.
    """
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="unknown_role_test",
            email="unknown-role@test.local",
            password_hash="dummy_hash",
            role="superuser",
            site_scope=None,
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def technician_user(test_db):
    """Create a ``technician`` with no site scope — a scopable role, so an anomaly."""
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="technician_test",
            email="technician@test.local",
            password_hash="dummy_hash",
            role="technician",
            site_scope=None,
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def scoped_admin_user(test_db):
    """Create an ``admin`` user that nevertheless carries a site scope.

    ``TokenPayload`` allows this shape and only an admin can assign it. It used
    to be the permissive half of the disagreement between the two scoping
    predicates: ``telemetry.py`` confined such a token, ``observability.py``
    served it the whole fleet. The shared predicate now confines it, and that
    behaviour change needs a regression test of its own (GUIDELINES §3).
    """
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="scoped_admin_test",
            email="scoped-admin@test.local",
            password_hash="dummy_hash",
            role="admin",
            site_scope="site-a",
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def injecting_scope_user(test_db):
    """Create a user whose ``site_scope`` is a PromQL/LogQL injection.

    ``users.site_scope`` is an unconstrained ``Text`` column, so nothing at the
    storage layer stops this value; the routers interpolate it into
    server-built expressions and must validate it like any label value.
    """
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        user = User(
            username="injecting_scope_test",
            email="injecting-scope@test.local",
            password_hash="dummy_hash",
            role="operator",
            site_scope='site-a",job=~".*',
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
async def unscoped_operator_token(unscoped_operator_user):
    """Generate a token for the non-admin, scope-less user."""
    return create_operator_token(
        sub=unscoped_operator_user.username,
        role=unscoped_operator_user.role,
        site_scope=unscoped_operator_user.site_scope,
    )


@pytest_asyncio.fixture
async def ci_bot_token(ci_bot_user):
    """Generate the default-shaped CI key token: role ``ci_bot``, no site scope."""
    return create_operator_token(
        sub=ci_bot_user.username,
        role=ci_bot_user.role,
        site_scope=ci_bot_user.site_scope,
    )


@pytest_asyncio.fixture
async def viewer_token(viewer_user):
    """Generate a fleet-wide ``viewer`` token."""
    return create_operator_token(
        sub=viewer_user.username,
        role=viewer_user.role,
        site_scope=viewer_user.site_scope,
    )


@pytest_asyncio.fixture
async def trailing_newline_scope_token(trailing_newline_scope_user):
    """Generate a token whose ``site_scope`` claim carries a trailing newline."""
    return create_operator_token(
        sub=trailing_newline_scope_user.username,
        role=trailing_newline_scope_user.role,
        site_scope=trailing_newline_scope_user.site_scope,
    )


@pytest_asyncio.fixture
async def scoped_ci_bot_token(scoped_ci_bot_user):
    """Generate a ``ci_bot`` token confined to site-a."""
    return create_operator_token(
        sub=scoped_ci_bot_user.username,
        role=scoped_ci_bot_user.role,
        site_scope=scoped_ci_bot_user.site_scope,
    )


@pytest_asyncio.fixture
async def scoped_viewer_token(scoped_viewer_user):
    """Generate a ``viewer`` token confined to site-a."""
    return create_operator_token(
        sub=scoped_viewer_user.username,
        role=scoped_viewer_user.role,
        site_scope=scoped_viewer_user.site_scope,
    )


@pytest_asyncio.fixture
async def unknown_role_token(unknown_role_user):
    """Generate a token carrying a role outside ``VALID_ROLES``."""
    return create_operator_token(
        sub=unknown_role_user.username,
        role=unknown_role_user.role,
        site_scope=unknown_role_user.site_scope,
    )


@pytest_asyncio.fixture
async def technician_token(technician_user):
    """Generate a scope-less ``technician`` token."""
    return create_operator_token(
        sub=technician_user.username,
        role=technician_user.role,
        site_scope=technician_user.site_scope,
    )


@pytest_asyncio.fixture
async def scoped_admin_token(scoped_admin_user):
    """Generate a token for the admin user that carries a site scope."""
    return create_operator_token(
        sub=scoped_admin_user.username,
        role=scoped_admin_user.role,
        site_scope=scoped_admin_user.site_scope,
    )


@pytest_asyncio.fixture
async def injecting_scope_token(injecting_scope_user):
    """Generate a token whose ``site_scope`` claim is an injection payload."""
    return create_operator_token(
        sub=injecting_scope_user.username,
        role=injecting_scope_user.role,
        site_scope=injecting_scope_user.site_scope,
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
        # Keep package-repo authorization tests compatible with the stricter
        # repo-token flow by provisioning the same fixture token as a repo token.
        device.repo_token_hash = hash_token(raw_token)
        await session.commit()
    return raw_token


def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "security: mark test as a security-specific regression test"
    )
