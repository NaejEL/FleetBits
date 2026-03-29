"""Packages router — Aptly repository and GPG key management."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import subprocess
import tarfile
import io
import uuid
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db import AsyncSessionLocal, get_db
from app.dependencies import require_roles, get_current_user
from app.models import AuditEvent
from app.models.device import Device
from app.services.token import hash_token

router = APIRouter(prefix="/packages", tags=["packages"])
logger = logging.getLogger(__name__)

# Direct Aptly API URL (runs on Docker bridge)
APTLY_API_URL = os.environ.get("APTLY_API_URL", "http://aptly-api:8080").rstrip("/")

PROMOTION_PATHS = {
    "dev": "staging",
    "staging": "prod",
}


async def _call_aptly(method: str, endpoint: str, data: dict | None = None) -> dict | list | None:
    """Call the Aptly REST API; return JSON response or None on error."""
    url = f"{APTLY_API_URL}/api/{endpoint.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if method == "GET":
                resp = await client.get(url)
            elif method == "POST":
                resp = await client.post(url, json=data)
            elif method == "DELETE":
                resp = await client.delete(url)
            else:
                return None

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"status": "ok"}
        else:
            return None
    except Exception:
        return None


async def _stage_package_in_aptly_files(filename: str, content: bytes) -> str:
    """Upload a package file into Aptly /api/files/<dir>; return staging dir name."""
    staging_dir = f"upload-{uuid.uuid4().hex[:12]}"
    url = f"{APTLY_API_URL}/api/files/{staging_dir}"
    files = {"file": (filename, content, "application/vnd.debian.binary-package")}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, files=files)

    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="Failed to stage package in Aptly files API")

    return staging_dir


async def _import_staged_package_to_repo(repo: str, staging_dir: str, force: bool) -> dict[str, Any]:
    """Import files from Aptly staging dir into target repository."""
    url = f"{APTLY_API_URL}/api/repos/{repo}/file/{staging_dir}"
    params = {"forceReplace": "1" if force else "0"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, params=params)

    if resp.status_code not in (200, 201):
        detail = None
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=502, detail=f"Aptly import failed: {detail}")

    try:
        data = resp.json()
    except Exception:
        data = {"status": "ok"}

    return data if isinstance(data, dict) else {"result": data}


async def _run_gpg_command(args: list[str]) -> tuple[bool, str]:
    """Run a GPG command in a thread; return (success, output)."""
    def _run() -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["gpg", "--batch", "--yes"] + args,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    return await run_in_threadpool(_run)


def _extract_repo_token(auth_header: str | None) -> tuple[str | None, str | None]:
    """Return (raw_device_token, hinted_device_id) from Authorization header.

    Supported formats:
    - Bearer <device_token>
    - Basic <base64(device_id:device_token)>
    """
    if not auth_header:
        return None, None

    scheme, _, value = auth_header.partition(" ")
    if not value:
        return None, None

    if scheme.lower() == "bearer":
        return value.strip(), None

    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(value.strip()).decode("utf-8")
            hinted_device_id, raw_token = decoded.split(":", 1)
            return raw_token.strip(), hinted_device_id.strip()
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return None, None

    return None, None


def _parse_repo_name(repo_name: str) -> tuple[str | None, str]:
    """Parse repo name into (distribution|None, channel).

    Supported patterns:
    - <distribution>-<channel>  (e.g. bookworm-dev)
    - <channel>                 (e.g. dev)
    """
    if "-" not in repo_name:
        return None, repo_name
    distribution, channel = repo_name.rsplit("-", 1)
    if not channel:
        return None, repo_name
    return (distribution or None), channel


def _infer_distribution_for_repo(repo_name: str, requested_distribution: str | None = None) -> tuple[str | None, str | None]:
    """Infer distribution/channel from repository name.

    Supports both modern names (<distribution>-<channel>) and legacy names
    (<channel> only). For legacy names we default to bookworm unless a valid
    distribution query parameter is explicitly provided.
    """
    distributions = {"bookworm", "bullseye", "buster", "trixie", "jammy"}
    channels = {"dev", "staging", "prod"}

    dist, channel = _parse_repo_name(repo_name)
    if dist and channel in channels and dist in distributions:
        return dist, channel

    if dist is None and channel in channels:
        fallback_dist = requested_distribution if requested_distribution in distributions else "bookworm"
        return fallback_dist, channel

    return None, None


def _validate_promotion_path(source_repo: str, target_repo: str) -> tuple[str | None, str]:
    """Validate promotion path (dev→staging or staging→prod)."""
    source_parts = _parse_repo_name(source_repo)
    target_parts = _parse_repo_name(target_repo)

    source_dist, source_channel = source_parts
    target_dist, target_channel = target_parts

    if source_dist and target_dist and source_dist != target_dist:
        raise HTTPException(
            status_code=400,
            detail="Promotion must stay within the same distribution",
        )

    expected_target = PROMOTION_PATHS.get(source_channel)
    if expected_target != target_channel:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid promotion path: {source_channel}→{target_channel}. "
                "Allowed: dev→staging, staging→prod"
            ),
        )

    return source_dist, source_channel


async def _get_repo_package_details(repo_name: str) -> list[dict[str, Any]]:
    """Return package details from Aptly for a repository."""
    packages = await _call_aptly("GET", f"repos/{repo_name}/packages?format=details")
    if packages is None:
        raise HTTPException(status_code=503, detail="Aptly API unavailable")
    if not isinstance(packages, list):
        raise HTTPException(status_code=500, detail="Unexpected Aptly response for packages")
    return packages


async def _build_promotion_plan(source_repo: str, target_repo: str) -> dict[str, Any]:
    """Build package diff plan from source to target repository."""
    _validate_promotion_path(source_repo, target_repo)

    source_packages = await _get_repo_package_details(source_repo)
    target_packages = await _get_repo_package_details(target_repo)

    target_index: dict[tuple[str, str], str] = {}
    for p in target_packages:
        package = p.get("Package", p.get("package", ""))
        arch = p.get("Architecture", p.get("architecture", ""))
        version = p.get("Version", p.get("version", ""))
        if package and arch:
            target_index[(package, arch)] = version

    to_add: list[dict[str, str]] = []
    to_update: list[dict[str, str]] = []
    unchanged: list[dict[str, str]] = []

    for p in source_packages:
        package = p.get("Package", p.get("package", ""))
        arch = p.get("Architecture", p.get("architecture", ""))
        version = p.get("Version", p.get("version", ""))
        if not package or not arch:
            continue

        key = (package, arch)
        target_version = target_index.get(key)

        if target_version is None:
            to_add.append({"package": package, "architecture": arch, "source_version": version})
        elif target_version != version:
            to_update.append(
                {
                    "package": package,
                    "architecture": arch,
                    "source_version": version,
                    "target_version": target_version,
                }
            )
        else:
            unchanged.append({"package": package, "architecture": arch, "version": version})

    return {
        "source_repo": source_repo,
        "target_repo": target_repo,
        "summary": {
            "source_total": len(source_packages),
            "target_total": len(target_packages),
            "to_add": len(to_add),
            "to_update": len(to_update),
            "unchanged": len(unchanged),
        },
        "diff": {
            "to_add": sorted(to_add, key=lambda x: (x["package"], x["architecture"])),
            "to_update": sorted(to_update, key=lambda x: (x["package"], x["architecture"])),
            "unchanged": sorted(unchanged, key=lambda x: (x["package"], x["architecture"])),
        },
    }


async def _safe_audit_log(
    *,
    actor: str,
    actor_role: str | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Write an audit event without breaking the caller on audit failures."""
    target: dict[str, Any] = {"type": target_type}
    if target_id:
        target["id"] = target_id

    event = AuditEvent(
        action=action,
        actor=actor,
        actor_role=actor_role,
        target=target,
        payload=details,
        ip_address=ip_address,
    )

    try:
        async with AsyncSessionLocal() as session:
            session.add(event)
            await session.commit()
    except Exception:
        logger.exception("Failed to persist audit event", extra={"action": action})


