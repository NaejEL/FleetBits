FROM postgres:16-alpine

# Bake the init script into the image so it is not bind-mounted from the host.
# The script reads FLEET_DB_PASSWORD and SEMAPHORE_DB_PASSWORD from the
# container environment (set in docker-compose.yml).
COPY init.sh /docker-entrypoint-initdb.d/01-init.sh
RUN chmod +x /docker-entrypoint-initdb.d/01-init.sh
