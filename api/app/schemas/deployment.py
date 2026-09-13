import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


_VALID_ARTIFACT_TYPES = ("deb", "git")
_VALID_ROLLOUT_MODES = ("ring-0", "ring-1", "ring-2", "hotfix", "rollback")
_VALID_RECON_POLICIES = ("promote", "revert", "decide-later")

# Permit safe package version / git ref chars; rejects shell metacharacters
_ARTIFACT_REF_RE = re.compile(r"^[a-zA-Z0-9\-_.+~:/@]{1,256}$")
# Safe Ansible inventory pattern: hostname-like characters
_SCOPE_ID_RE = re.compile(r"^[a-z0-9\-_.]{1,128}$")


class DeploymentCreate(BaseModel):
    artifact_type: str
    artifact_ref: str
    rollout_mode: str
    # See §7.2 — {"scope": "ring", "ring": 0} | {"scope": "site", "siteId": "paris"} | etc.
    target_scope: dict
    scheduled_at: datetime | None = None
    change_id: str | None = None
    requested_by: str

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, v: str) -> str:
        if v not in _VALID_ARTIFACT_TYPES:
            raise ValueError(f"artifact_type must be one of {_VALID_ARTIFACT_TYPES}")
        return v

    @field_validator("artifact_ref")
    @classmethod
    def validate_artifact_ref(cls, v: str) -> str:
        if not _ARTIFACT_REF_RE.match(v):
            raise ValueError("artifact_ref contains unsafe characters")
        return v

    @field_validator("rollout_mode")
    @classmethod
    def validate_rollout_mode(cls, v: str) -> str:
        if v not in _VALID_ROLLOUT_MODES:
            raise ValueError(f"rollout_mode must be one of {_VALID_ROLLOUT_MODES}")
        return v

    @field_validator("target_scope")
    @classmethod
    def validate_target_scope(cls, v: dict) -> dict:
        for key in ("deviceId", "zoneId", "siteId"):
            val = v.get(key)
            if val is not None and not _SCOPE_ID_RE.match(val):
                raise ValueError(f"target_scope.{key} contains unsafe characters")
        return v


class DeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deployment_id: uuid.UUID
    artifact_type: str
    artifact_ref: str
    resolved_commit: str | None = None
    rollout_mode: str
    target_scope: dict
    status: str
    scheduled_at: datetime | None = None
    change_id: str | None = None
    requested_by: str
    semaphore_job_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class TriggerRequest(BaseModel):
    """Body for POST /deployments/{id}/promote — optional override of scheduled_at."""

    scheduled_at: datetime | None = None


class HotfixCreate(BaseModel):
    hotfix_id: str  # operator-assigned, e.g. "HF-2026-00042"
    target_scope: dict
    artifact_type: str
    artifact_ref: str
    reason: str
    requested_by: str
    change_id: str | None = None
    expires_at: datetime | None = None
    recon_policy: str = "decide-later"

    @field_validator("hotfix_id")
    @classmethod
    def validate_hotfix_id(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Z0-9\-]{1,64}", v):
            raise ValueError("hotfix_id must be uppercase alphanumeric and hyphens only, max 64 chars")
        return v

    @field_validator("artifact_ref")
    @classmethod
    def validate_artifact_ref(cls, v: str) -> str:
        if not _ARTIFACT_REF_RE.match(v):
            raise ValueError("artifact_ref contains unsafe characters")
        return v

    @field_validator("target_scope")
    @classmethod
    def validate_target_scope(cls, v: dict) -> dict:
        for key in ("deviceId", "zoneId", "siteId"):
            val = v.get(key)
            if val is not None and not _SCOPE_ID_RE.match(val):
                raise ValueError(f"target_scope.{key} contains unsafe characters")
        return v

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, v: str) -> str:
        if v not in _VALID_ARTIFACT_TYPES:
            raise ValueError(f"artifact_type must be one of {_VALID_ARTIFACT_TYPES}")
        return v

    @field_validator("recon_policy")
    @classmethod
    def validate_recon_policy(cls, v: str) -> str:
        if v not in _VALID_RECON_POLICIES:
            raise ValueError(f"recon_policy must be one of {_VALID_RECON_POLICIES}")
        return v


class HotfixRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hotfix_id: str
    target_scope: dict
    artifact_type: str
    artifact_ref: str
    resolved_commit: str | None = None
    reason: str
    requested_by: str
    change_id: str | None = None
    expires_at: datetime | None = None
    recon_policy: str
    reconciled: bool
    status: str
    semaphore_job_id: str | None = None
    created_at: datetime


class OverrideCreate(BaseModel):
    scope: str  # 'site' | 'zone' | 'device'
    target_id: str
    component: str
    artifact_type: str
    artifact_ref: str
    reason: str
    created_by: str
    expires_at: datetime | None = None

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        if v not in ("site", "zone", "device"):
            raise ValueError("scope must be 'site', 'zone', or 'device'")
        return v

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, v: str) -> str:
        if v not in _VALID_ARTIFACT_TYPES:
            raise ValueError(f"artifact_type must be one of {_VALID_ARTIFACT_TYPES}")
        return v


class OverrideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    override_id: uuid.UUID
    scope: str
    target_id: str
    component: str
    artifact_type: str
    artifact_ref: str
    reason: str
    created_by: str
    created_at: datetime
    expires_at: datetime | None = None
    reconciled: bool
