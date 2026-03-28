FROM grafana/grafana-oss:11.1.0

# Bake provisioning + dashboards into image for reliable local dev
# (avoids host bind-mount issues on some Windows/OneDrive paths).
COPY provisioning /etc/grafana/provisioning
COPY dashboards /var/lib/grafana/dashboards
