"""
Authorization scope boundary tests.

These tests verify that site-scoped users cannot access resources outside
their assigned site_scope, and that cross-site access returns fail-closed behavior.
"""

import pytest
from httpx import AsyncClient

from app.routers import deployments as deployments_router
from app.routers import observability as observability_router


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

    async def test_unscoped_operator_gets_no_service_health(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        """A non-admin token with no site scope must be refused, not served fleet-wide.

        There is no site to confine such a caller to. Before the shared
        predicate, both observability and telemetry treated it as unrestricted.
        """
        response = await client.get(
            "/api/v1/query/service-health",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
        )
        assert response.status_code == 403, (
            f"Scope-less operator must be refused, got {response.status_code}"
        )

    async def test_unscoped_operator_gets_no_alerts(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        """Same fail-closed rule on the Alertmanager proxy, before any upstream call."""
        response = await client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
        )
        assert response.status_code == 403, (
            f"Scope-less operator must be refused, got {response.status_code}"
        )
        assert not isinstance(response.json(), list), "No alert data may be returned"

    async def test_unscoped_operator_gets_no_recent_logs(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        """Same fail-closed rule on the Loki proxy, with no filter supplied."""
        response = await client.get(
            "/api/v1/query/recent-logs",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
        )
        assert response.status_code == 403, (
            f"Scope-less operator must be refused, got {response.status_code}"
        )

    async def test_unscoped_operator_gets_no_device_metrics(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        """Same fail-closed rule on device metrics, for a device that does exist."""
        response = await client.get(
            "/api/v1/query/device-metrics/device-a1-1",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
        )
        assert response.status_code == 403, (
            f"Scope-less operator must be refused, got {response.status_code}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Regression tests for the unified site-scope predicate
# (SPEC-cloisonnement-telemetrie, criteria 21 to 24)
#
# Nine routers used to carry their own copy of the predicate
# `role != "admin" and bool(site_scope)`. They now all call
# `app.routers._scope.require_site_scope`, which is strictly stricter:
#
#   * a non-`admin` token with no `site_scope` is refused outright (403) where
#     it used to be served fleet-wide;
#   * an `admin` token carrying a `site_scope` is confined to it where
#     `observability.py` and the nine inventory routers used to ignore the
#     scope entirely.
#
# Both halves are behaviour changes on security-sensitive paths, so both get a
# regression test here (GUIDELINES §3).
# ══════════════════════════════════════════════════════════════════════════════


class _UpstreamOkResponse:
    """Minimal stand-in for an `httpx.Response` from an observability backend."""

    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _UpstreamRecorder:
    """Stand-in for `httpx.AsyncClient` that records every upstream GET.

    Assertions about *whether* a backend was contacted need a recorder rather
    than a connection error: an unreachable backend answers 502, which is
    indistinguishable from a request that was never made.
    """

    def __init__(self, *args, **kwargs):
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None, **kwargs):
        self.calls.append({"url": url, "params": dict(params or {})})
        if "/api/v2/alerts" in url:
            return _UpstreamOkResponse([])
        return _UpstreamOkResponse({"status": "success", "data": {"result": []}})

    @property
    def forwarded_queries(self) -> list[str]:
        return [call["params"].get("query", "") for call in self.calls]


def _record_upstream(monkeypatch) -> _UpstreamRecorder:
    recorder = _UpstreamRecorder()
    monkeypatch.setattr(
        observability_router.httpx, "AsyncClient", lambda *a, **k: recorder
    )
    return recorder


@pytest.mark.security
class TestUnscopedOperatorInventoryBoundaries:
    """Criterion 24 — inventory answers the scope-less operator like telemetry does.

    The defect this closes: the same token was told "you are confined" by
    `/api/v1/query/service-health` (403) and "you are not" by `/api/v1/devices`
    (200 with three devices across site-a and site-b). One caller, two
    contradictory answers to the same question.
    """

    @pytest.mark.parametrize(
        "path", ["/api/v1/devices", "/api/v1/zones", "/api/v1/sites"]
    )
    async def test_unscoped_operator_gets_no_inventory(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices, path: str
    ):
        """No inventory listing may be served to a token with no site to confine it to."""
        response = await client.get(
            path,
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
        )
        assert response.status_code == 403, (
            f"{path} must refuse a scope-less operator, got {response.status_code}"
        )
        assert not isinstance(response.json(), list), (
            f"{path} returned a collection to a scope-less operator"
        )

    @pytest.mark.parametrize(
        "path", ["/api/v1/devices", "/api/v1/zones", "/api/v1/sites"]
    )
    async def test_admin_without_scope_still_reads_the_whole_fleet(
        self, client: AsyncClient, admin_token: str, test_devices, path: str
    ):
        """The legitimate fleet-wide caller is unaffected — the change is a tightening, not a lockout."""
        response = await client.get(
            path,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_unscoped_operator_sees_no_cross_site_devices(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        """Spelled out on the route that leaked the widest: three devices, two sites."""
        response = await client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
        )
        assert response.status_code == 403
        assert "device-b1-1" not in response.text
        assert "device-a1-1" not in response.text


@pytest.mark.security
class TestUnscopedOperatorMutationBoundaries:
    """Criterion 7 — the same fail-closed answer on the mutation paths of the nine routers.

    The unified predicate runs inside the handler, after body validation, so
    every body below is valid: a 422 here would prove nothing about authorization.
    """

    async def test_unscoped_operator_cannot_create_site(
        self, client: AsyncClient, unscoped_operator_token: str, test_sites
    ):
        response = await client.post(
            "/api/v1/sites",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={"site_id": "site-c", "name": "Site C", "timezone": "UTC"},
        )
        assert response.status_code == 403

    async def test_unscoped_operator_cannot_create_zone(
        self, client: AsyncClient, unscoped_operator_token: str, test_zones
    ):
        response = await client.post(
            "/api/v1/zones",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={
                "zone_id": "zone-c1",
                "site_id": "site-b",
                "name": "Zone C-1",
                "criticality": "standard",
            },
        )
        assert response.status_code == 403

    async def test_unscoped_operator_cannot_create_device(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        response = await client.post(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={
                "device_id": "device-b1-2",
                "zone_id": "zone-b1",
                "site_id": "site-b",
                "role": "kiosk",
                "hostname": "device-b1-2",
            },
        )
        assert response.status_code == 403

    async def test_unscoped_operator_cannot_update_other_site_device(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        response = await client.put(
            "/api/v1/devices/device-b1-1",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={"hostname": "renamed-by-unscoped-operator"},
        )
        assert response.status_code == 403

    async def test_unscoped_operator_cannot_create_profile(
        self, client: AsyncClient, unscoped_operator_token: str, test_profiles
    ):
        response = await client.post(
            "/api/v1/profiles",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={"profile_id": "profile-new", "name": "New", "baseline_stack": {}},
        )
        assert response.status_code == 403

    async def test_unscoped_operator_cannot_create_hotfix(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        response = await client.post(
            "/api/v1/hotfixes",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={
                "hotfix_id": "HF-UNSCOPED-001",
                "target_scope": {"siteId": "site-b"},
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "reason": "Scope-less operator boundary test",
                "requested_by": "security-test",
            },
        )
        assert response.status_code == 403

    async def test_unscoped_operator_cannot_create_override(
        self, client: AsyncClient, unscoped_operator_token: str, test_sites
    ):
        response = await client.post(
            "/api/v1/overrides",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={
                "scope": "site",
                "target_id": "site-b",
                "component": "fleet-agent",
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent=9.9.9",
                "reason": "Scope-less operator boundary test",
                "created_by": "security-test",
            },
        )
        assert response.status_code == 403

    async def test_unscoped_operator_cannot_create_deployment(
        self, client: AsyncClient, unscoped_operator_token: str, test_sites
    ):
        response = await client.post(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "rollout_mode": "ring-0",
                "target_scope": {"siteId": "site-b"},
                "requested_by": "security-test",
            },
        )
        assert response.status_code == 403

    async def test_unscoped_operator_cannot_restart_service(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices
    ):
        response = await client.post(
            "/api/v1/operations/restart-service",
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
            json={
                "device_id": "device-b1-1",
                "unit_name": "fleet-agent.service",
                "requested_by": "security-test",
            },
        )
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "path",
        ["/api/v1/deployments", "/api/v1/hotfixes", "/api/v1/overrides", "/api/v1/audit"],
    )
    async def test_unscoped_operator_gets_no_collection(
        self, client: AsyncClient, unscoped_operator_token: str, test_devices, path: str
    ):
        """The read paths of the remaining unified routers answer the same way."""
        response = await client.get(
            path,
            headers={"Authorization": f"Bearer {unscoped_operator_token}"},
        )
        assert response.status_code == 403, (
            f"{path} must refuse a scope-less operator, got {response.status_code}"
        )


@pytest.mark.security
class TestScopedAdminIsConfined:
    """Criterion 22 — an `admin` carrying a `site_scope` is confined by it.

    This is the half of decision 2 that was previously unguarded.
    `observability.py` and the nine inventory routers required
    `role != "admin"` before honouring the scope, so this exact token read the
    whole fleet. The shared predicate keys on the scope first, whatever the role.
    """

    async def test_scoped_admin_logs_carry_the_site_constraint(
        self, client: AsyncClient, scoped_admin_token: str, test_devices, monkeypatch
    ):
        """The LogQL selector built for a scoped admin names its site."""
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/query/recent-logs",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
        )
        assert response.status_code == 200
        assert recorder.forwarded_queries == ['{site="site-a"}'], (
            f"Scoped admin must be confined to site-a; forwarded {recorder.forwarded_queries!r}"
        )

    async def test_scoped_admin_service_health_carries_the_site_constraint(
        self, client: AsyncClient, scoped_admin_token: str, test_devices, monkeypatch
    ):
        """Same on the Prometheus side, where the scope is appended to the selector."""
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/query/service-health",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
        )
        assert response.status_code == 200
        assert recorder.forwarded_queries == [
            'systemd_unit_state{state="failed",site="site-a"}'
        ], f"forwarded {recorder.forwarded_queries!r}"

    async def test_scoped_admin_cannot_read_other_site_device_metrics(
        self, client: AsyncClient, scoped_admin_token: str, test_devices, monkeypatch
    ):
        """A device of another site is 404 for a scoped admin, with no upstream call."""
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/query/device-metrics/device-b1-1",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
        )
        assert response.status_code == 404
        assert recorder.calls == [], (
            f"Rejection must precede any upstream call; got {recorder.calls!r}"
        )

    async def test_scoped_admin_cannot_read_other_site_service_health(
        self, client: AsyncClient, scoped_admin_token: str, test_devices, monkeypatch
    ):
        """An explicit cross-site request is refused rather than honoured."""
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/query/service-health",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            params={"site": "site-b"},
        )
        assert response.status_code == 404
        assert recorder.calls == []

    async def test_scoped_admin_sees_only_own_site_devices(
        self, client: AsyncClient, scoped_admin_token: str, test_devices
    ):
        """The inventory routers confine the scoped admin too, not only telemetry."""
        response = await client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
        )
        assert response.status_code == 200
        device_ids = {device["device_id"] for device in response.json()}
        assert device_ids == {"device-a1-1", "device-a2-1"}, (
            f"Scoped admin must not see site-b devices; got {sorted(device_ids)}"
        )

    async def test_scoped_admin_sees_only_own_site_sites(
        self, client: AsyncClient, scoped_admin_token: str, test_devices
    ):
        response = await client.get(
            "/api/v1/sites",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
        )
        assert response.status_code == 200
        assert {site["site_id"] for site in response.json()} == {"site-a"}


