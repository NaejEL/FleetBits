#!/bin/bash
# scripts/run-tests.sh
# ─────────────────────────────────────────────────────────────────────────────
# Single entry point for the FleetBits-platform checks:
#   1. docker compose config -q                 — compose validation
#   2. ansible-playbook --syntax-check          — playbook syntax
#   3. ansible-lint on the device-identity scope — GATE, must be clean
#   4. pytest                                   — device identity contract suite
#   5. ansible-lint on the whole repository     — pre-existing debt, RATCHET
#
# Why 3 and 5 are two different steps
# -----------------------------------
# `ansible-lint playbooks/ roles/` reports violations that predate the device
# identity contract work: var-naming, name-casing, yaml formatting,
# command-instead-of-module, risky-file-permissions, ignore-errors and
# no-changed-when, spread over app_config, deploy_artifact, headscale_enroll,
# systemd_exporter, systemd_hardening and bootstrap_device.yml. Cleaning them up
# is a separate piece of work and is NOT in the scope of this entry point.
#
# Nothing is skipped and nothing is hidden:
#   - step 3 GATES the files this contract owns (roles/fleet_agent/ and
#     playbooks/collect_diagnostics.yml). Those must be, and are, lint-clean.
#   - step 5 prints the WHOLE repository report in full and fails if the total
#     count rises above the recorded baseline. Existing debt stays visible and
#     named; new debt cannot slip in unnoticed.
#
# Ansible and Docker Compose are used from $PATH when installed and from their
# official container images otherwise. Nothing here ever touches a real
# inventory: syntax and lint only.
#
#   ./scripts/run-tests.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

ANSIBLE_IMAGE="${ANSIBLE_IMAGE:-willhallonline/ansible:latest}"
ANSIBLE_LINT_IMAGE="${ANSIBLE_LINT_IMAGE:-pipelinecomponents/ansible-lint:latest}"
# The .gitignore of this repository does not ignore .venv/, so the virtualenv
# lives beside the repository rather than inside it.
VENV="${FLEET_PLATFORM_VENV:-${REPO_ROOT}/../.venv-platform}"

echo "── docker compose config ────────────────────────────────────────────────"
# secrets.env.example supplies every variable the composition declares as
# required; the real secrets.env is never needed to validate the file.
docker compose --env-file secrets.env.example -f docker/docker-compose.yml config -q
echo "compose: OK"

echo "── ansible syntax check ─────────────────────────────────────────────────"
# ansible.cfg points vault_password_file at ~/.fleet-vault-pass, which no CI
# runner and no fresh checkout has. A syntax check parses playbooks and never
# needs a real secret, so point the setting at an empty throw-away file. If an
# encrypted vault is ever committed, this fails loudly rather than decrypting.
VAULT_STUB="$(mktemp)"
printf "syntax-check-only\n" > "${VAULT_STUB}"
trap 'rm -f "${VAULT_STUB}"' EXIT

if command -v ansible-playbook >/dev/null 2>&1; then
  (cd ansible && ANSIBLE_VAULT_PASSWORD_FILE="${VAULT_STUB}" \
    ansible-playbook --syntax-check playbooks/site.yml)
else
  echo "ansible-playbook not on PATH — using ${ANSIBLE_IMAGE}"
  docker run --rm \
    -v "${REPO_ROOT}/ansible":/w -v "${VAULT_STUB}":/tmp/vault-pass:ro -w /w \
    -e ANSIBLE_VAULT_PASSWORD_FILE=/tmp/vault-pass \
    "${ANSIBLE_IMAGE}" \
    ansible-playbook --syntax-check playbooks/site.yml
fi
echo "ansible syntax: OK"

# ansible_lint PATH... — run ansible-lint over the given paths, from ansible/.
# Prints its report on stdout and returns ansible-lint's own exit status.
ansible_lint() {
  if command -v ansible-lint >/dev/null 2>&1; then
    (cd ansible && ANSIBLE_VAULT_PASSWORD_FILE="${VAULT_STUB}" ansible-lint "$@")
  else
    docker run --rm \
      -v "${REPO_ROOT}/ansible":/w -v "${VAULT_STUB}":/tmp/vault-pass:ro -w /w \
      -e ANSIBLE_VAULT_PASSWORD_FILE=/tmp/vault-pass \
      "${ANSIBLE_LINT_IMAGE}" \
      ansible-lint "$@"
  fi
}

# The files this repository contributes to the device identity contract. This
# list is the lint gate: it must stay empty of violations.
IDENTITY_SCOPE=(
  roles/fleet_agent/
  playbooks/collect_diagnostics.yml
)

echo "── ansible-lint (device identity scope) ─────────────────────────────────"
if ! command -v ansible-lint >/dev/null 2>&1; then
  echo "ansible-lint not on PATH — using ${ANSIBLE_LINT_IMAGE}"
fi
ansible_lint "${IDENTITY_SCOPE[@]}"
echo "ansible-lint (device identity scope): OK"

echo "── pytest ───────────────────────────────────────────────────────────────"
if [ ! -x "${VENV}/bin/python" ]; then
  echo "Creating the test virtualenv at ${VENV}"
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install --quiet pytest jinja2
fi
"${VENV}/bin/python" -m pytest -q
echo "pytest: OK"

echo "── ansible-lint (whole repository — FAILING, pre-existing debt) ─────────"
# This pass DOES NOT PASS, and is not claimed to. ansible-lint reports 34
# violations across playbooks/ and roles/; all of them predate the device
# identity contract and all of them live outside roles/fleet_agent/ and
# playbooks/collect_diagnostics.yml, which are gated for real above.
#
# What this step enforces is a ratchet: the debt may shrink, never grow. The
# full report is printed unfiltered on every run so the debt stays visible
# rather than silenced.
#
# The baseline is deliberately NOT overridable from the environment: a ratchet
# a CI job can loosen without touching the repository is not a ratchet. Lower
# this literal when the report shrinks; raising it requires a justification in
# the commit message.
readonly ANSIBLE_LINT_DEBT_BASELINE=34

LINT_REPORT="$(mktemp)"
trap 'rm -f "${VAULT_STUB}" "${LINT_REPORT}"' EXIT
ansible_lint playbooks/ roles/ > "${LINT_REPORT}" 2>&1 || true
cat "${LINT_REPORT}"

# "Failed: N failure(s), ..." when there are violations; no such line when clean.
DEBT_COUNT="$(sed -n 's/^Failed: \([0-9]\+\) failure(s).*/\1/p' "${LINT_REPORT}" | head -n 1)"
DEBT_COUNT="${DEBT_COUNT:-0}"

echo
echo "ansible-lint (whole repository): ${DEBT_COUNT} pre-existing violation(s), baseline ${ANSIBLE_LINT_DEBT_BASELINE}"
if [ "${DEBT_COUNT}" -gt "${ANSIBLE_LINT_DEBT_BASELINE}" ]; then
  echo "FAIL: repository-wide ansible-lint debt grew (${DEBT_COUNT} > ${ANSIBLE_LINT_DEBT_BASELINE})." >&2
  echo "      Fix the new violation, or justify and raise the baseline explicitly." >&2
  exit 1
fi
if [ "${DEBT_COUNT}" -lt "${ANSIBLE_LINT_DEBT_BASELINE}" ]; then
  echo "NOTE: debt shrank to ${DEBT_COUNT}. Lower ANSIBLE_LINT_DEBT_BASELINE in this script."
fi
echo "ansible-lint (whole repository): still failing with ${DEBT_COUNT} violation(s);"
echo "                                 debt did not grow, so this step does not block."
