# FleetBits-platform tests

Single entry point, from the repository root:

```bash
./scripts/run-tests.sh
```

It runs, in order:

1. `docker compose --env-file secrets.env.example -f docker/docker-compose.yml config -q`,
   then the same command with `-f docker/docker-compose.ci.override.yml` added.
   The override is checked here and nowhere else: it carries Compose's own
   `!reset` tag, so `.pre-commit-config.yaml` can only parse it with
   `check-yaml --unsafe`, which says nothing about the Compose schema.
2. `ansible-playbook --syntax-check playbooks/site.yml`
3. `ansible-lint roles/fleet_agent/ playbooks/collect_diagnostics.yml` — the
   **gate**: the files this repository contributes to the device identity
   contract, which must be lint-clean. They are: 0 violations.
4. `pytest` — the device identity contract conformance suite (23 tests)
5. `ansible-lint playbooks/ roles/` — the **ratchet**: the whole-repository
   report, printed in full, compared against a recorded baseline.
6. `shellcheck --format=gcc` over every `*.sh` in the repository — a second
   **ratchet**, on the same terms. The file list is discovered with `find`, so a
   new script under `scripts/`, `docker/` or the repository root is analysed
   from the day it lands. This is where the `shellcheck` that
   `.github/workflows/platform-tests.yml` installs is actually invoked.

Steps 3 and 5 are deliberately separate. Step 3 is a hard failure on anything
this contract owns. Steps 5 and 6 keep the repository's pre-existing debt
visible, unfiltered and counted, and fail only if the total *grows*; the
baselines live in `ANSIBLE_LINT_DEBT_BASELINE` and `SHELLCHECK_DEBT_BASELINE` in
`scripts/run-tests.sh` and are meant to move down, never up. Nothing is skipped
and nothing is filtered out of either report.

Both ratchets capture the tool's exit status and refuse to read a report they
cannot count as a clean run: "0 violations" and "the tool never ran" must not
look alike, or a failed `docker pull` turns the step green and invites lowering
a baseline against a measurement that never happened.

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

## Pre-existing lint debt (steps 5 and 6)

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

`shellcheck`, last measured on 2026-09-13 with `koalaman/shellcheck:stable`:
**11 findings** (4 `warning`, 7 `note`, 0 `error`), none of them in a script this
work touches:

| Script | Count |
|---|---|
| `scripts/enroll-vps.sh` | 3 |
| `scripts/proxmox/install/fleetbits-install.sh` | 2 |
| `docker/mosquitto/docker-entrypoint.sh` | 2 |
| `dev-setup.sh` | 1 |
| `docker/aptly/entrypoint.sh` | 1 |
| `scripts/proxmox/ct/fleetbits.sh` | 1 |
| `scripts/update.sh` | 1 |

`ansible/.ansible-lint` declares the extra variables that playbooks designed to
be invoked with `-e target_group=...` expect, so the seven
`syntax-check[specific]: 'target_group' is undefined` findings that an
undeclared run used to produce no longer appear. Nothing is suppressed by that
file: it supplies values the linter would otherwise have no way to know about,
and the playbooks still take their real target group from the command line.
