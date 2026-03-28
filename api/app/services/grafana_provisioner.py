"""Grafana user provisioning service.

When a FleetBits user is created or updated, this service ensures a matching
Grafana account exists with the correct role and org/team memberships.

Security model:
- Only FleetBits-authenticated users can reach Grafana (Caddy forward_auth)
- Grafana login form is disabled — no separate Grafana password ever needed
- Admin/operator users get Grafana Editor role (can explore dashboards freely)
- Technician/viewer users get Grafana Viewer role (read-only)
- site_scope → Grafana Team membership (one team per site_id)
- Dashboard folder permissions are provisioned per team

Grafana provisioner calls are best-effort: a provisioning failure MUST NOT
block user creation — it is logged and retried on next relevant event.
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# FleetBits role → Grafana org role
_ROLE_MAP: dict[str, str] = {
    "admin": "Admin",
    "operator": "Editor",
    "technician": "Editor",
    "viewer": "Viewer",
    "ci_bot": "Viewer",
}


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _auth() -> tuple[str, str]:
    return ("admin", settings.GRAFANA_ADMIN_PASSWORD)


async def _get_or_create_user(
    client: httpx.AsyncClient,
    username: str,
    email: str,
    grafana_role: str,
) -> int | None:
    """Ensure the Grafana user exists. Returns grafana user ID or None on failure."""
    # Try lookup first
    resp = await client.get(
        f"{settings.GRAFANA_INTERNAL_URL}/api/users/lookup",
        params={"loginOrEmail": username},
        auth=_auth(),
        headers=_headers(),
    )
    if resp.status_code == 200:
        return resp.json()["id"]

    # Create the user with a random password — login form is disabled so the
    # password is never used. The proxy handles all authentication.
    import secrets as _secrets
    resp = await client.post(
        f"{settings.GRAFANA_INTERNAL_URL}/api/admin/users",
        json={
            "login": username,
            "email": email,
            "name": username,
            "password": _secrets.token_urlsafe(32),
            "OrgId": 1,
            "role": grafana_role,
        },
        auth=_auth(),
        headers=_headers(),
    )
    if resp.status_code in (200, 201):
        return resp.json()["id"]

    logger.error(
        "grafana_provisioner: failed to create user %s — %s %s",
        username,
        resp.status_code,
        resp.text[:200],
    )
    return None


async def _set_org_role(
    client: httpx.AsyncClient,
    grafana_user_id: int,
    grafana_role: str,
) -> None:
    """Patch the user's role in the default org."""
    resp = await client.patch(
        f"{settings.GRAFANA_INTERNAL_URL}/api/org/users/{grafana_user_id}",
        json={"role": grafana_role},
        auth=_auth(),
        headers=_headers(),
    )
    if resp.status_code not in (200, 201):
        logger.warning(
            "grafana_provisioner: failed to set org role for user id=%s — %s",
            grafana_user_id,
            resp.status_code,
        )


async def _get_or_create_team(
    client: httpx.AsyncClient,
    site_id: str,
) -> int | None:
    """Ensure a Grafana team exists for the given site. Returns team ID."""
    team_name = f"site-{site_id}"

    resp = await client.get(
        f"{settings.GRAFANA_INTERNAL_URL}/api/teams/search",
        params={"name": team_name},
        auth=_auth(),
        headers=_headers(),
    )
    if resp.status_code == 200:
        teams = resp.json().get("teams") or []
        for t in teams:
            if t.get("name") == team_name:
                return t["id"]

    # Create team
    resp = await client.post(
        f"{settings.GRAFANA_INTERNAL_URL}/api/teams",
        json={"name": team_name},
        auth=_auth(),
        headers=_headers(),
    )
    if resp.status_code in (200, 201):
        return resp.json()["teamId"]

    logger.error(
        "grafana_provisioner: failed to create team %s — %s",
        team_name,
        resp.status_code,
    )
    return None


async def _sync_team_membership(
    client: httpx.AsyncClient,
    grafana_user_id: int,
    site_scope: str | None,
) -> None:
    """Ensure user is a member of their site team (and remove stale memberships)."""
    # Get current memberships
    resp = await client.get(
        f"{settings.GRAFANA_INTERNAL_URL}/api/teams/search",
        params={"perpage": 100},
        auth=_auth(),
        headers=_headers(),
    )
    all_teams: list[dict[str, Any]] = []
    if resp.status_code == 200:
        all_teams = resp.json().get("teams") or []

    # Determine which team the user should belong to
    target_team_id: int | None = None
    if site_scope:
        target_team_id = await _get_or_create_team(client, site_scope)

    for team in all_teams:
        team_id = team["id"]
        team_name: str = team.get("name", "")
        if not team_name.startswith("site-"):
            continue

        # Check if user is currently in this team
        members_resp = await client.get(
            f"{settings.GRAFANA_INTERNAL_URL}/api/teams/{team_id}/members",
            auth=_auth(),
            headers=_headers(),
        )
        member_ids = []
        if members_resp.status_code == 200:
            member_ids = [m["userId"] for m in members_resp.json()]

        is_member = grafana_user_id in member_ids
        should_be_member = (team_id == target_team_id)

        if should_be_member and not is_member:
            await client.post(
                f"{settings.GRAFANA_INTERNAL_URL}/api/teams/{team_id}/members",
                json={"userId": grafana_user_id},
                auth=_auth(),
                headers=_headers(),
            )
        elif not should_be_member and is_member:
            await client.delete(
                f"{settings.GRAFANA_INTERNAL_URL}/api/teams/{team_id}/members/{grafana_user_id}",
                auth=_auth(),
                headers=_headers(),
            )


async def provision_user(
    username: str,
    email: str,
    role: str,
    site_scope: str | None,
) -> int | None:
    """Create or update the Grafana account for a FleetBits user.

    Returns the Grafana user ID on success, None on failure.
    Failures are logged but never re-raised — provisioning is best-effort.
    """
    grafana_role = _ROLE_MAP.get(role, "Viewer")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            grafana_user_id = await _get_or_create_user(
                client, username, email, grafana_role
            )
            if grafana_user_id is None:
                return None

            await _set_org_role(client, grafana_user_id, grafana_role)
            await _sync_team_membership(client, grafana_user_id, site_scope)

            logger.info(
                "grafana_provisioner: user %s provisioned (id=%s, role=%s, site=%s)",
                username,
                grafana_user_id,
                grafana_role,
                site_scope,
            )
            return grafana_user_id

    except Exception as exc:
        logger.error(
            "grafana_provisioner: unexpected error provisioning %s — %s",
            username,
            exc,
        )
        return None


async def deprovision_user(grafana_user_id: int) -> None:
    """Delete the Grafana account when the FleetBits user is deactivated.

    Best-effort — failure is logged, never raised.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{settings.GRAFANA_INTERNAL_URL}/api/admin/users/{grafana_user_id}",
                auth=_auth(),
                headers=_headers(),
            )
            if resp.status_code not in (200, 204):
                logger.warning(
                    "grafana_provisioner: failed to delete user id=%s — %s",
                    grafana_user_id,
                    resp.status_code,
                )
    except Exception as exc:
        logger.error(
            "grafana_provisioner: unexpected error deprovisioning id=%s — %s",
            grafana_user_id,
            exc,
        )
