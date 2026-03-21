"""Variant resolution — merges profile baseline with site/zone/device overrides.

Resolution order (later layers win):
  profile.baseline_stack.components
      → site overrides
      → zone overrides
      → device overrides
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deployment import Override
from app.models.device import Device
from app.models.profile import Profile
from app.models.zone import Zone


async def resolve_manifest(db: AsyncSession, *, device_id: str) -> dict | None:
    """Return the fully-resolved component manifest for a device.

    Returns None if the device does not exist.
    Each component is keyed by its name; the final dict is flattened to a list
    for the response payload so the shape matches §5.2.
    """
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        return None

    # Layer 1 — profile baseline
    components: dict[str, dict] = {}
    profile_id: str | None = None

    if device.zone_id:
        zone_result = await db.execute(select(Zone).where(Zone.zone_id == device.zone_id))
        zone = zone_result.scalar_one_or_none()
        if zone and zone.profile_id:
            profile_id = zone.profile_id
            profile_result = await db.execute(
                select(Profile).where(Profile.profile_id == zone.profile_id)
            )
            profile = profile_result.scalar_one_or_none()
            if profile:
                for comp in profile.baseline_stack.get("components", []):
                    components[comp["name"]] = {**comp, "origin": "profile"}

    # Layers 2-4 — site / zone / device overrides (non-reconciled, non-expired)
    now = datetime.now(UTC)
    applied: list[str] = []

    scopes: list[tuple[str, str]] = []
    if device.site_id:
        scopes.append(("site", device.site_id))
    if device.zone_id:
        scopes.append(("zone", device.zone_id))
    scopes.append(("device", device_id))

    for scope, target_id in scopes:
        ovr_result = await db.execute(
            select(Override).where(
                Override.scope == scope,
                Override.target_id == target_id,
                Override.reconciled.is_(False),
            )
        )
        for ov in ovr_result.scalars().all():
            if ov.expires_at and ov.expires_at < now:
                continue  # skip expired overrides
            origin = f"override:{scope}:{target_id}"
            components[ov.component] = {
                "name": ov.component,
                "artifactType": ov.artifact_type,
                "artifactRef": ov.artifact_ref,
                "origin": origin,
            }
            applied.append(f"{origin}:{ov.component}")

    return {
        "resolvedAt": datetime.now(UTC).isoformat(),
        "target": {
            "deviceId": device_id,
            "zoneId": device.zone_id,
            "siteId": device.site_id,
        },
        "context": {
            "profile": profile_id,
            "appliedOverrides": applied,
        },
        "components": list(components.values()),
    }
