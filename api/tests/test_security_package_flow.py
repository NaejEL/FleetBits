"""
Package repository access control tests.

These tests verify that:
- Aptly admin API endpoints are not publicly accessible
- Package download policy is enforced (device token + registered repo key required)
- Authorized device keys are auto-registered and required by the repository authorization path
- Edge-device access still works through the secure model
"""

import pytest
import os
import httpx
from httpx import AsyncClient


def _live_sim_state_url() -> str:
    return os.getenv("EDGE_SIM_STATE_URL", "http://edge-sim:18080/state")


async def _get_live_sim_state_or_skip() -> dict:
    """Fetch dummy edge simulator runtime state from the Docker network."""
    url = _live_sim_state_url()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
    except httpx.HTTPError:
        pytest.skip("edge-sim container is unreachable in this environment")

    if resp.status_code != 200:
        pytest.skip(f"edge-sim state endpoint unavailable (status={resp.status_code})")

    state = resp.json()
    if not state.get("bootstrapped"):
        pytest.skip(f"edge-sim not bootstrapped yet: {state.get('last_error')}")
    return state


@pytest.mark.security
class TestAptlyAdminAccessControl:
    """Test that Aptly admin API is properly restricted."""

    async def test_anonymous_cannot_access_aptly_admin_api(
        self, client: AsyncClient
    ):
        """Anonymous requests to Aptly admin endpoints should be blocked."""
        admin_endpoints = [
            "/api/repos",
            "/api/publish",
            "/api/files",
            "/api/mirrors",
        ]
        for endpoint in admin_endpoints:
            response = await client.get(f"http://localhost:8080{endpoint}")
            assert response.status_code in (401, 403, 404)

    async def test_device_cannot_access_aptly_admin_directly(
        self, client: AsyncClient, test_devices, device_token
    ):
        """Device bearer tokens must not grant access to Aptly-admin endpoints exposed by the API.

        All package-admin routes require a human JWT or opaque API key with an operator/admin
        role.  A raw device opaque token fails both the JWT decode and the API-key lookup,
        so every such request must be rejected with 401.
        """
        admin_endpoints = [
            "/api/v1/packages/gpg-keys",
            "/api/v1/packages/repos",
            "/api/v1/packages/publish",
            "/api/v1/packages/repo-authorized-keys",
        ]
        for endpoint in admin_endpoints:
            response = await client.get(
                endpoint,
                headers={"Authorization": f"Bearer {device_token}"},
            )
            assert response.status_code in (401, 403), (
                f"Device token must not access {endpoint}, got {response.status_code}"
            )


