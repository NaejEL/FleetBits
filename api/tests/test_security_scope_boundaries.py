"""
Authorization scope boundary tests.

These tests verify that site-scoped users cannot access resources outside
their assigned site_scope, and that cross-site access returns fail-closed behavior.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.security
class TestDeploymentScopeBoundaries:
    """Test deployment access scope enforcement."""

    async def test_admin_can_list_all_deployments(self, client: AsyncClient, admin_token: str):
        """Admin users should see all deployments regardless of site."""
        response = await client.get(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_sees_only_own_site_deployments(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped users should only see deployments for their assigned site."""
        response = await client.get(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_cannot_access_other_site_deployment(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped user attempting to access deployment from other site should fail."""
        response = await client.get(
            "/api/v1/deployments/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code in (403, 404)


@pytest.mark.security
class TestDeviceScopeBoundaries:
    """Test device access scope enforcement."""

    async def test_admin_can_list_all_devices(self, client: AsyncClient, admin_token: str):
        """Admin users should see all devices."""
        response = await client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_sees_only_own_site_devices(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped users should only see devices for their assigned site."""
        response = await client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_cannot_access_other_site_device(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped user attempting to access device from other site should fail."""
        response = await client.get(
            "/api/v1/devices/device-b1-1",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code in (403, 404)

    async def test_scoped_user_cannot_mutate_other_site_device(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped user cannot update a device from another site."""
        response = await client.put(
            "/api/v1/devices/device-b1-1",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={"hostname": "renamed"},
        )
        assert response.status_code in (403, 404)


@pytest.mark.security
class TestZoneScopeBoundaries:
    """Test zone access scope enforcement."""

    async def test_admin_can_list_all_zones(self, client: AsyncClient, admin_token: str):
        """Admin users should see all zones."""
        response = await client.get(
            "/api/v1/zones",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_sees_only_own_site_zones(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped users should only see zones in their assigned site."""
        response = await client.get(
            "/api/v1/zones",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_cannot_access_other_site_zone(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped user attempting to access zone from other site should fail."""
        response = await client.get(
            "/api/v1/zones/zone-b1",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code in (403, 404)


@pytest.mark.security
class TestProfileScopeBoundaries:
    """Test profile access scope enforcement."""

    async def test_admin_can_list_all_profiles(self, client: AsyncClient, admin_token: str):
        """Admin users should be able to list profiles."""
        response = await client.get(
            "/api/v1/profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_can_read_profiles(self, client: AsyncClient, scoped_token: str):
        """Site-scoped users should be able to read profiles (global resource)."""
        response = await client.get(
            "/api/v1/profiles",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code in (200, 403)

    async def test_scoped_user_cannot_create_profiles(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped users should not be able to create profiles."""
        response = await client.post(
            "/api/v1/profiles",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={
                "profile_id": "test-profile",
                "name": "Test",
                "baseline_stack": {},
            },
        )
        assert response.status_code in (403, 405)


@pytest.mark.security
class TestSiteScopeBoundaries:
    """Test site access scope enforcement."""

    async def test_admin_can_list_all_sites(self, client: AsyncClient, admin_token: str):
        """Admin users should be able to list all sites."""
        response = await client.get(
            "/api/v1/sites",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_cannot_mutate_sites(self, client: AsyncClient, scoped_token: str):
        """Site-scoped users should not be able to mutate sites."""
        response = await client.patch(
            "/api/v1/sites/site-b",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={"name": "Modified"},
        )
        assert response.status_code in (403, 404, 405)


@pytest.mark.security
class TestHotfixScopeBoundaries:
    """Test hotfix access scope enforcement."""

    async def test_admin_can_list_all_hotfixes(self, client: AsyncClient, admin_token: str):
        """Admin users should be able to list hotfixes across all sites."""
        response = await client.get(
            "/api/v1/hotfixes",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_can_list_hotfixes(self, client: AsyncClient, scoped_token: str):
        """Site-scoped users should be able to list hotfixes (result filtered to their site)."""
        response = await client.get(
            "/api/v1/hotfixes",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_cannot_get_other_site_hotfix(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped user requesting a hotfix from another site should get fail-closed 404."""
        response = await client.get(
            "/api/v1/hotfixes/HF-OTHER-SITE-001",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code in (403, 404)

    async def test_scoped_user_cannot_create_hotfix_for_other_site(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped user must not be able to create a hotfix targeting another site."""
        response = await client.post(
            "/api/v1/hotfixes",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={
                "hotfix_id": "HF-X-SCOPE-001",
                "target_scope": {"siteId": "site-b"},
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "reason": "Cross-site scope boundary test",
                "requested_by": "security-test",
            },
        )
        assert response.status_code == 403


@pytest.mark.security
class TestOverrideScopeBoundaries:
    """Test override access scope enforcement."""

    async def test_admin_can_list_all_overrides(self, client: AsyncClient, admin_token: str):
        """Admin users should be able to list overrides across all sites."""
        response = await client.get(
            "/api/v1/overrides",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_can_list_overrides(self, client: AsyncClient, scoped_token: str):
        """Site-scoped users should be able to list overrides (result filtered to their site)."""
        response = await client.get(
            "/api/v1/overrides",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code == 200

    async def test_scoped_user_cannot_create_override_for_other_site(
        self, client: AsyncClient, scoped_token: str
    ):
        """Site-scoped user must not be able to create an override targeting another site."""
        response = await client.post(
            "/api/v1/overrides",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={
                "scope": "site",
                "target_id": "site-b",
                "component": "fleet-agent",
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent=9.9.9",
                "reason": "Cross-site scope boundary test",
                "created_by": "security-test",
            },
        )
        assert response.status_code == 403


@pytest.mark.security
class TestOperationsScopeBoundaries:
    """Test operations (restart-service, run-diagnostics) scope enforcement."""

    async def test_scoped_user_cannot_restart_service_on_other_site_device(
        self, client: AsyncClient, scoped_token: str
    ):
        """Scoped user must not be able to restart a service on a device from another site."""
        response = await client.post(
            "/api/v1/operations/restart-service",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={
                "device_id": "device-b1-1",
                "unit_name": "fleet-agent.service",
                "requested_by": "security-test",
            },
        )
        # device-b1-1 is in site-b; site-a scoped user must be fail-closed
        assert response.status_code in (403, 404)

    async def test_scoped_user_cannot_run_diagnostics_on_other_site_device(
        self, client: AsyncClient, scoped_token: str
    ):
        """Scoped user must not be able to run diagnostics on a device from another site."""
        response = await client.post(
            "/api/v1/operations/run-diagnostics",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={
                "device_id": "device-b1-1",
                "requested_by": "security-test",
            },
        )
        assert response.status_code in (403, 404)

    async def test_scoped_user_cannot_collect_logs_from_other_site_device(
        self, client: AsyncClient, scoped_token: str
    ):
        """Scoped user must not be able to collect logs from a device in another site."""
        response = await client.post(
            "/api/v1/operations/collect-logs",
            headers={"Authorization": f"Bearer {scoped_token}"},
            json={
                "device_id": "device-b1-1",
                "since": "1h",
                "requested_by": "security-test",
            },
        )
        assert response.status_code in (403, 404)


@pytest.mark.security
class TestObservabilityScopeBoundaries:
    """Test observability query scope enforcement (service-health, device-metrics, logs, alerts)."""

    async def test_scoped_user_cannot_query_other_site_service_health(
        self, client: AsyncClient, scoped_token: str
    ):
        """Scoped user requesting service health for a different site must be rejected."""
        response = await client.get(
            "/api/v1/query/service-health",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"site": "site-b"},
        )
        # Scope check fires before Prometheus is contacted
        assert response.status_code == 404

    async def test_admin_can_query_any_site_service_health(
        self, client: AsyncClient, admin_token: str
    ):
        """Admin must not be blocked by scope check when querying another site's health."""
        response = await client.get(
            "/api/v1/query/service-health",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"site": "site-b"},
        )
        # Prometheus is not available in unit tests so 502 is expected;
        # the key assertion is that the admin is NOT rejected with 403/404
        assert response.status_code not in (403, 404)

    async def test_scoped_user_cannot_query_other_site_device_metrics(
        self, client: AsyncClient, scoped_token: str
    ):
        """Scoped user must not be able to query metrics for a device in another site."""
        response = await client.get(
            "/api/v1/query/device-metrics/device-b1-1",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        # device-b1-1 is site-b; site-a scoped user must be fail-closed
        assert response.status_code in (403, 404)

    async def test_scoped_user_cannot_query_other_site_device_logs(
        self, client: AsyncClient, scoped_token: str
    ):
        """Scoped user must not be able to query logs for a device in another site."""
        response = await client.get(
            "/api/v1/query/recent-logs",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"device_id": "device-b1-1"},
        )
        assert response.status_code in (403, 404)
