"""Device identity contract — platform/ side (SPEC-contrat-identite-appareil).

Covers acceptance criteria 5 (automation producer), 7, 9, 15, 16, 17 and 20.

What these tests actually read, stated exactly, because the name "contract
tests" invites a larger claim than the files support:

* the **platform** side — the Ansible template, the role tasks, group_vars, the
  diagnostics playbook and docker-compose.yml — from ``platform/``;
* the **agent** side — ``identity-lib.sh`` (the strict parser and the key list),
  ``generate-config.sh``, ``firstboot.sh`` and ``container-entrypoint.sh`` — from
  ``agent/``, the sibling folder of the same repository.

``api/app/contracts/device_identity.py`` is the contract's source of truth, and
it is **not read here**: ``contract_keys()`` below reads the agent-side copy in
``identity-lib.sh``. Keeping that copy equal to the Python module is the job of
``api/tests/test_device_identity_contract.py``. So a divergence between
``platform/`` and ``agent/`` fails here; a divergence between ``agent/`` and
``api/`` fails there.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, meta

PLATFORM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

IDENTITY_LIB = AGENT_DIR / "usr" / "lib" / "fleet-agent" / "identity-lib.sh"
CONTAINER_ENTRYPOINT = AGENT_DIR / "container-entrypoint.sh"
TEMPLATE_DIR = PLATFORM_DIR / "ansible" / "roles" / "fleet_agent" / "templates"
TEMPLATE_NAME = "device-identity.conf.j2"
ROLE_TASKS = PLATFORM_DIR / "ansible" / "roles" / "fleet_agent" / "tasks" / "main.yml"
GROUP_VARS = PLATFORM_DIR / "ansible" / "group_vars" / "all" / "vars.yml"
DIAGNOSTICS = PLATFORM_DIR / "ansible" / "playbooks" / "collect_diagnostics.yml"
COMPOSE = PLATFORM_DIR / "docker" / "docker-compose.yml"
FIRSTBOOT = AGENT_DIR / "usr" / "lib" / "fleet-agent" / "firstboot.sh"
GENERATE_CONFIG = AGENT_DIR / "usr" / "lib" / "fleet-agent" / "generate-config.sh"
ANSIBLE_DIR = PLATFORM_DIR / "ansible"
BOOTSTRAP_PLAYBOOK = ANSIBLE_DIR / "playbooks" / "bootstrap_device.yml"

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
        f"{path} is missing. The device identity contract spans three components of "
        f"the monorepo; they must all be present under {REPO_ROOT}."
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
    """Feed a file to the real agent parser."""
    bash = shutil.which("bash")
    assert bash, "bash is required to exercise the agent parser"
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
    """Both directions, because the test name promises both.

    Producer side: every key this repository writes must be one the agent parser
    accepts — an extra key is not ignored, ``fleet_identity_parse`` rejects the
    whole file on it.

    Consumer side: every ``${FLEET_ID_*}`` the agent dereferences must be a key
    this repository writes — a missing one expands to the empty string under the
    parser's prefix and the failure shows up far from its cause.

    Both sets are asserted non-empty first. A regex that stopped matching (the
    ``FLEET_ID_`` prefix renamed, the key list reformatted) would otherwise make
    an empty set satisfy every inclusion below and turn this into a test that
    passes by measuring nothing.
    """
    rendered = set(keys_of(render_template()))
    accepted = set(contract_keys())
    referenced = set(re.findall(r"\$\{FLEET_ID_([A-Z_]+)[:}]", read(FIRSTBOOT)))

    assert rendered, "the Ansible template rendered no KEY=value line"
    assert accepted, "identity-lib.sh declares no contract key"
    assert referenced, "firstboot.sh dereferences no FLEET_ID_* value"

    assert rendered <= accepted, sorted(rendered - accepted)
    assert referenced <= rendered, sorted(referenced - rendered)


# ── Criterion 7 — the automation path cannot emit a file the agent rejects ──
#
# Rendering a syntactically valid file is not enough. generate-config.sh is run
# by the role's own "Regenerate collector config" handler, right after the
# template task, so anything it refuses fails the play on the device. These
# tests replay that script on the real Ansible render instead of stopping at the
# parser, which accepts empty values for MQTT_USERNAME and MQTT_PASSWORD that
# generate-config.sh then demands.


def ansible_bool(value: object) -> bool:
    """Ansible's ``| bool`` filter, restricted to the values under test here.

    Plain Jinja2 has no ``bool`` filter — Ansible adds it — and the role's guard
    is written with it because a host_vars override may spell the flag as a
    string. Reimplemented narrowly so evaluating the guard's real expression
    needs no Ansible installation; any value outside this set raises rather than
    guessing.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        if value.lower() in {"true", "yes", "on", "1"}:
            return True
        if value.lower() in {"false", "no", "off", "0", ""}:
            return False
    raise AssertionError(f"ansible_bool: unhandled value {value!r}")


