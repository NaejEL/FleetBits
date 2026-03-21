-- postgresql/init.sql
-- Runs on first container start via docker-entrypoint-initdb.d.
-- Creates the fleet (API) and semaphore (job runner) databases with
-- dedicated users. Passwords come from the Docker Compose environment.

-- ── Fleet API database ────────────────────────────────────────────────────────
CREATE USER fleet WITH PASSWORD :'FLEET_DB_PASSWORD';
CREATE DATABASE fleet OWNER fleet;
GRANT ALL PRIVILEGES ON DATABASE fleet TO fleet;

-- ── Semaphore database ────────────────────────────────────────────────────────
CREATE USER semaphore WITH PASSWORD :'SEMAPHORE_DB_PASSWORD';
CREATE DATABASE semaphore OWNER semaphore;
GRANT ALL PRIVILEGES ON DATABASE semaphore TO semaphore;
