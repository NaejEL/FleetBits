"""Device identity contract — FleetBits-platform side (SPEC-contrat-identite-appareil).

Covers acceptance criteria 5 (automation producer), 7, 15, 16, 17 and 20.

The contract is owned by ``FleetBits-api/app/contracts/device_identity.py``; the
strict parser that consumes it lives in
``FleetBits-agent/usr/lib/fleet-agent/identity-lib.sh``. These tests render the
Ansible template and the container entry point and feed the result to that very
parser, so a divergence in any of the three repositories fails here.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

PLATFORM_REPO = Path(__file__).resolve().parents[1]
WORK_ROOT = PLATFORM_REPO.parent
AGENT_REPO = WORK_ROOT / "FleetBits-agent"

IDENTITY_LIB = AGENT_REPO / "usr" / "lib" / "fleet-agent" / "identity-lib.sh"
CONTAINER_ENTRYPOINT = AGENT_REPO / "container-entrypoint.sh"
TEMPLATE_DIR = PLATFORM_REPO / "ansible" / "roles" / "fleet_agent" / "templates"
TEMPLATE_NAME = "device-identity.conf.j2"
ROLE_TASKS = PLATFORM_REPO / "ansible" / "roles" / "fleet_agent" / "tasks" / "main.yml"
GROUP_VARS = PLATFORM_REPO / "ansible" / "group_vars" / "all" / "vars.yml"
DIAGNOSTICS = PLATFORM_REPO / "ansible" / "playbooks" / "collect_diagnostics.yml"
COMPOSE = PLATFORM_REPO / "docker" / "docker-compose.yml"
FIRSTBOOT = AGENT_REPO / "usr" / "lib" / "fleet-agent" / "firstboot.sh"

# A representative inventory for an edge device, as group_vars + host_vars
# would supply it.
INVENTORY_VARS = {
    "inventory_hostname": "rpi-paris-pharaoh-02",
    "site": "paris",
    "zone": "pharaoh",
    "device_id": "rpi-paris-pharaoh-02",
    "device_role": "rpi-video",
    "profile": "profile_v1",
    "environment": "prod",
    "ring": "2",
    "fleet_api_url": "https://api.fleet.example.com",
    "fleet_metrics_url": "https://metrics.fleet.example.com/api/v1/write",
    "fleet_logs_url": "https://logs.fleet.example.com/loki/api/v1/push",
    "fleet_agent_token": "agent-token-value",
    "repo_basic_token": "repo-token-value",
    "headscale_preauth_key": "preauth-key-value",
    "mqtt_broker_host": "localhost",
    "mqtt_broker_port": 1883,
    "mqtt_username": "device_rpi-paris-pharaoh-02",
    "mqtt_password": "mqtt-password-value",
    "enable_mqtt_exporter": True,
    "enable_process_exporter": False,
    "scrape_interval": "30s",
}


def read(path: Path) -> str:
    assert path.is_file(), (
        f"{path} is missing. The device identity contract spans three repositories; "
        f"they must all be checked out under {WORK_ROOT}."
    )
    return path.read_text(encoding="utf-8")


def render_template(**overrides: object) -> str:
    """Render device-identity.conf.j2 with Ansible's template settings."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=False,
        keep_trailing_newline=True,
        autoescape=False,  # a shell-style config file, never HTML
    )
    variables = dict(INVENTORY_VARS)
    variables.update(overrides)
    return env.get_template(TEMPLATE_NAME).render(**variables) + "\n"


def contract_keys() -> list[str]:
    """The canonical key list, read from the agent-side parser."""
    source = read(IDENTITY_LIB)
    match = re.search(r"^FLEET_IDENTITY_KEYS=\((.*?)\n\)", source, re.MULTILINE | re.DOTALL)
    assert match, "FLEET_IDENTITY_KEYS not found in identity-lib.sh"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def secret_keys() -> list[str]:
    source = read(IDENTITY_LIB)
    match = re.search(
        r"^FLEET_IDENTITY_SECRET_KEYS=\((.*?)\n\)", source, re.MULTILINE | re.DOTALL
    )
    assert match, "FLEET_IDENTITY_SECRET_KEYS not found in identity-lib.sh"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def keys_of(rendered: str) -> list[str]:
    return [
        line.split("=", 1)[0]
        for line in rendered.splitlines()
        if re.match(r"^[A-Z][A-Z0-9_]*=", line)
    ]