@pytest.mark.security
class TestSiteScopeIsValidatedBeforeInterpolation:
    """Criterion 21 — `site_scope` is a label value, and is checked like one.

    `users.site_scope` is an unconstrained `Text` column, so a scope such as
    `site-a",job=~".*` used to be interpolated verbatim into every server-built
    expression: `/query/recent-logs` forwarded `{site="site-a",job=~".*"}` and
    `/query/service-health` forwarded
    `systemd_unit_state{state="failed",site="site-a",job=~".*"}` — the very
    selector-widening the client-side `_validate_label_value` exists to stop.
    """

    @pytest.mark.parametrize(
        "path", ["/api/v1/query/recent-logs", "/api/v1/query/service-health"]
    )
    async def test_injecting_scope_is_refused_not_interpolated(
        self, client: AsyncClient, injecting_scope_token: str, test_devices, monkeypatch, path: str
    ):
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            path,
            headers={"Authorization": f"Bearer {injecting_scope_token}"},
        )
        assert response.status_code == 400, (
            f"{path} must refuse a malformed site scope, got {response.status_code}"
        )
        assert recorder.calls == [], (
            f"No widened expression may reach an upstream; got {recorder.forwarded_queries!r}"
        )

    async def test_injecting_scope_never_widens_a_selector(
        self, client: AsyncClient, scoped_token: str, injecting_scope_token: str,
        test_devices, monkeypatch
    ):
        """Spelled out: the matcher the payload tries to smuggle in never ships.

        The well-formed scope runs first and is the control: it proves the route
        does reach the upstream and does build a selector, so that the emptiness
        observed for the payload afterwards means "refused", not "never ran".
        Without that control an `all(...)` over an empty list would pass even if
        the handler had crashed.
        """
        control = _record_upstream(monkeypatch)
        ok = await client.get(
            "/api/v1/query/recent-logs",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert ok.status_code == 200
        assert control.forwarded_queries == ['{site="site-a"}'], (
            f"control case must forward one confined selector; got "
            f"{control.forwarded_queries!r}"
        )

        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/query/recent-logs",
            headers={"Authorization": f"Bearer {injecting_scope_token}"},
        )
        assert response.status_code == 400
        assert recorder.forwarded_queries == [], (
            f"the payload must reach no upstream at all; got "
            f"{recorder.forwarded_queries!r}"
        )
        assert all("job=~" not in query for query in recorder.forwarded_queries)

    async def test_trailing_newline_scope_is_refused(
        self, client: AsyncClient, trailing_newline_scope_token: str, test_devices, monkeypatch
    ):
        """The label-value anchor is `\\Z`, not `$`.

        `$` also matches just before a trailing newline, so `site-a\\n` passed
        `_validate_label_value` and was interpolated with the newline still on
        it. Not a widening on its own — the character class excludes the quote,
        comma, brace, equals and tilde — but a malformed label value must not be
        called well-formed.
        """
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/query/recent-logs",
            headers={"Authorization": f"Bearer {trailing_newline_scope_token}"},
        )
        assert response.status_code == 400, (
            f"A scope with a trailing newline is not a valid label value; "
            f"got {response.status_code}"
        )
        assert recorder.forwarded_queries == [], (
            f"nothing may be forwarded; got {recorder.forwarded_queries!r}"
        )

    async def test_injecting_scope_is_refused_on_device_metrics(
        self, client: AsyncClient, injecting_scope_token: str, test_devices, monkeypatch
    ):
        """The device path resolves the scope in the database, and refuses it just the same."""
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/query/device-metrics/device-a1-1",
            headers={"Authorization": f"Bearer {injecting_scope_token}"},
        )
        assert response.status_code == 400
        assert recorder.calls == []


