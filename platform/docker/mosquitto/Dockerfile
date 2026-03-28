FROM eclipse-mosquitto:2

# Data and log directories pre-created so mounted volumes don't need root initialisation
RUN mkdir -p /mosquitto/data /mosquitto/log && \
    chown -R mosquitto:mosquitto /mosquitto

COPY mosquitto.conf /mosquitto/config/mosquitto.conf
COPY docker-entrypoint.sh /usr/local/bin/fleetbits-mosquitto-entrypoint.sh

RUN chmod +x /usr/local/bin/fleetbits-mosquitto-entrypoint.sh

EXPOSE 1883

ENTRYPOINT ["/usr/local/bin/fleetbits-mosquitto-entrypoint.sh"]
CMD ["mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]
