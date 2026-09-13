"""Canonical contract for ``/etc/fleet/device-identity.conf``.

SOURCE OF TRUTH for the device identity file. Every producer and every consumer
of that file — the provisioning route below, ``FleetBits-agent`` (parser,
container entry point, example file, README) and ``FleetBits-platform``
(Ansible template, diagnostics redaction) — MUST agree with this module.
``tests/test_device_identity_contract.py`` compares the four key sets and fails
on any divergence.

Format (deliberately INERT — never evaluated by a shell interpreter):

* one ``KEY=value`` pair per line, in :data:`FIELDS` order;
* no quoting, no escaping, no variable expansion, no command substitution;
* blank lines and whole-line ``#`` comments are ignored by the parser;
* values are restricted to :data:`VALUE_PATTERN`.

The allowed character set excludes whitespace, quotes, backslash, ``$``,
backtick, ``;``, ``&`` and ``|``. Excluding whitespace and shell metacharacters
keeps the file inert even if a future consumer regressed to evaluating it;
excluding ``|``, ``&`` and ``\\`` additionally keeps the values safe as ``sed``
replacement text in ``generate-config.sh``, which uses ``|`` as its delimiter.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

# Bump when keys are added, removed or given a new meaning.
CONTRACT_VERSION = 1

#: The allowed character class, written once so the two spellings below can
#: never drift apart.
VALUE_CHARACTER_CLASS = r"[A-Za-z0-9._:/@=+,~-]"

#: Canonical POSIX ERE for a contract value. This exact string is duplicated as
#: ``FLEET_IDENTITY_VALUE_PATTERN`` in ``FleetBits-agent`` and compared by
#: ``tests/test_device_identity_contract.py``.
VALUE_PATTERN = rf"^{VALUE_CHARACTER_CLASS}*$"

#: The same expression for Python's engine. ``$`` is NOT the same anchor in the
#: two dialects: POSIX ERE anchors at end of string, while Python's ``$`` also
#: matches just before a final newline. Compiling ``VALUE_PATTERN`` verbatim
#: would therefore accept ``"role\n"`` here and reject it in the agent parser,
#: letting ``render()`` emit a line-split file that the agent refuses at boot.
#: ``\Z`` restores the POSIX meaning, so both validators decide identically.
_VALUE_RE = re.compile(rf"^{VALUE_CHARACTER_CLASS}*\Z")


@dataclass(frozen=True)
class IdentityField:
    """One key of the device identity contract."""

    key: str
    #: Carries a credential: must be redacted from diagnostics bundles and
    #: never logged (GUIDELINES.md §3).
    secret: bool = False
    #: The key is always present, but an empty value is a valid state.
    allow_empty: bool = False
    description: str = ""


FIELDS: tuple[IdentityField, ...] = (
    IdentityField("DEVICE_ID", description="Canonical device hostname (GUIDELINES.md §10)"),
    IdentityField("SITE_ID", description="Site slug — telemetry label 'site'"),
    IdentityField("ZONE_ID", description="Zone slug — telemetry label 'zone'"),
    IdentityField("DEVICE_ROLE", description="Free-text role — telemetry label 'device_role'"),
    IdentityField("PROFILE", allow_empty=True, description="Profile slug — label 'profile'"),
    IdentityField("ENVIRONMENT", description="lab|staging|prod — telemetry label 'environment'"),
    IdentityField("RING", description="Rollout ring 0|1|2 — telemetry label 'ring'"),
    IdentityField("FLEET_API_URL", description="Fleet API base URL, used by heartbeat.sh"),
    IdentityField("FLEET_METRICS_URL", description="Absolute Prometheus remote-write URL"),
    IdentityField("FLEET_LOGS_URL", description="Absolute Loki push URL"),
    IdentityField("FLEET_AGENT_TOKEN", secret=True, description="Per-device fleet API bearer token"),
    IdentityField(
        "REPO_BASIC_TOKEN",
        secret=True,
        allow_empty=True,
        description="APT repository credential; empty when the device is not repo-enrolled",
    ),
    IdentityField(
        "HEADSCALE_PREAUTH_KEY",
        secret=True,
        allow_empty=True,
        description="Headscale pre-auth key; empty means 'skip mesh enrollment'",
    ),
    IdentityField("MQTT_BROKER_HOST", description="MQTT broker hostname"),
    IdentityField("MQTT_BROKER_PORT", description="MQTT broker TCP port"),
    IdentityField(
        "MQTT_USERNAME",
        allow_empty=True,
        description="Per-device MQTT username; empty when MQTT is not used",
    ),
    IdentityField(
        "MQTT_PASSWORD",
        secret=True,
        allow_empty=True,
        description="Per-device MQTT password; empty when MQTT is not used",
    ),
    IdentityField("ENABLE_MQTT_EXPORTER", description="true|false — Alloy MQTT exporter"),
    IdentityField("ENABLE_PROCESS_EXPORTER", description="true|false — Alloy process exporter"),
    IdentityField("SCRAPE_INTERVAL", description="Collector scrape interval, e.g. 30s"),
)

KEYS: tuple[str, ...] = tuple(f.key for f in FIELDS)
KEY_SET: frozenset[str] = frozenset(KEYS)
SECRET_KEYS: frozenset[str] = frozenset(f.key for f in FIELDS if f.secret)
OPTIONAL_KEYS: frozenset[str] = frozenset(f.key for f in FIELDS if f.allow_empty)


class IdentityContractError(ValueError):
    """Raised when a set of values does not satisfy the contract."""


def validate(values: Mapping[str, str]) -> None:
    """Fail closed on any deviation from the contract."""
    provided = set(values)
    missing = KEY_SET - provided
    if missing:
        raise IdentityContractError(f"missing identity keys: {sorted(missing)}")
    unknown = provided - KEY_SET
    if unknown:
        raise IdentityContractError(f"unknown identity keys: {sorted(unknown)}")

    for field in FIELDS:
        value = values[field.key]
        if not isinstance(value, str):
            raise IdentityContractError(f"{field.key}: value must be a string")
        if not _VALUE_RE.match(value):
            raise IdentityContractError(
                f"{field.key}: value contains a character outside {VALUE_PATTERN}"
            )
        if not value and not field.allow_empty:
            raise IdentityContractError(f"{field.key}: value must not be empty")


def render(values: Mapping[str, str]) -> str:
    """Serialise ``values`` as the inert ``KEY=value`` identity file."""
    validate(values)
    return "".join(f"{field.key}={values[field.key]}\n" for field in FIELDS)


def parse(text: str) -> dict[str, str]:
    """Parse an identity file with the same strictness as the agent parser."""
    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise IdentityContractError(f"line {lineno}: expected KEY=value")
        key, _, value = line.partition("=")
        if key not in KEY_SET:
            raise IdentityContractError(f"line {lineno}: key {key!r} is not in the contract")
        if key in values:
            raise IdentityContractError(f"line {lineno}: duplicate key {key!r}")
        values[key] = value
    validate(values)
    return values