def load_yaml(path: Path) -> object:
    return yaml.safe_load(read(path))


def role_task(name: str) -> dict:
    """Return the fleet_agent task whose ``name`` starts with the given text."""
    tasks = load_yaml(ROLE_TASKS)
    for task in tasks:
        if str(task.get("name", "")).startswith(name):
            return task
    raise AssertionError(f"no task named {name!r} in {ROLE_TASKS}")


def collect_defined_names(node: object, into: set[str]) -> None:
    """Harvest every variable name an inventory or group_vars file defines."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"children", "hosts"} and isinstance(value, dict):
                for child in value.values():
                    # A host entry is itself a mapping of variables.
                    if isinstance(child, dict):
                        if set(child) & {"children", "hosts", "vars"}:
                            collect_defined_names(child, into)
                        else:
                            into.update(child)
            elif key == "vars" and isinstance(value, dict):
                into.update(value)
            elif key == "all" and isinstance(value, dict):
                collect_defined_names(value, into)
            else:
                into.add(key)


def defined_ansible_variables() -> set[str]:
    names: set[str] = set()
    for path in sorted((ANSIBLE_DIR / "group_vars").rglob("*.yml")):
        data = load_yaml(path)
        if isinstance(data, dict):
            names.update(data)
    for path in sorted((ANSIBLE_DIR / "inventories").rglob("*.yml")):
        collect_defined_names(load_yaml(path), names)
    # Facts the bootstrap play sets before the fleet_agent role runs.
    for task in yaml.safe_load(read(BOOTSTRAP_PLAYBOOK))[0].get("pre_tasks", []):
        fact = task.get("ansible.builtin.set_fact") or task.get("set_fact") or {}
        names.update(k for k in fact if k != "cacheable")
    # Ansible magic variables the template is entitled to use.
    names.add("inventory_hostname")
    return names


def template_variables() -> set[str]:
    env = Environment(autoescape=False)  # parsing only, nothing is rendered
    return meta.find_undeclared_variables(env.parse(read(TEMPLATE_DIR / TEMPLATE_NAME)))


def test_every_template_variable_is_defined_somewhere_in_the_inventory():
    """No name in the template may exist only in the template.

    ``{{ foo | default('') }}`` on a variable that nothing defines is not a
    default, it is a permanent empty value that no run can ever fill — and the
    filter is what hides it. Both HEADSCALE_PREAUTH_KEY and the MQTT credentials
    shipped that way.
    """
    referenced = template_variables()
    assert referenced, "the template reads no variable — the parse went wrong"
    defined = defined_ansible_variables()
    assert defined, "no variable definitions found under ansible/"
    assert referenced <= defined, sorted(referenced - defined)


def test_group_vars_define_the_identity_credentials_the_template_writes():
    """The three names the review found undefined, pinned by name."""
    declared = load_yaml(GROUP_VARS)
    for name in ("headscale_preauth_key", "repo_basic_token", "mqtt_username", "mqtt_password"):
        assert name in declared, f"{name} is read by the template but declared nowhere"


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        # Exporter off: credentials are irrelevant, the guard must not fire.
        ({"enable_mqtt_exporter": False, "mqtt_username": "", "mqtt_password": ""}, True),
        # Exporter on with both credentials: the supported configuration.
        ({"enable_mqtt_exporter": True, "mqtt_username": "u", "mqtt_password": "p"}, True),
        # Exporter on, credentials missing: generate-config.sh would refuse.
        ({"enable_mqtt_exporter": True, "mqtt_username": "", "mqtt_password": "p"}, False),
        ({"enable_mqtt_exporter": True, "mqtt_username": "u", "mqtt_password": ""}, False),
        ({"enable_mqtt_exporter": True, "mqtt_username": "", "mqtt_password": ""}, False),
        # The flag may arrive as a string from host_vars.
        ({"enable_mqtt_exporter": "true", "mqtt_username": "u", "mqtt_password": ""}, False),
    ],
)
def test_role_guard_holds_exactly_when_the_exporter_can_be_configured(variables, expected):
    """Evaluate the role's own assert expression, not a copy of it."""
    task = role_task("Assert the MQTT exporter")
    conditions = task["ansible.builtin.assert"]["that"]
    assert conditions, "the assert declares no condition"

    env = Environment(undefined=StrictUndefined, autoescape=False)
    env.filters["bool"] = ansible_bool
    for condition in conditions:
        holds = env.from_string("{{ (" + condition + ") | string }}").render(**variables)
        assert (holds == "True") is expected, f"{condition!r} on {variables!r} gave {holds}"


