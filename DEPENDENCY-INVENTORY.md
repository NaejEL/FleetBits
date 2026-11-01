# Dependency inventory

Every file in this repository that pins a third-party version, and whether
anything watches it for updates.

The point of this document is the second column. A pinned version that nobody
watches does not stay still — it rots, and it rots silently: no tool reports
it, no build turns red, and the gap only becomes visible the day someone
upgrades it by hand. Listing those files is the difference between a deliberate
freeze and an oversight nobody noticed.

Scope note: this table is about *version pins*, not about every file dependabot
touches. Where a file is watched, the authority is `.github/dependabot.yml`;
`platform/tests/test_dependabot_coverage.py` fails the platform suite when this
table and that file disagree about which manifests exist and which are watched.

## Python requirements

| File | Watched | Detail |
|---|---|---|
| `api/requirements.txt` | Yes — dependabot `pip` `/api` | Grouped as `api-python`, every update level in one pull request. Its header documents a coupled set (`fastapi`, `starlette`, `prometheus-fastapi-instrumentator`, `python-multipart`, `pytest`) that cannot move apart without failing the suite; the group is what keeps it moving as one block. Validated on a pull request by `api-tests.yml`, `security-regression-stack.yml` and the `pip-audit` / `bandit` jobs of `security-baseline.yml`. **Known defect, left alone on purpose** — see "Test dependencies inside a runtime manifest" below. |
| `ui/requirements.txt` | Yes — dependabot `pip` `/ui` | Grouped as `ui-python`. **Runtime only**: `flask`, `requests`, `python-dotenv`. This is the one file `ui/Dockerfile` installs, so it defines the dependency surface of the published `fleet-ui` image. Validated by `ui-tests.yml` (the smoke test: the Flask application still builds), by `build-fleet-ui.yml` (the image builds, so the install resolves) and by the `pip-audit` / `bandit` jobs of `security-baseline.yml`. |
| `ui/requirements-dev.txt` | Yes — dependabot `pip` `/ui` | Same entry and same `ui-python` group: a dependabot `directory:` resolves every `requirements*.txt` it holds. Test dependencies only (`pytest`), installed by `ui-tests.yml` and by developers, never by `ui/Dockerfile`. |
| `platform/docker/mqtt-exporter/requirements.txt` | Yes — dependabot `pip` `/platform/docker/mqtt-exporter` | Grouped as `mqtt-exporter-python`. `paho-mqtt` and `prometheus-client`. **No test exercises a bump**: no workflow builds or runs the mqtt-exporter image. A reviewer reads the release notes; nothing else does. |

### Test dependencies inside a runtime manifest

`ui/` keeps its test runner out of `requirements.txt` (see the two rows above).
`api/` does **not**: `api/requirements.txt` carries `pytest` and its test-only
companions, and `api/Dockerfile` installs that file, so the published
`fleet-api` image ships the test runner and its transitive dependencies, and
`pip-audit` gates `api/` on packages that never run in production.

This is a real defect and it is **deliberately not fixed here**. The header of
`api/requirements.txt` documents a coupled set — `fastapi`, `starlette`,
`prometheus-fastapi-instrumentator`, `python-multipart` and `pytest` — whose
versions must move together or the suite fails. Splitting the file splits that
set across two manifests and two dependabot resolutions, which is exactly the
drift the coupling note exists to prevent. Fixing it properly means re-deriving
the compatible version set first; that is its own piece of work, not a side
effect of this one.

## Container base images — `Dockerfile`

All watched by a dependabot `docker` entry on their own directory, one entry
per directory, one group each. What differs is what validates a bump.

