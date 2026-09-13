# FleetBits-platform tests

Single entry point, from the repository root:

```bash
./scripts/run-tests.sh
```

It runs, in order:

1. `docker compose --env-file secrets.env.example -f docker/docker-compose.yml config -q`
2. `ansible-playbook --syntax-check playbooks/site.yml`
3. `ansible-lint roles/fleet_agent/ playbooks/collect_diagnostics.yml` — the
   **gate**: the files this repository contributes to the device identity
   contract, which must be lint-clean. They are: 0 violations.
4. `pytest` — the device identity contract conformance suite (12 tests)
5. `ansible-lint playbooks/ roles/` — the **ratchet**: the whole-repository
   report, printed in full, compared against a recorded baseline.

Steps 3 and 5 are deliberately separate. Step 3 is a hard failure on anything
this contract owns. Step 5 keeps the repository's pre-existing lint debt
visible, unfiltered and counted, and fails only if the total *grows*; the
baseline lives in `ANSIBLE_LINT_DEBT_BASELINE` in `scripts/run-tests.sh` and is
meant to move down, never up. Nothing is skipped and nothing is filtered out of
the report.

Ansible tooling is executed from its container images when `ansible-playbook`
and `ansible-lint` are not on `$PATH`. Nothing here ever touches a real
inventory: syntax and lint only, with a throw-away vault password file so the
parser stops at `ansible.cfg`'s `vault_password_file` setting without ever
decrypting anything.

The Python suite uses a virtualenv kept **outside** the repository
(`../.venv-platform`), because this repository's `.gitignore` does not ignore
`.venv/`.

The contract tests read `FleetBits-agent/usr/lib/fleet-agent/identity-lib.sh`
and `FleetBits-agent/container-entrypoint.sh` from the sibling checkout: the
device identity contract spans three repositories and a desynchronised one must
fail a test rather than a device.

## Pre-existing lint debt (step 5)

Last measured on 2026-09-13 with `pipelinecomponents/ansible-lint:latest`: **34
violations**, all of them outside the gate of step 3 and all of them predating
the device identity contract work:

| Rule | Count |
|---|---|
| `var-naming[no-role-prefix]` | 10 |
| `yaml[colons]` | 8 |
| `name[casing]` | 7 |
| `command-instead-of-module` | 4 |
| `ignore-errors` | 1 |
| `name[template]` | 1 |
| `no-changed-when` | 1 |
| `risky-file-permissions` | 1 |
| `yaml[line-length]` | 1 |

They live in `roles/app_config`, `roles/deploy_artifact`,
`roles/headscale_enroll`, `roles/systemd_exporter`, `roles/systemd_hardening`,
`playbooks/bootstrap_device.yml`, `playbooks/bootstrap_observability.yml` and
`playbooks/restart_service.yml`.

`ansible/.ansible-lint` declares the extra variables that playbooks designed to
be invoked with `-e target_group=...` expect, so the seven
`syntax-check[specific]: 'target_group' is undefined` findings that an
undeclared run used to produce no longer appear. Nothing is suppressed by that
file: it supplies values the linter would otherwise have no way to know about,
and the playbooks still take their real target group from the command line.
