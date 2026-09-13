#!/bin/bash
# scripts/run-tests.sh
# ─────────────────────────────────────────────────────────────────────────────
# Single entry point for the FleetBits-platform checks:
#   1. docker compose config -q                 — compose validation, base file
#      and the CI override, which is the only real check that file ever gets
#      (pre-commit can only run check-yaml --unsafe on it: it carries Compose's
#      own `!reset` tag, which the safe YAML loader cannot resolve).
#   2. ansible-playbook --syntax-check          — playbook syntax
#   3. ansible-lint on the device-identity scope — GATE, must be clean
#   4. pytest                                   — device identity contract suite
#   5. ansible-lint on the whole repository     — pre-existing debt, RATCHET
#   6. shellcheck on every *.sh in the repo     — pre-existing debt, RATCHET
#
# Why 3 and 5 are two different steps
# -----------------------------------
# `ansible-lint playbooks/ roles/` reports violations that predate the device
# identity contract work. They are counted, listed by rule and located by file
# in tests/README.md, "Pre-existing lint debt" — that table is the single
# description of the debt, kept there so it cannot drift from this header.
# Cleaning it up is a separate piece of work and is NOT in the scope of this
# entry point.
#
# Nothing is skipped and nothing is hidden:
#   - step 3 GATES the files this contract owns (roles/fleet_agent/ and
#     playbooks/collect_diagnostics.yml). Those must be, and are, lint-clean.
#   - steps 5 and 6 print their WHOLE report in full and fail if the total count
#     rises above the recorded baseline. Existing debt stays visible and named;
#     new debt cannot slip in unnoticed.
#   - a ratchet that cannot tell "0 violations" from "the tool never ran" is not
#     a ratchet. Both ratchets below capture the tool's exit status and treat an
#     unparseable report as a hard failure, never as a clean run.
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
SHELLCHECK_IMAGE="${SHELLCHECK_IMAGE:-koalaman/shellcheck:stable}"
# The .gitignore of this repository does not ignore .venv/, so the virtualenv
# lives beside the repository rather than inside it.
VENV="${FLEET_PLATFORM_VENV:-${REPO_ROOT}/../.venv-platform}"

echo "── docker compose config ────────────────────────────────────────────────"
# secrets.env.example supplies every variable the composition declares as
# required; the real secrets.env is never needed to validate the file.
docker compose --env-file secrets.env.example -f docker/docker-compose.yml config -q
echo "compose (base): OK"
# The CI override is applied on top of the base file by the security workflow, so
# it is validated the same way it is used. This is the ONLY place it is checked
# against Compose's own schema: .pre-commit-config.yaml can only parse it with
# check-yaml --unsafe, because of its `!reset` tag.
docker compose --env-file secrets.env.example \
  -f docker/docker-compose.yml -f docker/docker-compose.ci.override.yml config -q
echo "compose (base + CI override): OK"

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
  "${VENV}/bin/pip" install --quiet pytest jinja2 pyyaml
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

# Capture the status instead of discarding it with `|| true`. ansible-lint exits
# 0 when it found nothing and 2 when it found violations; anything else means it
# did not get to measure — a failed `docker pull`, a traceback on malformed YAML,
# a missing collection. Those must fail the step, NOT be read as "0 violations":
# a silent zero here both greens the ratchet on nothing and invites lowering the
# baseline to a number no tool ever produced.
LINT_STATUS=0
ansible_lint playbooks/ roles/ > "${LINT_REPORT}" 2>&1 || LINT_STATUS=$?
cat "${LINT_REPORT}"

# "Failed: N failure(s), ..." when there are violations; no such line when clean.
DEBT_COUNT="$(sed -n 's/^Failed: \([0-9]\+\) failure(s).*/\1/p' "${LINT_REPORT}" | head -n 1)"

case "${LINT_STATUS}" in
  0)
    # Clean run: ansible-lint prints no "Failed:" summary at all.
    DEBT_COUNT=0
    ;;
  2)
    if [ -z "${DEBT_COUNT}" ]; then
      echo "FAIL: ansible-lint reported violations (exit 2) but printed no" >&2
      echo "      'Failed: N failure(s)' summary line. The report above could not" >&2
      echo "      be counted, so the ratchet has measured nothing. Fix the run" >&2
      echo "      before trusting this step." >&2
      exit 1
    fi
    ;;
  *)
    echo "FAIL: ansible-lint did not run to completion (exit ${LINT_STATUS})." >&2
    echo "      The report above is an execution failure, not a lint result." >&2
    echo "      Common causes: docker pull failed, or the linter crashed." >&2
    exit 1
    ;;
