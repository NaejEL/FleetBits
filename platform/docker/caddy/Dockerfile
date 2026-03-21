FROM caddy:2.8-alpine

# Bake both Caddyfiles into the image.
# Production default uses Caddyfile; the dev override changes the command to
# point at Caddyfile.dev (see docker-compose.override.yml).
RUN mkdir -p /etc/caddy
COPY Caddyfile     /etc/caddy/Caddyfile
COPY Caddyfile.dev /etc/caddy/Caddyfile.dev