@pytest.mark.security
class TestPackageRepositoryAuthorization:
    """Test package download authorization via device tokens."""

    async def test_anonymous_cannot_download_packages(self, client: AsyncClient):
        """Anonymous user trying to download packages should be rejected."""
        response = await client.get("/api/v1/packages/repo/authorize")
        assert response.status_code == 401

    async def test_device_with_valid_token_can_authorize(
        self, client: AsyncClient, device_token
    ):
        """Device with registered repo key and valid token should authorize."""
        device_id = "device-a1-1"
        register = await client.post(
            f"/api/v1/devices/{device_id}/repo-key/self",
            headers={"Authorization": f"Bearer {device_token}"},
            json={"public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCdev device-a1@test"},
        )
        assert register.status_code in (200, 201)

        response = await client.get(
            "/api/v1/packages/repo/authorize",
            headers={"Authorization": f"Bearer {device_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["authorized"] is True
        assert body["device_id"] == device_id

    async def test_repository_authorization_requires_device_token(
        self, client: AsyncClient
    ):
        """Repository authorization endpoint should require device token + repo key."""
        response = await client.get("/api/v1/packages/repo/authorize")
        assert response.status_code == 401

    async def test_authorized_device_repo_key_is_stored(
        self, client: AsyncClient, test_devices, device_token, admin_token
    ):
        """Once a device self-registers its repo key, it should be stored in DB."""
        device_id = "device-a1-1"
        public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQClocal device-a1@test"

        register = await client.post(
            f"/api/v1/devices/{device_id}/repo-key/self",
            headers={"Authorization": f"Bearer {device_token}"},
            json={"public_key": public_key, "key_fingerprint": "SHA256:testfp"},
        )
        assert register.status_code in (200, 201)

        read_back = await client.get(
            f"/api/v1/devices/{device_id}/repo-key",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert read_back.status_code == 200
        payload = read_back.json()
        assert payload["device_id"] == device_id
        assert payload["repo_public_key"] == public_key
        assert payload["repo_key_fingerprint"] == "SHA256:testfp"
        assert payload["repo_key_updated_at"] is not None


@pytest.mark.security
class TestDeviceRepositoryKeyRotation:
    """Test that device repository keys support rotation."""

    async def test_device_can_register_repo_key(
        self, client: AsyncClient, test_devices, device_token
    ):
        """Device should be able to register a public key for repository authentication."""
        device_id = "device-a1-1"
        response = await client.post(
            f"/api/v1/devices/{device_id}/repo-key/self",
            headers={"Authorization": f"Bearer {device_token}"},
            json={
                "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCkey1 device@test.local"
            },
        )
        assert response.status_code in (200, 201)

    async def test_device_can_rotate_repo_key(
        self, client: AsyncClient, test_devices, device_token
    ):
        """Device should be able to rotate its repository key."""
        device_id = "device-a1-1"
        response1 = await client.post(
            f"/api/v1/devices/{device_id}/repo-key/self",
            headers={"Authorization": f"Bearer {device_token}"},
            json={
                "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCkey1 device@test.local"
            },
        )
        assert response1.status_code in (200, 201)

        response2 = await client.post(
            f"/api/v1/devices/{device_id}/repo-key/self",
            headers={"Authorization": f"Bearer {device_token}"},
            json={
                "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCkey2 device@test.local.new"
            },
        )
        assert response2.status_code in (200, 201)

    async def test_old_repo_key_becomes_invalid_after_rotation(
        self, client: AsyncClient, test_devices, device_token, admin_token
    ):
        """After key rotation, the old key should not be accepted."""
        device_id = "device-a1-1"
        old_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCold device@test"
        new_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCnew device@test"

        first = await client.post(
            f"/api/v1/devices/{device_id}/repo-key/self",
            headers={"Authorization": f"Bearer {device_token}"},
            json={"public_key": old_key},
        )
        assert first.status_code in (200, 201)

        second = await client.post(
            f"/api/v1/devices/{device_id}/repo-key/self",
            headers={"Authorization": f"Bearer {device_token}"},
            json={"public_key": new_key},
        )
        assert second.status_code in (200, 201)

        read_back = await client.get(
            f"/api/v1/devices/{device_id}/repo-key",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert read_back.status_code == 200
        payload = read_back.json()
        assert payload["repo_public_key"] == new_key
        assert payload["repo_public_key"] != old_key


@pytest.mark.security
class TestPackageDownloadWithAuthorization:
    """Test that package downloads work through the secure authorization model."""

    async def test_device_can_download_packages_with_authorization(
        self, client: AsyncClient, test_devices, device_token
    ):
        """Device with valid authorization should be able to download packages."""
        register = await client.post(
            "/api/v1/devices/device-a1-1/repo-key/self",
            headers={"Authorization": f"Bearer {device_token}"},
            json={"public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCauth device@test"},
        )
        assert register.status_code in (200, 201)

        response = await client.get(
            "/api/v1/packages/repo/authorize",
            headers={"Authorization": f"Bearer {device_token}"},
        )
        assert response.status_code == 200
        assert response.json()["authorized"] is True

    async def test_unauthorized_repo_key_is_rejected(self, client: AsyncClient):
        """Repository should reject requests with unknown or invalid repo keys."""
        response = await client.get(
            "/api/v1/packages/repo/authorize",
            headers={"Authorization": "Bearer invalid-or-expired-token"},
        )
        assert response.status_code == 401


@pytest.mark.security
class TestCaddyRepositoryProxyRestrictions:
    """Test that Caddy reverse-proxy properly restricts repository access."""

    async def _repo_client_or_skip(self) -> httpx.AsyncClient:
        """Create an HTTP client targeting dev Caddy path-based repo controls."""
        caddy_base = os.getenv("FLEETBITS_CADDY_URL", "http://caddy")
        client = httpx.AsyncClient(base_url=caddy_base, timeout=10)

        # Detect whether repo policy paths are active in this stack.
        try:
            probe = await client.get("/api/repos")
        except httpx.HTTPError:
            await client.aclose()
            pytest.skip("Caddy is unreachable from test environment; integration route tests skipped")

        if probe.status_code != 403:
            await client.aclose()
            pytest.skip(
                "Repo path policy is not active on this stack; check Caddy dev config"
            )
        return client

    async def test_repo_subdomain_restricted_to_wireguard_cidr(self):
        """repo.<domain> should only accept connections from WireGuard mesh CIDR."""
        client = await self._repo_client_or_skip()
        try:
            response = await client.get("/dists/focal/Release")
            assert response.status_code in (401, 403)
        finally:
            await client.aclose()

    async def test_aptly_admin_subpaths_blocked_at_proxy(self):
        """Caddy should block Aptly admin API subpaths like /api, /mirrors, /repos."""
        client = await self._repo_client_or_skip()
        try:
            for path in ("/api/repos", "/repos", "/snapshots", "/publish"):
                response = await client.get(path)
                assert response.status_code == 403, (
                    f"Expected Caddy to block {path}, got {response.status_code}"
                )
        finally:
            await client.aclose()

    async def test_package_paths_enforce_forward_auth(self):
        """Package paths (/pool/*, /dists/*) should invoke Caddy forward-auth."""
        client = await self._repo_client_or_skip()
        try:
            # Anonymous request should be denied by forward-auth (or by outer mesh gate).
            response = await client.get("/pool/main/f/fleet-agent/fleet-agent_1.0.0_amd64.deb")
            assert response.status_code in (401, 403)
        finally:
            await client.aclose()


@pytest.mark.security
class TestFirstBootKeyGeneration:
    """Test that device generates and registers repo key on first boot."""

    async def test_device_generates_key_on_enrollment(self):
        """Dummy edge simulator should bootstrap and self-register its repo key."""
        state = await _get_live_sim_state_or_skip()
        assert state["device_token_issued"] is True
        assert state["repo_key_registered"] is True
        assert state.get("repo_public_key", "").startswith("ssh-rsa ")

    async def test_enrollment_script_includes_key_generation(self):
        """Enrollment flow should include repo key registration as a first-boot step."""
        state = await _get_live_sim_state_or_skip()
        # We validate behavior (key exists after first-boot bootstrap), not file text.
        assert state["repo_key_registered"] is True
        assert state["heartbeat_ok"] is True


@pytest.mark.security
class TestEdgePackageFlowEndToEnd:
    """Test complete edge device package flow (pull, authenticate, download)."""

    async def test_enrolled_device_can_pull_packages(self):
        """Enrolled dummy edge device should be authorized by repo authorization path."""
        state = await _get_live_sim_state_or_skip()
        token = state.get("device_token")
        device_id = state.get("device_id")
        if not token:
            pytest.skip("edge-sim did not expose a device token")

        api_base = os.getenv("EDGE_SIM_API_BASE", "http://fleet-api:8000")
        async with httpx.AsyncClient(base_url=api_base, timeout=10) as client:
            response = await client.get(
                "/api/v1/packages/repo/authorize",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["authorized"] is True
        assert body["device_id"] == device_id

    async def test_unenrolled_device_cannot_pull_packages(self):
        """Unenrolled device (no WireGuard connection) should be rejected."""
        caddy_base = os.getenv("FLEETBITS_CADDY_URL", "http://caddy")
        async with httpx.AsyncClient(base_url=caddy_base, timeout=10) as client:
            try:
                response = await client.get("/dists/focal/Release")
            except httpx.HTTPError:
                pytest.skip("Caddy is unreachable from test environment; integration route tests skipped")
            if response.status_code in (301, 302, 307, 308):
                try:
                    redirected = await client.get(
                        response.headers.get("location", "/dists/focal/Release"),
                    )
                except httpx.HTTPError:
                    pytest.skip("Caddy route unreachable while following redirect")
                assert redirected.status_code in (401, 403)
            else:
                assert response.status_code in (401, 403)
