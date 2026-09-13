"""Device identity contract — cross-component conformance (SPEC-contrat-identite-appareil).

The contract declared in ``app.contracts.device_identity`` is the single source
of truth for ``/etc/fleet/device-identity.conf``. These tests compare it against
every other producer and consumer of the monorepo:

* ``agent/usr/lib/fleet-agent/identity-lib.sh``              (parser whitelist)
* ``agent/container-entrypoint.sh``                          (container producer)
* ``platform/ansible/.../device-identity.conf.j2``           (automation producer)

They deliberately reach into the sibling top-level folders of the same
repository: a desynchronised component must fail a test rather than a device.

Markers
-------
Every test that reads another component carries ``@pytest.mark.crossrepo`` and,
deliberately, NOT ``@pytest.mark.security``. The security marker selects the
suite that CI runs *inside the fleet-api container image*
(``.github/workflows/security-regression-stack.yml``, ``docker compose exec
fleet-api pytest -q -m security tests``); that image is built from the Dockerfile,
which copies ``/app`` and nothing else, so no sibling folder exists there and a
cross-component test could only fail. The separation is not a weakening: those
tests run in full, over the whole checkout, in ``.github/workflows/api-tests.yml``
and in the documented local command ``./.venv/bin/python -m pytest``. Nothing is
skipped anywhere.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.device_identity import (
    KEYS,
    OPTIONAL_KEYS,
    SECRET_KEYS,
    VALUE_PATTERN,
    IdentityContractError,
    validate,
)
from app.contracts.device_identity import parse as parse_identity
from app.contracts.device_identity import render as render_identity
from app.models.device import Device
from app.models.token import ProvisionToken
from app.services.device_identity import (
    LOGS_HOST_PREFIX,
    LOGS_PATH,
    METRICS_HOST_PREFIX,
    METRICS_PATH,
)
from app.services.token import create_provision_token, hash_token

# ── Monorepo layout ──────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / "agent"
PLATFORM_DIR = REPO_ROOT / "platform"
API_DIR = Path(__file__).resolve().parents[1]

IDENTITY_LIB = AGENT_DIR / "usr" / "lib" / "fleet-agent" / "identity-lib.sh"
CONTAINER_ENTRYPOINT = AGENT_DIR / "container-entrypoint.sh"
FIRSTBOOT = AGENT_DIR / "usr" / "lib" / "fleet-agent" / "firstboot.sh"
ANSIBLE_TEMPLATE = (
    PLATFORM_DIR / "ansible" / "roles" / "fleet_agent" / "templates" / "device-identity.conf.j2"
)
CADDYFILE = PLATFORM_DIR / "docker" / "caddy" / "Caddyfile"
COMPOSE_FILE = PLATFORM_DIR / "docker" / "docker-compose.yml"
DEVICES_ROUTER = API_DIR / "app" / "routers" / "devices.py"


def read(path: Path) -> str:
    assert path.is_file(), (
        f"{path} is missing. The device identity contract spans three components of "
        f"the monorepo; they must all be present under {REPO_ROOT}."
    )
    return path.read_text(encoding="utf-8")


def shell_array(source: str, name: str) -> list[str]:
    """Extract the elements of a literal bash array assignment."""
    match = re.search(rf"^{re.escape(name)}=\((.*?)\n\)", source, re.MULTILINE | re.DOTALL)
    assert match, f"{name} not found as a literal array"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


# ── Criterion 5 — the four key sets are identical ────────────────────────────


@pytest.mark.crossrepo
class TestContractKeySets:
    def test_agent_parser_whitelist_matches_contract(self):
        source = read(IDENTITY_LIB)
        assert shell_array(source, "FLEET_IDENTITY_KEYS") == list(KEYS)
        assert set(shell_array(source, "FLEET_IDENTITY_OPTIONAL_KEYS")) == set(OPTIONAL_KEYS)
        assert set(shell_array(source, "FLEET_IDENTITY_SECRET_KEYS")) == set(SECRET_KEYS)

    def test_agent_parser_value_charset_matches_contract(self):
        source = read(IDENTITY_LIB)
        match = re.search(r"^FLEET_IDENTITY_VALUE_PATTERN='(.+)'$", source, re.MULTILINE)
        assert match, "FLEET_IDENTITY_VALUE_PATTERN not found"
        assert match.group(1) == VALUE_PATTERN

    # Values probing every boundary of the charset: the separators the sed
    # renderer cares about, the shell metacharacters the inertness of the format
    # rests on, and the anchor dialects of the two regex engines.
    VALUE_PROBES: ClassVar[tuple[str, ...]] = (
        "video-player",
        "https://logs.fleet.example.com/loki/api/v1/push",
        "a.b_c:d/e@f=g+h,i~j-k",
        "",
        " ",
        "a b",
        "a\tb",
        "a\nb",
        # Python's '$' matches before a final newline; POSIX ERE's does not.
        "role\n",
        "role\n\n",
        "role\nEXTRA=x",
        "role\r",
        "a;b",
        "a|b",
        "a&b",
        "a\\b",
        "a$b",
        "a`b`",
        "a'b",
        'a"b',
        "a#b",
        "a!b",
        "a(b)",
        "a[b]",
        "a{b}",
        "a<b",
        "a>b",
        "a?b",
        "a*b",
        "a%b",
        "a^b",
        "rôle",
        "aé",
        # NUL is deliberately absent *from this list*: these probes are fed to
        # fleet_identity_set through a bash variable, and a bash variable cannot
        # hold a NUL byte, so a NUL probe would compare a truncated value. The
        # byte is not out of reach of the contract for all that — a FILE can
        # contain one, and both parsers must reject such a file. That verdict is
        # compared in test_a_nul_byte_in_the_file_is_rejected_by_both_parsers
        # below, and on the agent side in tests/identity_parser.bats.
    )

    # Locales the bash validator is cross-checked under. The charset pattern is
    # a bracket expression built from ranges, and a range is resolved against
    # the COLLATION ORDER of the active locale: under a glibc UTF-8 locale
    # 'A-Za-z' used to sweep in accented letters, so 'rôle' and 'aé' were
    # accepted by bash and rejected by Python. No consumer pins a locale (the
    # systemd units and container-entrypoint.sh inherit the host's), so the
    # agreement has to hold under whatever locale a device happens to run.
    LOCALE_CANDIDATES: ClassVar[tuple[str, ...]] = (
        "C",
        "POSIX",
        "C.UTF-8",
        "en_US.UTF-8",
        "fr_FR.UTF-8",
    )

    @staticmethod
    def _installed_locales() -> dict[str, str]:
        """Map a normalised locale name to the spelling ``locale -a`` uses."""
        locale_bin = shutil.which("locale")
        if not locale_bin:
            return {}
        proc = subprocess.run(
            [locale_bin, "-a"], capture_output=True, text=True, check=False, errors="replace"
        )
        installed = {}
        for name in proc.stdout.split():
            installed.setdefault(name.lower().replace("-", ""), name)
        return installed

    def _probe_locales(self) -> list[str]:
        installed = self._installed_locales()
        chosen = [
            installed[candidate.lower().replace("-", "")]
            for candidate in self.LOCALE_CANDIDATES
            if candidate.lower().replace("-", "") in installed
        ]
        assert any("utf" in name.lower() for name in chosen), (
            "no UTF-8 locale is installed, so the locale-collation divergence this "
            f"test exists to catch cannot be exercised. Candidates: {self.LOCALE_CANDIDATES}"
        )
        return chosen

    def _bash_verdicts(self, bash: str, probes_file: Path, locale_name: str) -> list[str]:
        # fleet_identity_set is called directly: the file parser is line-based
        # and could never present it a value containing a newline.
        script = (
            f'. "{IDENTITY_LIB}"\n'
            f'while IFS= read -r -d "" probe; do\n'
            f'  if fleet_identity_set DEVICE_ROLE "$probe" 2>/dev/null; then\n'
            f"    echo accept\n"
            f"  else\n"
            f"    echo reject\n"
            f"  fi\n"
            f'done < "{probes_file}"\n'
        )
        proc = subprocess.run(
            [bash, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "LANG": locale_name,
                "LC_ALL": locale_name,
            },
        )
        assert proc.returncode == 0, f"[{locale_name}] {proc.stderr}"
        verdicts = proc.stdout.split()
        assert len(verdicts) == len(self.VALUE_PROBES), f"[{locale_name}] {proc.stdout}"
        return verdicts

    def test_python_and_bash_validators_agree_on_every_probe(self, tmp_path):
        """Comparing the two pattern *strings* is not enough.

        ``test_agent_parser_value_charset_matches_contract`` proves the two
        repositories spell the same expression; it cannot prove the two engines
        *decide* the same — ``$`` does not mean the same thing in Python and in
        POSIX ERE, and a character range does not cover the same characters in
        the C locale and in a UTF-8 one. This test runs both validators over the
        same probes, under every locale installed from ``LOCALE_CANDIDATES``,
        and fails on the first disagreement.
        """
        bash = shutil.which("bash")
        assert bash, "bash is required to exercise the agent parser"
        assert IDENTITY_LIB.is_file(), f"{IDENTITY_LIB} is missing"

        probes_file = tmp_path / "probes.bin"
        probes_file.write_bytes(b"".join(p.encode("utf-8") + b"\0" for p in self.VALUE_PROBES))

        python_verdicts = []
        for probe in self.VALUE_PROBES:
            try:
                validate({**{key: "x" for key in KEYS}, "DEVICE_ROLE": probe})
                python_verdicts.append("accept")
            except IdentityContractError:
                python_verdicts.append("reject")

        disagreements = []
        for locale_name in self._probe_locales():
            bash_verdicts = self._bash_verdicts(bash, probes_file, locale_name)
            for probe, python_verdict, bash_verdict in zip(
                self.VALUE_PROBES, python_verdicts, bash_verdicts, strict=True
            ):
                if python_verdict != bash_verdict:
                    disagreements.append(
                        (locale_name, probe, f"python={python_verdict} bash={bash_verdict}")
                    )
        assert not disagreements, f"validators disagree on: {disagreements}"

    def test_a_nul_byte_in_the_file_is_rejected_by_both_parsers(self, tmp_path):
        """A NUL byte must be a parse error, not a silently mutated value.

        ``IFS= read -r line`` drops NUL bytes rather than reporting them, so a
        line ``DEVICE_ROLE=a<NUL>b`` used to be accepted by the agent parser with
        the value quietly rewritten to ``ab``, while the Python contract rejected
        the very same bytes. The two sides must return the same verdict on the
        same file.
        """
        bash = shutil.which("bash")
        assert bash, "bash is required to exercise the agent parser"

        raw = b"".join(
            f"{key}=".encode() + (b"a\x00b" if key == "DEVICE_ROLE" else b"x") + b"\n"
            for key in KEYS
        )
        identity_file = tmp_path / "device-identity.conf"
        identity_file.write_bytes(raw)

        with pytest.raises(IdentityContractError):
            parse_identity(raw.decode("utf-8"))

        proc = subprocess.run(
            [bash, "-c", f'. "{IDENTITY_LIB}"\nfleet_identity_parse "{identity_file}"\n'],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        assert proc.returncode != 0, (
            "the agent parser accepted a file containing a NUL byte; "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )

    def test_a_value_with_a_trailing_newline_is_refused(self):
        """Regression guard for the ``$`` vs ``\\Z`` anchor difference."""
        with pytest.raises(IdentityContractError):
            render_identity({**{key: "x" for key in KEYS}, "DEVICE_ROLE": "role\n"})

    def test_container_entrypoint_produces_contract_keys(self):
        produced = re.findall(
            r"^fleet_identity_set\s+([A-Z_]+)\s", read(CONTAINER_ENTRYPOINT), re.MULTILINE
        )
        assert produced == list(KEYS)

    def test_ansible_template_produces_contract_keys(self):
        rendered_keys = [
            line.split("=", 1)[0]
            for line in read(ANSIBLE_TEMPLATE).splitlines()
            if re.match(r"^[A-Z][A-Z0-9_]*=", line)
        ]
        assert rendered_keys == list(KEYS)

    def test_all_four_key_sets_are_equal(self):
        api_keys = set(KEYS)
        parser_keys = set(shell_array(read(IDENTITY_LIB), "FLEET_IDENTITY_KEYS"))
        container_keys = set(
            re.findall(
                r"^fleet_identity_set\s+([A-Z_]+)\s", read(CONTAINER_ENTRYPOINT), re.MULTILINE
            )
        )
        ansible_keys = {
            line.split("=", 1)[0]
            for line in read(ANSIBLE_TEMPLATE).splitlines()
            if re.match(r"^[A-Z][A-Z0-9_]*=", line)
        }
        assert api_keys == parser_keys == container_keys == ansible_keys


# ── Criterion 8 — telemetry URLs match the Caddy routing ─────────────────────


@pytest.mark.crossrepo
class TestTelemetryUrlsMatchCaddyfile:
    def test_metrics_host_and_path_are_exposed_by_caddy(self):
        caddy = read(CADDYFILE)
        site = f"{METRICS_HOST_PREFIX}{{$FLEET_DOMAIN}} {{"
        assert site in caddy, f"no Caddy site block for {METRICS_HOST_PREFIX}<domain>"
        block = caddy.split(site, 1)[1].split("\n}\n", 1)[0]
        assert f"path {METRICS_PATH}" in block

    def test_logs_host_and_path_are_exposed_by_caddy(self):
        caddy = read(CADDYFILE)
        site = f"{LOGS_HOST_PREFIX}{{$FLEET_DOMAIN}} {{"
        assert site in caddy, f"no Caddy site block for {LOGS_HOST_PREFIX}<domain>"
        block = caddy.split(site, 1)[1].split("\n}\n", 1)[0]
        assert f"path {LOGS_PATH}" in block

    def test_no_prometheus_or_loki_hostnames_are_handed_to_devices(self):
        """The old contract shipped prometheus./loki. hosts that Caddy never served."""
        service = read(API_DIR / "app" / "services" / "device_identity.py")
        assert "prometheus." not in service
        assert "loki." not in service


# ── Criterion 9 — FLEET_DOMAIN is a start-up setting ─────────────────────────


class TestFleetDomainSetting:
    def test_settings_refuse_to_build_without_fleet_domain(self, monkeypatch):
        from pydantic import ValidationError

        from app.config import Settings

        monkeypatch.delenv("FLEET_DOMAIN", raising=False)
        monkeypatch.setenv("FLEET_JWT_SECRET", "x" * 40)
        monkeypatch.setenv("OPERATOR_PASSWORD", "y" * 16)
        with pytest.raises(ValidationError) as exc:
            Settings(_env_file=None)
        assert "FLEET_DOMAIN" in str(exc.value)

    @pytest.mark.crossrepo
    def test_compose_injects_fleet_domain_into_fleet_api(self):
        compose = read(COMPOSE_FILE)
        api_block = compose.split("\n  fleet-api:\n", 1)[1].split("\n  fleet-ui:\n", 1)[0]
        assert re.search(r'^\s+FLEET_DOMAIN:\s+"\$\{FLEET_DOMAIN', api_block, re.MULTILINE)


# ── Criteria 1 and 21 — one route, one format, no legacy remnant ─────────────


@pytest.mark.crossrepo
class TestNoLegacyPathOrFormat:
    def test_firstboot_calls_the_declared_route(self):
        declared = re.search(
            r'@router\.post\(\s*"(/\{device_id\}/provision)"', read(DEVICES_ROUTER)
        )
        assert declared, "provisioning route decorator not found"
        called = re.search(r'"\$\{API_URL\}(/api/v1/devices/[^"]*provision)"', read(FIRSTBOOT))
        assert called, "firstboot.sh does not build a provisioning URL"
        # Compare segment by segment, device id placeholder included.
        expected = ["api", "v1", "devices", "{device_id}", "provision"]
        actual = called.group(1).strip("/").split("/")
        actual = ["{device_id}" if seg == "${DEVICE_ID}" else seg for seg in actual]
        assert actual == expected
        assert declared.group(1).strip("/").split("/") == expected[3:]

    # Built by concatenation so this very file is not a match for its own search.
    FORBIDDEN: ClassVar[dict[str, str]] = {
        # criterion 1: provisioning route without a device id
        "legacy-route": "/devices" + "/provision",
        # criteria 2 and 21: shell evaluation of the identity file
        "shell-source": "source " + '"${IDENTITY_FILE}"',
        # criterion 21: the old JSON response model
        "json-model": "Device" + "Identity",
    }

    @pytest.mark.parametrize("name", sorted(FORBIDDEN))
    def test_pattern_absent_from_every_repository(self, name):
        forbidden = self.FORBIDDEN[name]
        repos = (API_DIR, AGENT_DIR, PLATFORM_DIR, REPO_ROOT / "ui")
        # Criterion 21 says "the four repositories" — now the four top-level
        # folders of the monorepo. A missing folder must fail the test, never
        # silently reduce the search: a green run that swept one out of four
        # proves nothing.
        missing = [str(r) for r in repos if not r.is_dir()]
        assert not missing, (
            f"criterion 21 searches all four components; missing: {missing}. "
            f"Expected them under {REPO_ROOT}."
        )
        scanned = 0
        hits = []
        for repo in repos:
            for path in repo.rglob("*"):
                if not path.is_file():
                    continue
                parts = set(path.relative_to(repo).parts)
                # Generated, git-ignored artefacts only — never source or config.
                if parts & {
                    ".git",
                    ".venv",
                    "node_modules",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "dist",
                    "build",
                }:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                scanned += 1
                if forbidden in text:
                    hits.append(str(path))
        # A search that read nothing would also report no hits.
        assert scanned > 100, f"only {scanned} files were searched; the sweep did not run"
        assert hits == [], f"{forbidden!r} still present in: {hits}"

    def test_identity_file_is_never_sourced_by_the_agent(self):
        """Criterion 2: no `source` / `.` applied to the identity file."""
        targets = list((AGENT_DIR / "usr" / "lib" / "fleet-agent").glob("*.sh"))
        targets.append(CONTAINER_ENTRYPOINT)
        assert targets
        pattern = re.compile(r"^\s*(?:source|\.)\s+\S*(?:IDENTITY|identity-file|identity\.conf)\S*")
        for path in targets:
            for lineno, line in enumerate(read(path).splitlines(), start=1):
                assert not pattern.match(line), f"{path}:{lineno}: {line.strip()}"


# ── Criterion 13 — end-to-end enrollment against the real parser ─────────────


@pytest_asyncio.fixture
async def provision_token(test_db, test_devices):
    """Create a technician provision token for device-a1-1 (decision 7).

    No API route issues these yet — that gap is a separate finding, explicitly
    out of scope for this cycle — so the record is created directly.
    """
    raw, expires_at = create_provision_token(
        created_by="technician_test", allowed_device_ids=["device-a1-1"]
    )
    async with AsyncSession(test_db, expire_on_commit=False) as session:
        session.add(
            ProvisionToken(
                token_hash=hash_token(raw),
                device_id="device-a1-1",
                # The route reads the scope from the JWT claim; the SQLite test
                # dialect has no ARRAY bind support, so the column stays NULL.
                allowed_device_ids=None,
                created_by="technician_test",
                created_at=datetime.now(UTC),
                expires_at=expires_at,
            )
        )
        await session.commit()
    return raw


async def _provision(client: AsyncClient, token: str, device_id: str = "device-a1-1"):
    return await client.post(
        f"/api/v1/devices/{device_id}/provision",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.security
class TestProvisioningProducesTheContract:
    async def test_response_is_the_identity_file_not_json(
        self, client: AsyncClient, provision_token
    ):
        response = await _provision(client, provision_token)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert not response.text.lstrip().startswith("{")

    async def test_response_satisfies_the_contract(self, client: AsyncClient, provision_token):
        response = await _provision(client, provision_token)
        values = parse_identity(response.text)
        assert list(values) == list(KEYS)
        # Criterion 6: FLEET_API_URL is present and non-empty.
        assert values["FLEET_API_URL"]
        # Criterion 11: ENVIRONMENT and RING are returned non-empty.
        assert values["ENVIRONMENT"]
        assert values["RING"]
        # Criterion 12: HEADSCALE_PREAUTH_KEY is declared and may be empty.
        assert values["HEADSCALE_PREAUTH_KEY"] == ""
        # Criterion 8: telemetry URLs point at the Caddy-exposed host + path.
        assert values["FLEET_METRICS_URL"].endswith(METRICS_PATH)
        assert f"//{METRICS_HOST_PREFIX}" in values["FLEET_METRICS_URL"]
        assert values["FLEET_LOGS_URL"].endswith(LOGS_PATH)
        assert f"//{LOGS_HOST_PREFIX}" in values["FLEET_LOGS_URL"]

    async def test_logs_url_satisfies_the_vector_absolute_url_regex(
        self, client: AsyncClient, provision_token
    ):
        """Criterion 10 — same expression as generate-config.sh render_vector_config."""
        response = await _provision(client, provision_token)
        logs_url = parse_identity(response.text)["FLEET_LOGS_URL"]
        match = re.match(r"^(https?://[^/]+)(/.*)?$", logs_url)
        assert match, logs_url
        assert match.group(2) == LOGS_PATH

    async def test_contract_violation_fails_closed(
        self, client: AsyncClient, provision_token, test_db
    ):
        """Criterion: a device record the contract rejects yields no file at all.

        This drives the route, not ``validate()`` in isolation: the branch under
        test is ``except IdentityContractError -> HTTPException(500)`` in
        ``app/routers/devices.py``. Remove that branch and the request either
        raises through as a 500 with a traceback body or, worse, hands the
        device an unparseable file — either way this test fails.
        """
        # 'video player' holds a space: outside VALUE_PATTERN, so the renderer
        # must refuse it. The value reaches the contract straight from the
        # device record, which nothing else validates.
        async with AsyncSession(test_db, expire_on_commit=False) as session:
            device = await session.get(Device, "device-a1-1")
            assert device is not None
            device.role = "video player"
            await session.commit()

        response = await _provision(client, provision_token)

        assert response.status_code == 500
        detail = response.json()["detail"]
        # The key is named so an operator can fix the record...
        assert "DEVICE_ROLE" in detail
        # ... but the offending value is never echoed back (GUIDELINES.md §3),
        # and no identity file is emitted.
        assert "video player" not in detail
        with pytest.raises(IdentityContractError):
            parse_identity(response.text)


# ── Criterion 13 — the API bytes are fed to the real agent parser ────────────
#
# Cross-component, therefore NOT @pytest.mark.security: see the module docstring.


@pytest.mark.crossrepo
class TestProvisioningIsAcceptedByTheAgentParser:
    async def test_response_is_accepted_by_the_agent_parser(
        self, client: AsyncClient, provision_token, tmp_path
    ):
        """Criterion 13 — the bytes the API returns are fed to the real bash parser."""
        bash = shutil.which("bash")
        assert bash, "bash is required to exercise the agent parser"
        assert IDENTITY_LIB.is_file(), f"{IDENTITY_LIB} is missing from the checkout."
        response = await _provision(client, provision_token)

        identity_file = tmp_path / "device-identity.conf"
        identity_file.write_text(response.text, encoding="utf-8")

        script = (
            f'set -euo pipefail\n. "{IDENTITY_LIB}"\n'
            f'fleet_identity_parse "{identity_file}"\n'
            'printf "%s\\n" "${FLEET_ID_DEVICE_ID}"\n'
        )
        proc = await asyncio.to_thread(
            subprocess.run,
            [bash, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "device-a1-1"