# ─── GPG Key Management (4.1) ───────────────────────────────────────────────


@router.get("/gpg-keys")
async def list_gpg_keys(_: tuple = Depends(require_roles("admin", "operator"))):
    """List all GPG keys imported in the Aptly GPG keyring."""
    try:
        result = await run_in_threadpool(
            lambda: subprocess.run(
                ["gpg", "--list-keys", "--with-colons"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail="Failed to list GPG keys")

        # Parse colons format: uid:u:::::<timestamp>:::<name>:
        keys = []
        for line in result.stdout.split("\n"):
            if line.startswith("pub:"):
                parts = line.split(":")
                if len(parts) >= 5:
                    key_id = parts[4][-16:] if len(parts) > 4 else "unknown"
                    keys.append(
                        {
                            "key_id": key_id,
                            "created": parts[5] if len(parts) > 5 else None,
                            "algorithm": parts[3] if len(parts) > 3 else "unknown",
                        }
                    )
            elif line.startswith("uid:"):
                parts = line.split(":")
                if keys and len(parts) >= 10:
                    keys[-1]["uid"] = parts[9] if len(parts) > 9 else "unknown"

        return {"keys": keys}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GPG error: {e}")


@router.post("/gpg-keys/generate")
async def generate_gpg_key(
    payload: dict[str, Any],
    request: Request,
    user: tuple = Depends(get_current_user),
    _: tuple = Depends(require_roles("admin")),
):
    """Generate a new GPG key for Aptly package signing."""
    name = payload.get("name", "")
    email = payload.get("email", "")
    key_type = payload.get("key_type", "rsa4096")

    if not name or not email:
        raise HTTPException(status_code=400, detail="name and email required")

    # Generate key batch config
    batch_config = f"""
Name-Real: {name}
Name-Email: {email}
Key-Type: {key_type}
Expire-Date: 0
%no-ask-passphrase
%done
"""

    try:
        result = await run_in_threadpool(
            lambda: subprocess.run(
                ["gpg", "--batch", "--generate-key"],
                input=batch_config,
                capture_output=True,
                text=True,
                timeout=60,
            )
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"GPG generation failed: {result.stderr}")

        # Extract key ID from output
        output = result.stdout + result.stderr
        key_id = None
        for line in output.split("\n"):
            if "key " in line.lower() and ("created" in line.lower() or "generated" in line.lower()):
                # Try to extract key ID (last 16 hex chars in the line)
                for word in line.split():
                    if len(word) == 16 and all(c in "0123456789ABCDEF" for c in word.upper()):
                        key_id = word.upper()
                        break

        # Audit log
        await _safe_audit_log(
            actor=user.sub,
            actor_role=user.role,
            action="PACKAGE_GPG_KEY_GENERATE",
            target_type="gpg_key",
            target_id=key_id or "pending",
            details={"name": name, "email": email, "key_type": key_type},
            ip_address=request.client.host if request.client else None,
        )

        return {
            "status": "generated",
            "message": "GPG key generation started — may take a few seconds",
            "key_id": key_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GPG error: {e}")


@router.post("/gpg-keys/import")
async def import_gpg_key(
    payload: dict[str, Any],
    request: Request,
    user: tuple = Depends(get_current_user),
    _: tuple = Depends(require_roles("admin")),
):
    """Import an existing GPG public key (armored ASCII format)."""
    armored_key = payload.get("armored_key", "")

    if not armored_key:
        raise HTTPException(status_code=400, detail="armored_key required")

    if not armored_key.startswith("-----BEGIN PGP"):
        raise HTTPException(status_code=400, detail="Invalid PGP key format")

    try:
        result = await run_in_threadpool(
            lambda: subprocess.run(
                ["gpg", "--batch", "--import"],
                input=armored_key,
                capture_output=True,
                text=True,
                timeout=10,
            )
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"GPG import failed: {result.stderr}")

        # Audit log
        await _safe_audit_log(
            actor=user.sub,
            actor_role=user.role,
            action="PACKAGE_GPG_KEY_IMPORT",
            target_type="gpg_key",
            details={"key_sample": armored_key[:50] + "..."},
            ip_address=request.client.host if request.client else None,
        )

        return {"status": "imported", "message": "GPG key imported successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GPG error: {e}")


@router.delete("/gpg-keys/{key_id}")
async def delete_gpg_key(
    key_id: str,
    request: Request,
    user: tuple = Depends(get_current_user),
    _: tuple = Depends(require_roles("admin")),
):
    """Delete a GPG key from the keyring."""
    # Validate key_id format (16 hex chars)
    if not (len(key_id) == 16 and all(c in "0123456789ABCDEFabcdef" for c in key_id)):
        raise HTTPException(status_code=400, detail="Invalid key ID format")

    try:
        result = await run_in_threadpool(
            lambda: subprocess.run(
                ["gpg", "--batch", "--delete-keys", key_id],
                capture_output=True,
                text=True,
                timeout=10,
            )
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"GPG deletion failed: {result.stderr}")

        # Audit log
        await _safe_audit_log(
            actor=user.sub,
            actor_role=user.role,
            action="PACKAGE_GPG_KEY_DELETE",
            target_type="gpg_key",
            target_id=key_id,
            ip_address=request.client.host if request.client else None,
        )

        return {"status": "deleted", "message": f"GPG key {key_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GPG error: {e}")


# ─── Aptly Repository Listing (shared by multiple phases) ──────────────────


@router.get("/repos")
async def list_repos(_: tuple = Depends(require_roles("viewer", "technician", "operator", "admin"))):
    """List all Aptly repositories."""
    repos = await _call_aptly("GET", "repos")
    if repos is None:
        raise HTTPException(status_code=503, detail="Aptly API unavailable")
    return {"repos": repos}


@router.get("/repos/{repo_name}/packages")
async def list_packages(
    repo_name: str,
    _: tuple = Depends(require_roles("viewer", "technician", "operator", "admin")),
):
    """List packages in a specific repository."""
    packages = await _call_aptly("GET", f"repos/{repo_name}/packages?format=details")
    if packages is None:
        raise HTTPException(status_code=503, detail="Aptly API unavailable")
    return {"packages": packages}


@router.get("/publish")
async def list_publish(_: tuple = Depends(require_roles("viewer", "technician", "operator", "admin"))):
    """List all published endpoints."""
    endpoints = await _call_aptly("GET", "publish")
    if endpoints is None:
        raise HTTPException(status_code=503, detail="Aptly API unavailable")
    return {"endpoints": endpoints}


@router.get("/repo-authorized-keys")
async def list_repo_authorized_keys(
    _: tuple = Depends(require_roles("operator", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return public keys of devices authorized for repository key-based workflows."""
    result = await db.execute(
        select(
            Device.device_id,
            Device.site_id,
            Device.repo_public_key,
            Device.repo_key_fingerprint,
            Device.repo_key_updated_at,
        )
        .where(Device.repo_public_key.is_not(None))
        .order_by(Device.site_id, Device.device_id)
    )

    rows = result.all()
    keys = [
        {
            "device_id": row.device_id,
            "site_id": row.site_id,
            "public_key": row.repo_public_key,
            "key_fingerprint": row.repo_key_fingerprint,
            "updated_at": row.repo_key_updated_at,
        }
        for row in rows
    ]

    return {
        "count": len(keys),
        "keys": keys,
        "authorized_keys": "\n".join(k["public_key"] for k in keys),
    }


@router.get("/repo/authorize")
async def authorize_repo_download(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Forward-auth endpoint used by Caddy before serving Aptly package paths.

    Access is granted only when:
    - a valid device token is presented (Bearer or Basic password), and
    - the device has a registered repository public key.
    """
    auth_header = request.headers.get("Authorization")
    raw_token, hinted_device_id = _extract_repo_token(auth_header)

    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid repository credentials",
            headers={"WWW-Authenticate": "Basic realm=FleetBits repo"},
        )

    # Accept only the dedicated repo token (not the fleet bearer token) so that
    # APT credentials cannot be used to call Fleet API endpoints.
    result = await db.execute(
        select(Device).where(Device.repo_token_hash == hash_token(raw_token))
    )
    device = result.scalar_one_or_none()

    if device is None:
        raise HTTPException(status_code=401, detail="Invalid repository credentials")

    if hinted_device_id and hinted_device_id != device.device_id:
        raise HTTPException(status_code=403, detail="Repository credential/device mismatch")

    if not device.repo_public_key:
        raise HTTPException(status_code=403, detail="Device repository key not registered")

    return {
        "authorized": True,
        "device_id": device.device_id,
        "site_id": device.site_id,
    }


# ─── Multi-Distribution Support (4.2–4.3) ─────────────────────────────────


@router.get("/distributions")
async def list_distributions(_: tuple = Depends(require_roles("viewer", "technician", "operator", "admin"))):
    """List available Debian distributions (bookworm, bullseye, buster, trixie, jammy)."""
    return {
        "distributions": [
            {"codename": "bookworm", "name": "Debian 12 Bookworm"},
            {"codename": "bullseye", "name": "Debian 11 Bullseye"},
            {"codename": "buster", "name": "Debian 10 Buster"},
            {"codename": "trixie", "name": "Debian 13 Trixie"},
            {"codename": "jammy", "name": "Ubuntu 22.04 Jammy"},
        ]
    }


@router.get("/architectures")
async def list_architectures(_: tuple = Depends(require_roles("viewer", "technician", "operator", "admin"))):
    """List supported architectures for package publishing."""
    return {
        "architectures": [
            {"arch": "amd64", "name": "x86_64 / AMD64"},
            {"arch": "arm64", "name": "ARM 64-bit (ARMv8)"},
            {"arch": "armhf", "name": "ARM 32-bit (ARMv6/v7)"},
        ]
    }


@router.get("/repos-by-distribution")
async def list_repos_by_distribution(
    distribution: str | None = None,
    _: tuple = Depends(require_roles("viewer", "technician", "operator", "admin")),
):
    """List repositories organized by distribution and channel (dev/staging/prod)."""
    repos = await _call_aptly("GET", "repos")
    if repos is None:
        raise HTTPException(status_code=503, detail="Aptly API unavailable")

    # Organize by distribution
    by_dist: dict[str, dict[str, list]] = {}
    distributions = ["bookworm", "bullseye", "buster", "trixie", "jammy"]

    for dist in distributions:
        by_dist[dist] = {"dev": [], "staging": [], "prod": []}

    async def _arch_counts_for_repo(repo_name: str) -> dict[str, int]:
        counts = {"amd64": 0, "arm64": 0, "armhf": 0, "other": 0}
        pkgs = await _call_aptly("GET", f"repos/{repo_name}/packages?format=details")
        if not isinstance(pkgs, list):
            return counts
        for pkg in pkgs:
            arch = (pkg.get("Architecture") or pkg.get("architecture") or "").strip().lower()
            if arch in counts:
                counts[arch] += 1
            elif arch:
                counts["other"] += 1
        return counts

    # Filter repositories by distribution and channel
    for r in repos:
        repo_name = r.get("Name", r.get("name", ""))
        dist, channel = _infer_distribution_for_repo(repo_name, requested_distribution=distribution)
        if dist and channel:
            repo_with_counts = dict(r)
            repo_with_counts["arch_counts"] = await _arch_counts_for_repo(repo_name)
            by_dist[dist][channel].append(repo_with_counts)

    # Filter by distribution if specified
    if distribution and distribution in by_dist:
        return {"distribution": distribution, "repos": by_dist[distribution]}

    return {"repos_by_distribution": by_dist}


# ─── Deb File Upload and Metadata Extraction ──────────────────────────────


def _extract_deb_metadata(deb_data: bytes) -> dict[str, str]:
    """Extract package metadata from a .deb file.
    
    A .deb file is an ar archive containing:
    - debian-binary (format version)
    - control.tar.gz (contains control files including control script)
    - data.tar.* (actual package contents)
    
    This function extracts the control.tar.gz, decompresses it, and reads
    the 'control' file to extract metadata like Package, Version, Architecture.
    """
    try:
        # Read ar archive header and members
        if not deb_data.startswith(b"!<arch>\n"):
            raise ValueError("Invalid deb file: not an ar archive")
        
        offset = 8  # Skip ar magic
        metadata = {}
        
        while offset < len(deb_data):
            # ar member header is 60 bytes
            if offset + 60 > len(deb_data):
                break
            
            header = deb_data[offset:offset + 60]
            member_name = header[0:16].decode("utf-8", errors="ignore").rstrip()
            size_str = header[48:58].rstrip()
            
            try:
                member_size = int(size_str)
            except ValueError:
                break
            
            offset += 60
            member_data = deb_data[offset:offset + member_size]
            offset += member_size
            
            # Align to even boundary
            if offset % 2:
                offset += 1
            
            # Look for control.tar.gz
            if "control.tar" in member_name:
                # Debian control archive may be .gz, .xz, .bz2, or plain .tar.
                # Use tarfile auto-detection instead of forcing gzip.
                tar_io = io.BytesIO(member_data)
                try:
                    tar = tarfile.open(fileobj=tar_io, mode="r:*")
                except tarfile.ReadError:
                    if member_name.endswith(".zst"):
                        raise ValueError(
                            "Unsupported control archive compression: .zst"
                        )
                    raise ValueError(
                        f"Unsupported control archive format in member '{member_name}'"
                    )

                with tar:
                    # Find the control file
                    for member in tar.getmembers():
                        if member.name == "./control" or member.name == "control":
                            control_file = tar.extractfile(member)
                            if control_file:
                                control_text = control_file.read().decode('utf-8', errors='ignore')
                                
                                # Parse control file (RFC 822 format)
                                for line in control_text.split('\n'):
                                    if ':' in line:
                                        key, value = line.split(':', 1)
                                        metadata[key.strip()] = value.strip()
                            break
                break
        
        return metadata
    except Exception as e:
        return {"error": f"Failed to extract metadata: {str(e)}"}


@router.post("/upload")
async def upload_package(
    request: Request,
    file: UploadFile = File(...),
    repo: str | None = None,
    distribution: str | None = None,
    architecture: str | None = None,
    is_overwrite: bool = False,
    user: tuple = Depends(get_current_user),
    _: tuple = Depends(require_roles("operator", "admin")),
):
    """Upload a .deb package file and extract its metadata.
    
    This endpoint:
    1. Receives a .deb file upload
    2. Extracts metadata from the control section
    3. Returns metadata for validation/review
    4. (In a later step) adds to Aptly repository
    
    Args (from request body or query):
        file: The .deb package file
        repo: Target repository name (e.g., "bookworm-dev")
        distribution: Debian distribution codename (e.g., "bookworm")
        architecture: Package architecture (e.g., "amd64")
        is_overwrite: Allow overwriting existing package version
    
    Returns:
        {
            "filename": "fleet-agent_1.0.0_amd64.deb",
            "size": 1024000,
            "metadata": {
                "Package": "fleet-agent",
                "Version": "1.0.0",
                "Architecture": "amd64",
                "Maintainer": "FleetBits Ops",
                ...
            },
            "validation": {
                "is_valid": true,
                "warnings": []
            }
        }
    """
    try:
        # Validate file extension (case-insensitive, e.g. .deb / .DEB)
        filename = (file.filename or "").strip()
        if not filename or not filename.lower().endswith('.deb'):
            raise HTTPException(status_code=400, detail="File must be a .deb package")
        
        # Read file content
        content = await file.read()
        file_size = len(content)
        
        # Validate minimum size (deb file should be at least several KB)
        if file_size < 1024:
            raise HTTPException(status_code=400, detail="File is too small to be a valid .deb package")
        
        # Extract metadata
        metadata = _extract_deb_metadata(content)
        
        if "error" in metadata:
            raise HTTPException(status_code=400, detail=metadata["error"])
        
        # Extract key fields for validation
        package_name = metadata.get("Package", "UNKNOWN")
        version = metadata.get("Version", "UNKNOWN")
        arch = metadata.get("Architecture", "UNKNOWN")
        
        # Validate metadata
        warnings = []
        if not package_name or package_name == "UNKNOWN":
            raise HTTPException(status_code=400, detail="Package name not found in control metadata")
        
        if not version or version == "UNKNOWN":
            warnings.append("Version not found in metadata")
        
        # Check for suspicious fields
        if not metadata.get("Maintainer"):
            warnings.append("No Maintainer field in control file")

        # Stage file in Aptly files API for optional later import.
        staging_dir = await _stage_package_in_aptly_files(filename=filename, content=content)
        package_reference = f"{staging_dir}:{filename}"
        
        # Audit log
        await _safe_audit_log(
            actor=user.sub,
            actor_role=user.role,
            action="PACKAGE_UPLOAD",
            target_type="package",
            target_id=f"{package_name}_{version}",
            details={
                "filename": filename,
                "size": file_size,
                "package": package_name,
                "version": version,
                "architecture": arch,
                "repo": repo,
                "distribution": distribution,
                "package_reference": package_reference,
            },
            ip_address=request.client.host if request.client else None,
        )
        
        return {
            "filename": filename,
            "package_reference": package_reference,
            "size": file_size,
            "metadata": metadata,
            "validation": {
                "is_valid": len(warnings) == 0,
                "warnings": warnings,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload error: {str(e)}")


@router.post("/add-to-repo")
async def add_package_to_repo(
    payload: dict[str, Any],
    request: Request,
    user: tuple = Depends(get_current_user),
    _: tuple = Depends(require_roles("operator", "admin")),
):
    """Add a previously uploaded/scanned package to an Aptly repository.
    
    This is called after the UI has validated the package metadata.
    
    Args:
        payload: {
            "package_reference": "fleet-agent_1.0.0_amd64.deb",  # or internal reference
            "repo": "bookworm-dev",
            "force": false  # allow overwriting existing version
        }
    
    Returns:
        {
            "status": "added",
            "repo": "bookworm-dev",
            "package": "fleet-agent_1.0.0_amd64",
            "message": "Package added successfully"
        }
    """
    try:
        package_ref = payload.get("package_reference", "")
        repo = payload.get("repo", "")
        force = payload.get("force", False)
        
        if not package_ref or not repo:
            raise HTTPException(status_code=400, detail="package_reference and repo required")

        # Expected reference format from upload step: <staging_dir>:<filename>
        if ":" not in package_ref:
            raise HTTPException(
                status_code=400,
                detail="Invalid package_reference format. Re-upload package before importing.",
            )

        staging_dir, staged_filename = package_ref.split(":", 1)
        if not staging_dir or not staged_filename:
            raise HTTPException(status_code=400, detail="Invalid package_reference")

        import_result = await _import_staged_package_to_repo(repo=repo, staging_dir=staging_dir, force=bool(force))
        
        # Audit log
        await _safe_audit_log(
            actor=user.sub,
            actor_role=user.role,
            action="PACKAGE_ADD_TO_REPO",
            target_type="package",
            target_id=package_ref,
            details={
                "repo": repo,
                "force": force,
                "staging_dir": staging_dir,
            },
            ip_address=request.client.host if request.client else None,
        )
        
        return {
            "status": "added",
            "repo": repo,
            "package": package_ref,
            "message": "Package added to repository",
            "aptly": import_result,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Add to repo error: {str(e)}")


# ─── Package Promotion Workflow (4.5) ──────────────────────────────────────


@router.get("/promotions/plan")
async def get_promotion_plan(
    source_repo: str,
    target_repo: str,
    _: tuple = Depends(require_roles("viewer", "technician", "operator", "admin")),
):
    """Compute promotion diff between source and target repository.

    Supports strict paths only:
    - <distribution>-dev → <distribution>-staging
    - <distribution>-staging → <distribution>-prod
    """
    return await _build_promotion_plan(source_repo=source_repo, target_repo=target_repo)


@router.post("/promotions/execute")
async def execute_promotion(
    payload: dict[str, Any],
    request: Request,
    user: tuple = Depends(get_current_user),
    _: tuple = Depends(require_roles("operator", "admin")),
):
    """Execute a repository promotion by copying package refs source→target."""
    source_repo = payload.get("source_repo", "").strip()
    target_repo = payload.get("target_repo", "").strip()
    force_replace = bool(payload.get("force_replace", False))

    if not source_repo or not target_repo:
        raise HTTPException(status_code=400, detail="source_repo and target_repo are required")

    plan = await _build_promotion_plan(source_repo=source_repo, target_repo=target_repo)

    if plan["summary"]["to_add"] == 0 and plan["summary"]["to_update"] == 0:
        return {
            "status": "noop",
            "message": "Target repository is already up to date",
            "plan": plan,
        }

    refs_resp = await _call_aptly("GET", f"repos/{source_repo}/packages")
    if refs_resp is None or not isinstance(refs_resp, list):
        raise HTTPException(status_code=503, detail="Failed to fetch package references from Aptly")

    if not refs_resp:
        raise HTTPException(status_code=400, detail="Source repository has no packages to promote")

    add_payloads = [
        {"PackageRefs": refs_resp, "ForceReplace": force_replace},
        {"PackageRefs": refs_resp},
    ]

    add_result: dict | list | None = None
    for body in add_payloads:
        add_result = await _call_aptly("POST", f"repos/{target_repo}/packages", body)
        if add_result is not None:
            break

    if add_result is None:
        raise HTTPException(
            status_code=502,
            detail="Aptly rejected promotion request while adding packages to target repository",
        )

    await _safe_audit_log(
        actor=user.sub,
        actor_role=user.role,
        action="PACKAGE_PROMOTION_EXECUTE",
        target_type="repository",
        target_id=target_repo,
        details={
            "source_repo": source_repo,
            "target_repo": target_repo,
            "force_replace": force_replace,
            "summary": plan["summary"],
        },
        ip_address=request.client.host if request.client else None,
    )

    return {
        "status": "promoted",
        "message": f"Promotion completed: {source_repo} → {target_repo}",
        "plan": plan,
        "aptly": add_result,
    }