| File | Base image | Watched | What exercises a bump |
|---|---|---|---|
| `api/Dockerfile` | `python:3.12-slim` | Yes — `/api` | `security-regression-stack.yml` builds and runs this image on every pull request touching `api/`, `platform/` or `agent/`. Real validation. |
| `ui/Dockerfile` | `python:3.12-slim` | Yes — `/ui` | `build-fleet-ui.yml` builds the image on a pull request touching `ui/`. The image is built, never started: `fleet-ui` is not part of the integration stack. |
| `agent/Dockerfile.container` | `ubuntu:24.04` | Yes — `/agent` | **Nothing on a pull request.** The job building this image is guarded by `if: startsWith(github.ref, 'refs/tags/v')`. `agent-tests.yml` runs shellcheck and bats, which neither build nor start the image. A base image bump — `24.04` is an LTS, most successors are not — is exercised for the first time at `docker compose --profile agent up`. |
| `platform/docker/alertmanager/Dockerfile` | `prom/alertmanager:v0.27.0` | Yes — `/platform/docker/alertmanager` | `platform/scripts/run-tests.sh` validates the composition, never builds this image. |
| `platform/docker/aptly/Dockerfile` | `debian:12-slim` | Yes — `/platform/docker/aptly` | Built and started by `security-regression-stack.yml` (service `aptly-api`). Real validation. |
| `platform/docker/caddy/Dockerfile` | `caddy:2.8-alpine` | Yes — `/platform/docker/caddy` | Built and started by `security-regression-stack.yml`. Real validation. |
| `platform/docker/edge-sim/Dockerfile` | `python:3.12-alpine` | Yes — `/platform/docker/edge-sim` | Built and started by `security-regression-stack.yml`. Real validation. |
| `platform/docker/grafana/Dockerfile` | `grafana/grafana-oss:11.1.0` | Yes — `/platform/docker/grafana` | Composition validation only. |
| `platform/docker/headscale/Dockerfile` | `headscale/headscale:0.23` | Yes — `/platform/docker/headscale` | Composition validation only. |
| `platform/docker/loki/Dockerfile` | `grafana/loki:3.0.0` | Yes — `/platform/docker/loki` | Built and started by `security-regression-stack.yml`. Real validation. |
| `platform/docker/mosquitto/Dockerfile` | `eclipse-mosquitto:2` | Yes — `/platform/docker/mosquitto` | Composition validation only. A floating major tag: the digest moves under a pin that does not. |
| `platform/docker/mqtt-exporter/Dockerfile` | `python:3.12-slim` | Yes — `/platform/docker/mqtt-exporter` | Composition validation only. |
| `platform/docker/postgresql/Dockerfile` | `postgres:16-alpine` | Yes — `/platform/docker/postgresql` | Built and started by `security-regression-stack.yml`. Real validation. |
| `platform/docker/prometheus/Dockerfile` | `prom/prometheus:v2.52.0` | Yes — `/platform/docker/prometheus` | Built and started by `security-regression-stack.yml`. Real validation. |

Eleven `Dockerfile` live under `platform/docker/*/`, one per service directory,
each with a single `FROM`.

## Version pins inside a `Dockerfile`

| Pin | File | Watched | Reason |
|---|---|---|---|
| `ARG ALLOY_VERSION=1.8.2` | `agent/Dockerfile.container` | **No** | Not a `FROM`: dependabot's `docker` ecosystem reads base images, not build arguments. Grafana Alloy is downloaded by version from a release URL. Upgrading is a manual step; nothing reports a new Alloy release. |

## Images pinned in `platform/docker/docker-compose.yml`

**None of these is watched.** Dependabot's `docker-compose` ecosystem is in
beta, and this repository does not enable it. These four pins move only when a
human moves them.

| Line | Image | Watched | Reason |
|---|---|---|---|
| 73 | `grafana/grafana-oss:11.1.0` | **No** | `docker-compose` ecosystem in beta. Note that the same version is also pinned in `platform/docker/grafana/Dockerfile`, which *is* watched — so the two can drift apart, and a dependabot pull request on the `Dockerfile` will not touch this line. |
| 102 | `semaphoreui/semaphore:v2.10.22` | **No** | `docker-compose` ecosystem in beta. Pinned nowhere else in the repository. |
| 233 | `prom/node-exporter:v1.8.2` | **No** | `docker-compose` ecosystem in beta. Pinned nowhere else in the repository. |
| 247 | `gcr.io/cadvisor/cadvisor:v0.49.2` | **No** | `docker-compose` ecosystem in beta. Pinned nowhere else in the repository. |

Line 319, `fleetbits/vps-device:latest`, is this project's own agent image, not
a third-party pin; lines 132 and 166 resolve to variables set in `secrets.env`.

## Pre-commit hook revisions

Out of dependabot's reach by nature: `rev:` pins are git references in a
`.pre-commit-config.yaml`, an ecosystem dependabot does not support. They are
updated with `pre-commit autoupdate`, run by hand. The four files hold the same
revisions, and nothing enforces that they stay aligned.

