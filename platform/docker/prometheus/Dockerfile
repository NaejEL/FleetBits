FROM prom/prometheus:v3.15.1

# Bake config into the image — avoids Windows WSL2 bind-mount issues
# with paths containing spaces. To apply config changes: docker compose up --build prometheus
RUN mkdir -p /etc/prometheus/rules
COPY prometheus.yml /etc/prometheus/prometheus.yml
COPY rules/           /etc/prometheus/rules/