esac

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

echo "── shellcheck (every *.sh — RATCHET) ────────────────────────────────────"
# This repository ships shell: the operator scripts under scripts/, the container
# entry points under docker/ and dev-setup.sh. This step is the one place the
# linter the CI workflow installs is actually invoked, so that installation is a
# real dependency and not a promise. The file list is discovered, never
# enumerated: a new script is analysed the day it lands.
#
# Same ratchet contract as the ansible-lint step above, for the same reason: the
# 11 findings below all predate the device identity contract and live in scripts
# this work does not touch. They stay printed, counted and capped.
readonly SHELLCHECK_DEBT_BASELINE=11

SHELLCHECK_REPORT="$(mktemp)"
trap 'rm -f "${VAULT_STUB}" "${LINT_REPORT}" "${SHELLCHECK_REPORT}"' EXIT

mapfile -t SHELL_FILES < <(find . -name '*.sh' -not -path './.git/*' | sort)
if [ "${#SHELL_FILES[@]}" -eq 0 ]; then
  echo "FAIL: no *.sh found — the shellcheck step is measuring nothing." >&2
  exit 1
fi
echo "${#SHELL_FILES[@]} shell script(s) analysed"

# --format=gcc prints exactly one line per finding, which is what makes the
# count below a count and not a guess.
SHELLCHECK_STATUS=0
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --format=gcc "${SHELL_FILES[@]}" > "${SHELLCHECK_REPORT}" 2>&1 \
    || SHELLCHECK_STATUS=$?
else
  echo "shellcheck not on PATH — using ${SHELLCHECK_IMAGE}"
  docker run --rm -v "${REPO_ROOT}":/mnt -w /mnt "${SHELLCHECK_IMAGE}" \
    --format=gcc "${SHELL_FILES[@]}" > "${SHELLCHECK_REPORT}" 2>&1 \
    || SHELLCHECK_STATUS=$?
fi
cat "${SHELLCHECK_REPORT}"

# Exit status: 0 when clean, 1 when it found something; 2 and above mean a usage
# or parse error, i.e. it never measured the scripts.
case "${SHELLCHECK_STATUS}" in
  0 | 1) ;;
  *)
    echo "FAIL: shellcheck did not run to completion (exit ${SHELLCHECK_STATUS})." >&2
    echo "      The output above is an execution failure, not an analysis result." >&2
    exit 1
    ;;
esac

SHELLCHECK_COUNT="$(grep -c -E '^[^ ]+:[0-9]+:[0-9]+: (error|warning|note):' \
  "${SHELLCHECK_REPORT}" || true)"
if [ "${SHELLCHECK_STATUS}" -eq 1 ] && [ "${SHELLCHECK_COUNT}" -eq 0 ]; then
  echo "FAIL: shellcheck reported findings (exit 1) but none could be counted." >&2
  echo "      The ratchet has measured nothing; fix the run first." >&2
  exit 1
fi

echo
echo "shellcheck: ${SHELLCHECK_COUNT} pre-existing finding(s), baseline ${SHELLCHECK_DEBT_BASELINE}"
if [ "${SHELLCHECK_COUNT}" -gt "${SHELLCHECK_DEBT_BASELINE}" ]; then
  echo "FAIL: shellcheck debt grew (${SHELLCHECK_COUNT} > ${SHELLCHECK_DEBT_BASELINE})." >&2
  echo "      Fix the new finding, or justify and raise the baseline explicitly." >&2
  exit 1
fi
if [ "${SHELLCHECK_COUNT}" -lt "${SHELLCHECK_DEBT_BASELINE}" ]; then
  echo "NOTE: debt shrank to ${SHELLCHECK_COUNT}. Lower SHELLCHECK_DEBT_BASELINE in this script."
fi
echo "shellcheck: debt did not grow, so this step does not block."
