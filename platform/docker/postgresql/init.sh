#!/bin/bash
# postgresql/init.sh
# Runs on first container start via docker-entrypoint-initdb.d.
# Creates the fleet (API) and semaphore (job runner) databases with
# dedicated users. Passwords are read from the container environment.
#
# Required environment variables (set in docker-compose.yml):
#   FLEET_DB_PASSWORD
#   SEMAPHORE_DB_PASSWORD
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    -- Fleet API database
    CREATE USER fleet WITH PASSWORD '${FLEET_DB_PASSWORD}';
    CREATE DATABASE fleet OWNER fleet;
    GRANT ALL PRIVILEGES ON DATABASE fleet TO fleet;

    -- Semaphore (Ansible job runner) database
    CREATE USER semaphore WITH PASSWORD '${SEMAPHORE_DB_PASSWORD}';
    CREATE DATABASE semaphore OWNER semaphore;
    GRANT ALL PRIVILEGES ON DATABASE semaphore TO semaphore;
EOSQL

echo "[init] fleet and semaphore databases created."
