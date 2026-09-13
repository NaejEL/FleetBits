"""Semaphore REST API client — triggers Ansible playbook jobs."""

import json

import httpx

from app.config import settings


class SemaphoreError(RuntimeError):
    pass


async def trigger_job(
    template_id: int,
    limit: str = "",
    extra_vars: dict | None = None,
) -> str:
    """Trigger a Semaphore task template and return the task ID as a string.

    Args:
        template_id: Semaphore template ID (from settings.SEMAPHORE_*_TEMPLATE_ID).
        limit: Ansible inventory host-limit pattern, e.g. "rpi-paris-zone1-01".
        extra_vars: Dict injected as JSON in the Semaphore `environment` field.
    """
    payload: dict = {
        "template_id": template_id,
        "debug": False,
        "dry_run": False,
        "playbook": "",
        "environment": json.dumps(extra_vars) if extra_vars else "",
        "limit": limit,
    }
    url = (
        f"{settings.SEMAPHORE_URL}/api/projects/"
        f"{settings.SEMAPHORE_PROJECT_ID}/tasks"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.SEMAPHORE_API_KEY}"},
        )
    if resp.status_code not in (200, 201):
        raise SemaphoreError(f"Semaphore {resp.status_code}: {resp.text[:300]}")
    return str(resp.json()["id"])


async def get_task_status(task_id: str) -> str:
    """Return Semaphore task status: waiting | running | success | error."""
    url = (
        f"{settings.SEMAPHORE_URL}/api/projects/"
        f"{settings.SEMAPHORE_PROJECT_ID}/tasks/{task_id}"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {settings.SEMAPHORE_API_KEY}"},
        )
    if resp.status_code != 200:
        raise SemaphoreError(f"Semaphore {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("status", "unknown")