@pytest.mark.security
class TestAlertsScopeSettledBeforeUpstream:
    """Criterion 23 — the cross-site rejection of `/alerts` precedes the fetch.

    The predicate already ran before the upstream call, but the
    `site != scope` rejection ran after it: a site-a token asking for
    `?site=site-b` caused a real Alertmanager fetch before its 404. Nothing
    leaked, yet the request was issued for a caller with no right to the answer.
    """

    async def test_cross_site_alert_request_reaches_no_upstream(
        self, client: AsyncClient, scoped_token: str, test_devices, monkeypatch
    ):
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"site": "site-b"},
        )
        assert response.status_code == 404
        assert recorder.calls == [], (
            f"Alertmanager was contacted before the rejection; got {recorder.calls!r}"
        )

    async def test_own_site_alert_request_still_reaches_upstream(
        self, client: AsyncClient, scoped_token: str, test_devices, monkeypatch
    ):
        """The reordering must not turn a legitimate request into a rejection."""
        recorder = _record_upstream(monkeypatch)
        response = await client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"site": "site-a"},
        )
        assert response.status_code == 200
        assert len(recorder.calls) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Criterion 25 — the fleet-wide roles keep exactly what they had.
#
# The first shape of the shared predicate refused *every* non-`admin` token that
# carried no `site_scope`. That wording aimed at the human operator but caught the
# service roles with it: a `ci_bot` key — which `ApiKeyCreate` mints with
# `role="ci_bot"`, `site_scope=None` — lost `POST /deployments` and
# `POST /deployments/{id}/trigger` outright, which in turn made the two ring-0
# rules of `deployments.py` unreachable code; and a fleet-wide `viewer` lost every
# inventory read. Decision 2 now keys on what the data model says about each role.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.security
class TestCiBotKeepsItsDeploymentCapabilities:
    """A default-shaped CI key still creates and triggers ring-0 deployments."""

    async def test_ci_bot_without_scope_creates_a_ring_0_deployment(
        self, client: AsyncClient, ci_bot_token: str, test_sites
    ):
        response = await client.post(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {ci_bot_token}"},
            json={
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "rollout_mode": "ring-0",
                "target_scope": {"siteId": "site-a"},
                "requested_by": "ci",
            },
        )
        assert response.status_code == 201, (
            "A scope-less ci_bot is the normal shape of a CI key and must still "
            f"create ring-0 deployments; got {response.status_code} {response.text}"
        )

    async def test_ci_bot_ring_0_restriction_on_create_is_live_code(
        self, client: AsyncClient, ci_bot_token: str, test_sites
    ):
        """The rule is only a rule if the path reaches it: ring-1 must be refused *by it*."""
        response = await client.post(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {ci_bot_token}"},
            json={
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "rollout_mode": "ring-1",
                "target_scope": {"siteId": "site-a"},
                "requested_by": "ci",
            },
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "CI bot may only create ring-0 deployments", (
            "The refusal must come from the ring-0 rule, not from the scope predicate"
        )

    async def test_ci_bot_without_scope_triggers_a_ring_0_deployment(
        self, client: AsyncClient, ci_bot_token: str, test_sites, monkeypatch
    ):
        created = await client.post(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {ci_bot_token}"},
            json={
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "rollout_mode": "ring-0",
                "target_scope": {"siteId": "site-a"},
                "requested_by": "ci",
            },
        )
        assert created.status_code == 201
        deployment_id = created.json()["deployment_id"]

        async def _fake_trigger_job(**kwargs):
            return "4242"

        monkeypatch.setattr(deployments_router.sem, "trigger_job", _fake_trigger_job)

        response = await client.post(
            f"/api/v1/deployments/{deployment_id}/trigger",
            headers={"Authorization": f"Bearer {ci_bot_token}"},
            json={},
        )
        assert response.status_code == 200, (
            f"A scope-less ci_bot must still trigger its ring-0 deployment; "
            f"got {response.status_code} {response.text}"
        )
        assert response.json()["status"] == "deploying"

    async def test_ci_bot_ring_0_restriction_on_trigger_is_live_code(
        self, client: AsyncClient, ci_bot_token: str, admin_token: str, test_sites, monkeypatch
    ):
        """A ring-1 deployment exists only via an admin; the ci_bot must be refused by the rule."""
        created = await client.post(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "rollout_mode": "ring-1",
                "target_scope": {"siteId": "site-a"},
                "requested_by": "admin",
            },
        )
        assert created.status_code == 201
        deployment_id = created.json()["deployment_id"]

        async def _fake_trigger_job(**kwargs):
            raise AssertionError("Semaphore must not be reached for a refused trigger")

        monkeypatch.setattr(deployments_router.sem, "trigger_job", _fake_trigger_job)

        response = await client.post(
            f"/api/v1/deployments/{deployment_id}/trigger",
            headers={"Authorization": f"Bearer {ci_bot_token}"},
            json={},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "CI bot may only trigger ring-0 deployments"

    async def test_scoped_ci_bot_is_still_confined(
        self, client: AsyncClient, scoped_ci_bot_token: str, test_sites
    ):
        """A CI key that *does* carry a scope stays confined — the tightening is not undone."""
        response = await client.post(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {scoped_ci_bot_token}"},
            json={
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "rollout_mode": "ring-0",
                "target_scope": {"siteId": "site-b"},
                "requested_by": "ci",
            },
        )
        assert response.status_code == 403, (
            "A ci_bot carrying site-a must not deploy to site-b"
        )
        assert response.json()["detail"] == "Access denied"


@pytest.mark.security
class TestFleetWideViewerKeepsItsReads:
    """A fleet-wide `viewer` reads the inventory; a scopable role with no scope does not."""

    @pytest.mark.parametrize(
        "path", ["/api/v1/devices", "/api/v1/zones", "/api/v1/sites"]
    )
    async def test_viewer_without_scope_still_reads_inventory(
        self, client: AsyncClient, viewer_token: str, test_devices, path: str
    ):
        response = await client.get(
            path, headers={"Authorization": f"Bearer {viewer_token}"}
        )
        assert response.status_code == 200, (
            f"{path} must still serve a fleet-wide viewer; got {response.status_code}"
        )
        assert isinstance(response.json(), list)

    async def test_viewer_without_scope_sees_both_sites(
        self, client: AsyncClient, viewer_token: str, test_devices
    ):
        """Spelled out: `viewer` is a fleet-wide read role, so the fleet is what it reads."""
        response = await client.get(
            "/api/v1/devices", headers={"Authorization": f"Bearer {viewer_token}"}
        )
        assert response.status_code == 200
        sites = {device["site_id"] for device in response.json()}
        assert sites == {"site-a", "site-b"}, f"viewer saw only {sites!r}"

    async def test_scoped_viewer_is_still_confined(
        self, client: AsyncClient, scoped_viewer_token: str, test_devices
    ):
        """A `viewer` that carries a scope is confined by it, like any other role."""
        response = await client.get(
            "/api/v1/devices", headers={"Authorization": f"Bearer {scoped_viewer_token}"}
        )
        assert response.status_code == 200
        sites = {device["site_id"] for device in response.json()}
        assert sites == {"site-a"}, f"A viewer scoped to site-a saw {sites!r}"

    @pytest.mark.parametrize(
        "path", ["/api/v1/devices", "/api/v1/zones", "/api/v1/sites"]
    )
    async def test_technician_without_scope_is_still_refused(
        self, client: AsyncClient, technician_token: str, test_devices, path: str
    ):
        """`technician` is the second scopable role: no scope is an anomaly, not a shape."""
        response = await client.get(
            path, headers={"Authorization": f"Bearer {technician_token}"}
        )
        assert response.status_code == 403, (
            f"{path} must refuse a scope-less technician; got {response.status_code}"
        )

    async def test_unknown_role_without_scope_is_refused(
        self, client: AsyncClient, unknown_role_token: str, test_devices
    ):
        """The fleet-wide set is an allow-list: an unrecognised role is refused, not served."""
        response = await client.get(
            "/api/v1/devices", headers={"Authorization": f"Bearer {unknown_role_token}"}
        )
        assert response.status_code == 403
        assert "site scope" in response.json()["detail"], (
            "The refusal must come from the scope predicate, not from a role gate"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Criterion 26 — the scoped admin on the mutation paths.
#
# `TestScopedAdminIsConfined` above covers reads. The same token also flips from
# allowed to refused on every mutation path of the unified routers, and
# GUIDELINES §3 wants a regression test for each such transition, not only for
# the ones that were convenient to reach.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.security
class TestScopedAdminIsConfinedOnMutationPaths:
    """An `admin` carrying `site-a` creates nothing on site-b and mutates nothing outside it."""

    async def test_scoped_admin_cannot_create_a_site_other_than_its_own(
        self, client: AsyncClient, scoped_admin_token: str, test_sites
    ):
        response = await client.post(
            "/api/v1/sites",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={"site_id": "site-c", "name": "Site C"},
        )
        assert response.status_code == 403

    async def test_scoped_admin_cannot_create_a_zone_on_another_site(
        self, client: AsyncClient, scoped_admin_token: str, test_sites
    ):
        response = await client.post(
            "/api/v1/zones",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={
                "zone_id": "zone-b2",
                "site_id": "site-b",
                "name": "Zone B2",
                "profile_id": "profile-default",
            },
        )
        assert response.status_code == 403

    async def test_scoped_admin_cannot_create_a_device_on_another_site(
        self, client: AsyncClient, scoped_admin_token: str, test_devices
    ):
        response = await client.post(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={
                "device_id": "device-b2-1",
                "site_id": "site-b",
                "zone_id": "zone-b1",
                "profile_id": "profile-default",
                "role": "kiosk",
                "hostname": "device-b2-1",
            },
        )
        assert response.status_code == 403

    async def test_scoped_admin_cannot_move_a_device_to_another_site(
        self, client: AsyncClient, scoped_admin_token: str, test_devices
    ):
        response = await client.put(
            "/api/v1/devices/device-a1-1",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={"site_id": "site-b"},
        )
        assert response.status_code == 403

    async def test_scoped_admin_cannot_mutate_another_site_device(
        self, client: AsyncClient, scoped_admin_token: str, test_devices
    ):
        """Out-of-scope resources answer 404, not 403 — no enumeration through the mutation path."""
        response = await client.put(
            "/api/v1/devices/device-b1-1",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={"hostname": "renamed-by-scoped-admin"},
        )
        assert response.status_code == 404

    async def test_scoped_admin_cannot_create_a_fleet_profile(
        self, client: AsyncClient, scoped_admin_token: str, test_sites
    ):
        """Profiles carry no `site_id`: a fleet object is out of reach of a confined caller."""
        response = await client.post(
            "/api/v1/profiles",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={
                "profile_id": "profile-scoped-admin",
                "name": "Scoped admin profile",
                "baseline_stack": {},
            },
        )
        assert response.status_code == 403

    async def test_scoped_admin_cannot_update_a_fleet_profile(
        self, client: AsyncClient, scoped_admin_token: str, test_profiles
    ):
        response = await client.put(
            "/api/v1/profiles/profile-default",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={"name": "Renamed by scoped admin"},
        )
        assert response.status_code == 403

    async def test_scoped_admin_cannot_delete_a_fleet_profile(
        self, client: AsyncClient, scoped_admin_token: str, test_profiles
    ):
        response = await client.delete(
            "/api/v1/profiles/profile-default",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
        )
        assert response.status_code == 403

    async def test_scoped_admin_cannot_create_a_deployment_on_another_site(
        self, client: AsyncClient, scoped_admin_token: str, test_sites
    ):
        response = await client.post(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "rollout_mode": "ring-1",
                "target_scope": {"siteId": "site-b"},
                "requested_by": "scoped-admin",
            },
        )
        assert response.status_code == 403

    async def test_scoped_admin_can_still_create_on_its_own_site(
        self, client: AsyncClient, scoped_admin_token: str, test_sites
    ):
        """The confinement is a boundary, not a lockout: inside site-a the admin still acts."""
        response = await client.post(
            "/api/v1/deployments",
            headers={"Authorization": f"Bearer {scoped_admin_token}"},
            json={
                "artifact_type": "deb",
                "artifact_ref": "fleet-agent-9.9.9",
                "rollout_mode": "ring-1",
                "target_scope": {"siteId": "site-a"},
                "requested_by": "scoped-admin",
            },
        )
        assert response.status_code == 201, response.text


# ══════════════════════════════════════════════════════════════════════════════
# `GET /devices/mqtt/acl` is an inventory listing too.
#
# It enumerates every device's MQTT identity and topic namespace and applied no
# scope at all, so a site-a operator received `device_device-b1-1` and
# `device/device-b1-1/#`. It is one of the routes the unified predicate covers,
# and `SECURITY_ROADMAP.md` S0.1-S0.3 asserts that every router scope is
# enforced — GUIDELINES §6 forbids leaving that assertion false.
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.security
class TestMqttAclIsSiteScoped:
    """The broker ACL listing is confined like every other device listing."""

    async def test_scoped_operator_gets_only_its_own_site_identities(
        self, client: AsyncClient, scoped_token: str, test_devices, test_db
    ):
        await _set_mqtt_usernames(test_db)
        response = await client.get(
            "/api/v1/devices/mqtt/acl",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        assert response.status_code == 200
        acl = response.json()
        assert "device_device-a1-1" in acl, f"own-site identity missing: {acl!r}"
        assert "device_device-b1-1" not in acl, (
            f"site-a operator received a site-b MQTT identity: {acl!r}"
        )
        assert "device/device-b1-1/#" not in str(acl), (
            f"site-a operator received a site-b topic pattern: {acl!r}"
        )

    async def test_fleet_wide_admin_still_gets_the_whole_acl(
        self, client: AsyncClient, admin_token: str, test_devices, test_db
    ):
        """The broker bootstrap needs the full fleet — a fleet-wide token still gets it."""
        await _set_mqtt_usernames(test_db)
        response = await client.get(
            "/api/v1/devices/mqtt/acl",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        acl = response.json()
        assert "device_device-a1-1" in acl
        assert "device_device-b1-1" in acl
        assert acl["fleet_exporter"] == ["$SYS/#"]


async def _set_mqtt_usernames(test_db) -> None:
    """Give one device per site an MQTT identity, so the ACL listing has both sites in it."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.device import Device

    async with AsyncSession(test_db, expire_on_commit=False) as session:
        for device_id in ("device-a1-1", "device-b1-1"):
            await session.execute(
                update(Device)
                .where(Device.device_id == device_id)
                .values(mqtt_username=f"device_{device_id}")
            )
        await session.commit()
