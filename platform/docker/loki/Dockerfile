FROM grafana/loki:3.7.9

# No RUN here, deliberately: since 3.7 the upstream image is distroless and has
# no /bin/sh, so `RUN mkdir -p /etc/loki` fails the build with
#   exec: "/bin/sh": stat /bin/sh: no such file or directory
# COPY creates the destination directory on its own, which is all the mkdir did.
COPY loki.yml /etc/loki/loki.yml
