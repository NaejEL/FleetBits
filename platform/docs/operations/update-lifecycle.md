# FleetBits Update Lifecycle (`fleetbits-update`)

This runbook documents and validates the standard platform update lifecycle for production hosts.

## What `fleetbits-update` does

By default, the command executes four phases in order:

1. **Pull platform config** (`git pull --ff-only`) in `/opt/fleetbits/FleetBits-platform`
2. **Pull runtime images** for `fleet-api` and `fleet-ui`
3. **Restart only changed pulled services** (`fleet-api` / `fleet-ui` if their digest changed)
4. **Rebuild only impacted local-build services** when config changed (e.g. `prometheus`, `loki`, `alertmanager`, `caddy`, `grafana`, etc.)
5. **Run post-update health check**
6. **Prune dangling image layers**

## Safety guarantees

- Uses `git pull --ff-only` (no merge commits created by updater)
- Validates Docker Compose config before update starts
- Restarts pulled services only when image digests changed
- Rebuilds local services only when matching files changed between Git revisions
- Supports **dry-run** mode to preview actions without changing the host

## Command options

- `fleetbits-update` — full update lifecycle
- `fleetbits-update --config-only` — git/config update only
- `fleetbits-update --images-only` — image pull/restart only
- `fleetbits-update --dry-run` — print actions without applying changes

## Typical production sequence

1. Run a preview:
   - `fleetbits-update --dry-run`
2. Apply full update:
   - `fleetbits-update`
3. Validate:
   - `docker compose --env-file /opt/fleetbits/secrets.env ps`
   - `docker logs --tail 100 fleetbits-api`
   - `docker logs --tail 100 fleetbits-ui`

## Rollback approach

If API/UI behavior regresses after update:

1. In `/opt/fleetbits/FleetBits-platform`, identify previous commit:
   - `git log --oneline -n 5`
2. Roll config back:
   - `git reset --hard <previous_commit>`
3. Re-run updater in image mode to refresh runtime:
   - `fleetbits-update --images-only`

## Operational notes

- If `jq` is unavailable, updater falls back to plain `docker compose ps` output.
- The updater intentionally prunes **dangling** image layers only (safe default).
- For hosted behind-proxy setups, this lifecycle is unchanged; only routing differs.
