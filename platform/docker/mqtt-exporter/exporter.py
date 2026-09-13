#!/usr/bin/env python3
"""
mqtt-exporter — subscribe to Mosquitto $SYS statistics and expose them as
Prometheus metrics on :9234/metrics.

$SYS topics exposed:
  $SYS/broker/clients/connected     → mqtt_connected_clients (gauge)
  $SYS/broker/clients/disconnected  → mqtt_disconnected_clients (gauge)
  $SYS/broker/clients/total         → mqtt_clients_total (gauge)
  $SYS/broker/messages/received     → mqtt_messages_received_total (counter)
  $SYS/broker/messages/sent         → mqtt_messages_sent_total (counter)
  $SYS/broker/subscriptions/count   → mqtt_subscriptions_total (gauge)
  $SYS/broker/uptime                → mqtt_broker_uptime_seconds (gauge)
  $SYS/broker/heap/current          → mqtt_heap_bytes (gauge)
"""

import os
import threading
import time

import paho.mqtt.client as mqtt
from prometheus_client import Gauge, Counter, start_http_server

MQTT_HOST    = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT    = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9234"))
RECONNECT_S  = 5  # seconds between reconnect attempts

# ── Prometheus metrics ────────────────────────────────────────────────────────
g_connected     = Gauge("mqtt_connected_clients",    "Currently connected MQTT clients")
g_disconnected  = Gauge("mqtt_disconnected_clients", "Currently disconnected MQTT clients")
g_total         = Gauge("mqtt_clients_total",        "Total MQTT clients (ever connected)")
g_subscriptions = Gauge("mqtt_subscriptions_total",  "Active MQTT subscriptions")
g_uptime        = Gauge("mqtt_broker_uptime_seconds","Mosquitto broker uptime in seconds")
g_heap          = Gauge("mqtt_heap_bytes",           "Mosquitto broker heap usage in bytes")
c_recv          = Counter("mqtt_messages_received_total", "Messages received by broker")
c_sent          = Counter("mqtt_messages_sent_total",     "Messages sent by broker")

# Track counter state to avoid double-incrementing (Paho delivers each retained message once)
_counter_state: dict = {}


def _update_counter(counter, value: int) -> None:
    """Increment a Prometheus Counter to match the absolute value from $SYS."""
    key = id(counter)
    prev = _counter_state.get(key, 0)
    delta = value - prev
    if delta > 0:
        counter.inc(delta)
    elif delta < -1_000:
        # Broker restarted — reset tracking (counter stays monotonic in Prometheus)
        _counter_state[key] = value
        return
    _counter_state[key] = value


def on_connect(client, userdata, flags, rc, properties=None):  # noqa: ANN001
    if rc == 0:
        print(f"[mqtt-exporter] Connected to {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe("$SYS/#")
    else:
        print(f"[mqtt-exporter] Connection refused, rc={rc}")


def on_message(client, userdata, msg):  # noqa: ANN001
    topic   = msg.topic
    payload = msg.payload.decode(errors="replace").strip()

    try:
        value = int(float(payload))
    except ValueError:
        # Some $SYS topics publish strings like "1 day, 2:03:04" — parse seconds
        if "day" in payload:
            try:
                parts = payload.split(",")
                days = int(parts[0].split()[0])
                h, m, s = (int(x) for x in parts[1].strip().split(":"))
                value = days * 86400 + h * 3600 + m * 60 + s
            except Exception:
                return
        else:
            return

    mapping = {
        "$SYS/broker/clients/connected":    lambda v: g_connected.set(v),
        "$SYS/broker/clients/disconnected": lambda v: g_disconnected.set(v),
        "$SYS/broker/clients/total":        lambda v: g_total.set(v),
        "$SYS/broker/subscriptions/count":  lambda v: g_subscriptions.set(v),
        "$SYS/broker/uptime":               lambda v: g_uptime.set(v),
        "$SYS/broker/heap/current":         lambda v: g_heap.set(v),
        "$SYS/broker/messages/received":    lambda v: _update_counter(c_recv, v),
        "$SYS/broker/messages/sent":        lambda v: _update_counter(c_sent, v),
    }

    handler = mapping.get(topic)
    if handler:
        handler(value)


def run_client() -> None:
    """Run the MQTT client with automatic reconnect."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            print(f"[mqtt-exporter] Connection error: {exc} — retrying in {RECONNECT_S}s")
            time.sleep(RECONNECT_S)


if __name__ == "__main__":
    print(f"[mqtt-exporter] Starting metrics server on :{METRICS_PORT}")
    start_http_server(METRICS_PORT)
    # Run MQTT client in the main thread (blocking)
    run_client()