def test_role_asserts_before_it_writes_the_identity_file():
    """The guard is worthless after the file is on disk."""
    names = [str(task.get("name", "")) for task in load_yaml(ROLE_TASKS)]
    guard = next(i for i, n in enumerate(names) if n.startswith("Assert the MQTT exporter"))
    deploy = next(i for i, n in enumerate(names) if n.startswith("Deploy device-identity.conf"))
    assert guard < deploy, names


def run_generate_config(identity_file: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the agent's real generate-config.sh on a rendered identity file.

    A stub stands in for /usr/bin/alloy: the script only tests it for the
    executable bit to pick a telemetry runtime, and never executes it.
    """
    alloy_stub = tmp_path / "alloy-stub"
    alloy_stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    alloy_stub.chmod(0o755)

    env = dict(os.environ)
    env.update(
        {
            "FLEET_IDENTITY_FILE": str(identity_file),
            "FLEET_ALLOY_BIN": str(alloy_stub),
            "FLEET_ALLOY_CONFIG": str(tmp_path / "alloy" / "config.alloy"),
            "FLEET_VECTOR_BIN": str(tmp_path / "no-vector"),
        }
    )
    return subprocess.run(
        [str(GENERATE_CONFIG)], capture_output=True, text=True, check=False, env=env
    )


def test_generate_config_accepts_the_render_with_the_mqtt_exporter_enabled(tmp_path):
    """The case the play actually hits on a Mosquitto host.

    ``enable_mqtt_exporter: true`` is a documented, supported host_vars setting
    (group_vars/all/vars.yml, host_vars/README.md). On such a host the template
    task notifies the handler that runs this script, so anything it refuses
    fails the play on the first run.
    """
    identity_file = tmp_path / "device-identity.conf"
    identity_file.write_text(render_template(enable_mqtt_exporter=True), encoding="utf-8")

    proc = run_generate_config(identity_file, tmp_path)
    assert proc.returncode == 0, proc.stderr

    rendered = (tmp_path / "alloy" / "config.alloy").read_text(encoding="utf-8")
    assert INVENTORY_VARS["mqtt_username"] in rendered
    assert 'target_label = "environment"' in rendered
    assert 'target_label = "ring"' in rendered


def test_generate_config_refuses_the_exporter_without_credentials(tmp_path):
    """Why the role guard exists, demonstrated rather than asserted.

    This is the file the automation path used to produce whenever an operator
    set ``enable_mqtt_exporter: true``: the parser accepts it — MQTT_USERNAME and
    MQTT_PASSWORD are declared as allowed-empty — and generate-config.sh then
    refuses it. The role's assert is what keeps this file from ever being
    written; if this test ever stops failing the script, the guard has become
    dead weight and should go, not be kept for decoration.
    """
    identity_file = tmp_path / "device-identity.conf"
    identity_file.write_text(
        render_template(enable_mqtt_exporter=True, mqtt_username="", mqtt_password=""),
        encoding="utf-8",
    )

    assert run_agent_parser(identity_file).returncode == 0, "the parser should accept this file"

    proc = run_generate_config(identity_file, tmp_path)
    assert proc.returncode != 0
    assert "MQTT_USERNAME" in proc.stderr


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
            "FLEET_AGENT_LIB_DIR": str(AGENT_DIR / "usr" / "lib" / "fleet-agent"),
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
