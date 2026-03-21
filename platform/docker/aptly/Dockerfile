# aptly/Dockerfile
# Minimal image: Debian 12 (glibc) + aptly from apt + thin HTTP entrypoint.
# Alpine was avoided because the aptly release binary is glibc-linked.
FROM debian:12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    aptly \
    gnupg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create default aptly directories
RUN mkdir -p /root/.aptly /root/.gnupg && chmod 700 /root/.gnupg

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Bake config into image so no file-mount is needed at runtime.
# If aptly.conf changes, rebuild with --build.
COPY aptly.conf /root/.aptly.conf

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