def run_agent_parser(identity_file: Path) -> subprocess.CompletedProcess:
    """Feed a file to the real FleetBits-agent parser."""
    bash = shutil.which("bash")
    assert bash, "bash is required to exercise the FleetBits-agent parser"
    script = (
        f'set -euo pipefail\n. "{IDENTITY_LIB}"\n'
        f'fleet_identity_parse "{identity_file}"\n'
        'printf "%s\\n" "${FLEET_ID_DEVICE_ID}"\n'
    )
    return subprocess.run(
        [bash, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )


# ── Criteria 5 and 15 — the Ansible producer matches the contract ───────────


def test_template_renders_exactly_the_contract_keys_in_order():
    assert keys_of(render_template()) == contract_keys()


def test_rendered_template_is_accepted_by_the_agent_parser(tmp_path):
    identity_file = tmp_path / "device-identity.conf"
    identity_file.write_text(render_template(), encoding="utf-8")
    proc = run_agent_parser(identity_file)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "rpi-paris-pharaoh-02"


def test_rendered_template_is_accepted_with_only_the_mandatory_inventory_vars(tmp_path):
    """Everything the template defaults must still produce a valid file."""
    minimal = {
        key: INVENTORY_VARS[key]
        for key in (
            "inventory_hostname",
            "site",
            "zone",
            "device_role",
            "fleet_api_url",
            "fleet_metrics_url",
            "fleet_logs_url",
            "fleet_agent_token",
        )
    }
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    rendered = env.get_template(TEMPLATE_NAME).render(**minimal) + "\n"
    identity_file = tmp_path / "device-identity.conf"
    identity_file.write_text(rendered, encoding="utf-8")
    proc = run_agent_parser(identity_file)
    assert proc.returncode == 0, proc.stderr


# ── Criterion 7 — the keys firstboot.sh treats as fatal are provided ────────


def test_template_provides_every_key_firstboot_treats_as_fatal():
    firstboot = read(FIRSTBOOT)
    fatal = set(re.findall(r"fleet_identity_require\s+([A-Z_]+)\s*\\?\n\s*\|\|\s*fail", firstboot))
    assert fatal, "firstboot.sh declares no fatal identity requirement"
    rendered = set(keys_of(render_template()))
    assert fatal <= rendered, sorted(fatal - rendered)


def test_neither_side_references_a_key_the_other_cannot_provide():
    rendered = set(keys_of(render_template()))
    referenced = set(re.findall(r"\$\{FLEET_ID_([A-Z_]+)[:}]", read(FIRSTBOOT)))
    assert referenced <= rendered, sorted(referenced - rendered)


# ── Criterion 16 — one file mode across every producer ─────────────────────


def test_ansible_deploys_the_identity_file_with_mode_0600():
    tasks = read(ROLE_TASKS)
    block = tasks.split("- name: Deploy device-identity.conf", 1)[1]
    mode = re.search(r'mode:\s*"(\d+)"', block)
    assert mode, "no mode on the device-identity.conf template task"
    assert mode.group(1).lstrip("0") == "600"
    assert 'chmod 600 "${IDENTITY_FILE}"' in read(FIRSTBOOT)


# ── Criterion 17 — diagnostics redact every declared secret ─────────────────


def test_group_vars_list_matches_the_contract_secret_keys():
    block = read(GROUP_VARS).split("fleet_identity_secret_keys:", 1)[1]
    declared = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            declared.append(stripped[2:].strip())
        elif stripped and not stripped.startswith("#"):
            break
    assert set(declared) == set(secret_keys())


def test_diagnostics_redaction_removes_every_secret_value(tmp_path):
    """Apply the playbook's redaction command to a complete identity file."""
    task_block = read(DIAGNOSTICS).split("Collect device identity", 1)[1]
    assert "fleet_identity_secret_keys" in task_block, (
        "the redaction task no longer derives its key list from the contract"
    )

    identity_file = tmp_path / "device-identity.conf"
    identity_file.write_text(render_template(), encoding="utf-8")

    # Same command the playbook runs, with the Ansible variable resolved.
    pattern = "^(" + "|".join(secret_keys()) + ")="
    proc = subprocess.run(
        ["grep", "-v", "-E", pattern, str(identity_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    redacted = proc.stdout

    for key in secret_keys():
        assert f"{key}=" not in redacted, f"{key} survived redaction"
    for secret_value in (
        INVENTORY_VARS["fleet_agent_token"],
        INVENTORY_VARS["repo_basic_token"],
        INVENTORY_VARS["headscale_preauth_key"],
        INVENTORY_VARS["mqtt_password"],
    ):
        assert secret_value not in redacted, f"{secret_value!r} survived redaction"

    # Non-secret keys must still be there — the bundle has to stay useful.
    assert "DEVICE_ID=" in redacted
    assert "FLEET_METRICS_URL=" in redacted


# ── Criterion 20 — the vps-device service still produces a valid file ───────


def compose_service_environment(service: str) -> dict[str, str]:
    """Read the literal environment mapping of one compose service."""
    text = read(COMPOSE)
    block = text.split(f"\n  {service}:\n", 1)[1]
    env_block = block.split("    environment:\n", 1)[1]
    result: dict[str, str] = {}
    for line in env_block.splitlines():
        if not line.startswith("      ") or line.strip().startswith("#"):
            if line.strip() and not line.startswith("      "):
                break
            continue
        key, _, value = line.strip().partition(":")
        result[key.strip()] = value.strip().strip('"')
    return result


def resolve(value: str, environment: dict[str, str]) -> str:
    """Resolve ${VAR}, ${VAR:-default} and ${VAR:?msg} the way compose does."""

    def substitute(match: re.Match) -> str:
        name = match.group("name")
        default = match.group("default")
        if name in environment and environment[name]:
            return environment[name]
        return default or ""

    return re.sub(
        r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::[-?](?P<default>[^}]*))?\}",
        substitute,
        value,
    )


def test_vps_device_environment_produces_a_parseable_identity_file(tmp_path):
    service_env = compose_service_environment("vps-device")
    assert service_env, "vps-device declares no environment"

    # The enrollment script writes VPS_DEVICE_TOKEN into secrets.env.
    host_env = {"VPS_DEVICE_TOKEN": "vps-device-token-value", "FLEET_ENV": "development"}
    resolved = {key: resolve(value, host_env) for key, value in service_env.items()}

    identity_file = tmp_path / "device-identity.conf"
    alloy_config = tmp_path / "config.alloy"
    env = dict(os.environ)
    env.update(resolved)
    env.update(
        {
            "FLEET_AGENT_LIB_DIR": str(AGENT_REPO / "usr" / "lib" / "fleet-agent"),
            "FLEET_IDENTITY_FILE": str(identity_file),
            "FLEET_ALLOY_CONFIG": str(alloy_config),
            "FLEET_ALLOY_DATA_DIR": str(tmp_path / "alloy-data"),
        }
    )

    proc = subprocess.run(
        [str(CONTAINER_ENTRYPOINT), "--render-only"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr

    parsed = run_agent_parser(identity_file)
    assert parsed.returncode == 0, parsed.stderr
    assert parsed.stdout.strip() == resolved["DEVICE_ID"]

    rendered = alloy_config.read_text(encoding="utf-8")
    assert 'target_label = "environment"' in rendered
    assert 'target_label = "ring"' in rendered
    # No substitution left unresolved (the template header mentions the word).
    assert not re.search(r'"[A-Z_]*PLACEHOLDER', rendered)


@pytest.mark.parametrize("key", ["RING", "ENVIRONMENT"])
def test_vps_device_declares_the_mandatory_telemetry_labels(key):
    assert key in compose_service_environment("vps-device")


# ── Criterion 9 — FLEET_DOMAIN reaches the API container ───────────────────


def test_compose_injects_fleet_domain_into_fleet_api():
    assert "FLEET_DOMAIN" in compose_service_environment("fleet-api")