| File | Watched | Pinned revisions |
|---|---|---|
| `api/.pre-commit-config.yaml` | **No** | `pre-commit-hooks` v5.0.0, `gitleaks` v8.18.4, `bandit` 1.7.8, `ruff-pre-commit` v0.4.4, `actionlint` v1.7.4 |
| `ui/.pre-commit-config.yaml` | **No** | `pre-commit-hooks` v5.0.0, `gitleaks` v8.18.4, `bandit` 1.7.8, `ruff-pre-commit` v0.4.4, `actionlint` v1.7.4 |
| `agent/.pre-commit-config.yaml` | **No** | `pre-commit-hooks` v5.0.0, `gitleaks` v8.18.4, `actionlint` v1.7.4 |
| `platform/.pre-commit-config.yaml` | **No** | `pre-commit-hooks` v5.0.0, `gitleaks` v8.18.4, `actionlint` v1.7.4 |

## Tool images of the test harnesses

Out of dependabot's reach: these are shell variables, not a manifest. They are
pinned because two of the steps they feed compare a *count* against a recorded
baseline — a ratchet is only a ratchet if every environment counts with the same
analyser, so a floating tag turns an upstream release into a red build with no
change in this repository.

| Variable | File | Value | Watched | Reason |
|---|---|---|---|---|
| `SHELLCHECK_IMAGE` | `agent/scripts/run-tests.sh` | `koalaman/shellcheck:v0.11.0` | **No** | Shell variable. Deliberately the *same* version as the platform harness: two analysers over overlapping shell would report two different sets of findings for one tree. |
| `BATS_IMAGE` | `agent/scripts/run-tests.sh` | `bats/bats:1.14.0` | **No** | Shell variable. Pinned so the bats suite runs the same runner everywhere. |
| `ANSIBLE_IMAGE` | `platform/scripts/run-tests.sh` | `willhallonline/ansible:latest` | **No** | Shell variable. Deliberately left floating: it only runs `ansible-playbook --syntax-check`, a pass/fail with no counted baseline. Checking syntax against a current parser is the point. |
| `ANSIBLE_LINT_IMAGE` | `platform/scripts/run-tests.sh` | `pipelinecomponents/ansible-lint:0.79.38` | **No** | Shell variable. Pinned: the repository-wide `ansible-lint` step is a ratchet against `ANSIBLE_LINT_DEBT_BASELINE`. |
| `SHELLCHECK_IMAGE` | `platform/scripts/run-tests.sh` | `koalaman/shellcheck:v0.11.0` | **No** | Shell variable. Pinned: the repository-wide shellcheck step is a ratchet against `SHELLCHECK_DEBT_BASELINE`. |

## Tools installed by workflows

| Install | Workflow | Watched | Reason |
|---|---|---|---|
| `pip install pip-audit bandit` | `security-baseline.yml` | **No** | Unpinned install inside a `run:` step, not a manifest: dependabot has nothing to read. `pip-audit` and `bandit` therefore float, and a new rule in either can turn a required check red with no change in this repository. |
| `pip install ansible-core ansible-lint` | `platform-tests.yml` | **No** | Same: unpinned install in a `run:` step. Note that this makes the CI `ansible-lint` a *different* version from `ANSIBLE_LINT_IMAGE` above, so the ratchet baseline is only guaranteed reproducible locally. |
| `apt-get install shellcheck bats` | `agent-tests.yml` | **No** | Distribution packages, whose versions follow the runner image. `agent/scripts/run-tests.sh` prefers a tool found on `PATH`, so CI runs the distribution version rather than the pinned image. |

## GitHub Actions

Watched by the dependabot `github-actions` entry on `/`. Minor and patch bumps
arrive grouped; each major arrives on its own, because a major is a behaviour
change that has to be read by itself.

One pairing constraint is recorded in the workflow that carries it:
`actions/upload-artifact` and `actions/download-artifact` in
`.github/workflows/build-fleet-agent.yml` must stay on matching majors, and the
path that uses them runs **only on a tag push** — no pull request would reveal a
mismatch, so it would surface at the next release. Both comments in that file
say so; move the two together.

**Known blind spot on that pair.** The `publish-dev` job of
`build-fleet-agent.yml` is guarded by `if: startsWith(github.ref, 'refs/tags/v')`.
Nothing in continuous integration executes it: no pull request, no push to
`main`. `upload-artifact` was moved from `v4` to `v7` there to match the `v8` of
`download-artifact` — the two upstream releases are published minutes apart and
cite each other as the matched pair — but that pairing is asserted from release
notes, and the three-major jump itself is exercised by nothing. Neither the
pairing nor the jump is validated by a pull request; both are first exercised at
the next tag push. Read this as the exception to "bumps are tested, not
arbitrated on their number": here the number is all there is, and a release is
the first test. Anyone cutting the next tag should expect this job to be the one
that breaks, and should read it before pushing the tag.
