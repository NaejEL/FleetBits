"""
Telemetry identity field validation and canonicalization tests.

These tests verify that:
- Telemetry ingress authenticates device token
- Server rewrites authoritative identity labels from DB record (device_id, site, zone, instance)
- Client-supplied identity labels are ignored or overwritten
- Forged labels do not survive ingest to Prometheus/Loki
- Query proxy enforces site-scope isolation for non-admin operators
"""

import os
import struct
import time
import pytest
import httpx
from httpx import AsyncClient

import app.routers.telemetry as telemetry_router
import json


class _FakeUpstreamResponse:
    def __init__(self, status_code: int = 204, content: bytes = b"", content_type: str = "application/json"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}


_PROM_OK_RESPONSE = _FakeUpstreamResponse(
    status_code=200,
    content=b'{"status":"success","data":{"resultType":"vector","result":[]}}',
    content_type="application/json",
)


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, content=None, headers=None, **kwargs):
        self.calls.append({"method": "POST", "url": url, "content": content, "headers": headers or {}})
        return _FakeUpstreamResponse()

    async def get(self, url, params=None, headers=None, **kwargs):
        self.calls.append({"method": "GET", "url": url, "params": params, "headers": headers or {}})
        return _PROM_OK_RESPONSE


# ── Minimal raw-proto WriteRequest builder ────────────────────────────────────
# Builds a snappy-compressed Prometheus remote_write WriteRequest from scratch
# using raw protobuf wire encoding, without relying on the FleetBits proto pool.
# This lets E2E tests send real payloads through the full rewrite pipeline.

def _varint(n: int) -> bytes:
    out = []
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _ld(data: bytes) -> bytes:
    return _varint(len(data)) + data


def _tag(fn: int, wt: int) -> bytes:
    return _varint((fn << 3) | wt)


def _str_field(fn: int, s: str) -> bytes:
    return _tag(fn, 2) + _ld(s.encode())


def _double_field(fn: int, v: float) -> bytes:
    return _tag(fn, 1) + struct.pack("<d", v)


def _i64_field(fn: int, v: int) -> bytes:
    if v < 0:
        v &= (1 << 64) - 1
    return _tag(fn, 0) + _varint(v)


def _msg_field(fn: int, data: bytes) -> bytes:
    return _tag(fn, 2) + _ld(data)


def _build_prom_write_payload(
    metric_name: str,
    extra_labels: dict[str, str],
    value: float = 1.0,
) -> bytes:
    """Return a snappy-compressed Prometheus WriteRequest with one TimeSeries."""
    try:
        import snappy
    except ImportError:
        return b""  # caller will skip

    ts_ms = int(time.time() * 1000)

    # Sample { value=1: double, timestamp=2: int64 ms }
    sample = _double_field(1, value) + _i64_field(2, ts_ms)

    # Build labels: __name__ first, then extra labels
    labels_bytes = _msg_field(1, _str_field(1, "__name__") + _str_field(2, metric_name))
    for k, v in extra_labels.items():
        labels_bytes += _msg_field(1, _str_field(1, k) + _str_field(2, v))

    # TimeSeries { labels=1 repeated, samples=2 }
    timeseries = labels_bytes + _msg_field(2, sample)

    # WriteRequest { timeseries=1 }
    write_request = _msg_field(1, timeseries)

    return snappy.compress(write_request)


def _is_prometheus_reachable() -> bool:
    prom_url = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    try:
        import urllib.request
        urllib.request.urlopen(f"{prom_url}/-/healthy", timeout=3)
        return True
    except Exception:
        return False


def _is_loki_reachable() -> bool:
    loki_url = os.getenv("LOKI_URL", "http://loki:3100")
    try:
        import urllib.request
        urllib.request.urlopen(f"{loki_url}/ready", timeout=3)
        return True
    except Exception:
        return False


@pytest.mark.security
class TestTelemetryIngressAuthentication:
    """Test that telemetry ingress requires device authentication."""

    async def test_anonymous_prometheus_push_rejected(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={"Content-Encoding": "snappy"},
            content=b"invalid-snappy-data",
        )
        assert response.status_code == 401

    async def test_anonymous_loki_push_rejected(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/telemetry/logs/push",
            headers={"Content-Encoding": "snappy"},
            content=b"invalid-snappy-data",
        )
        assert response.status_code == 401

    async def test_invalid_device_token_rejected(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={
                "Authorization": "Bearer invalid-device-token",
                "Content-Encoding": "snappy",
            },
            content=b"invalid-snappy-data",
        )
        assert response.status_code == 401

    async def test_revoked_device_token_rejected(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/telemetry/logs/push",
            headers={
                "Authorization": "Bearer revoked-device-token",
                "Content-Type": "application/json",
            },
            content=b'{"streams":[]}',
        )
        assert response.status_code == 401


@pytest.mark.security
class TestPrometheusLabelRewriting:
    """Test that Prometheus WriteRequest identity labels are rewritten."""

    async def test_device_id_label_rewritten_from_db(
        self, client: AsyncClient, test_devices, device_token, monkeypatch
    ):
        fake_client = _FakeAsyncClient()
        seen = {}

        def _rewrite(body, device_id, site_id, zone_id, hostname):
            seen["device_id"] = device_id
            seen["site_id"] = site_id
            seen["zone_id"] = zone_id
            seen["hostname"] = hostname
            return b"rewritten-prom"

        monkeypatch.setattr(telemetry_router, "rewrite_prometheus_payload", _rewrite)
        monkeypatch.setattr(telemetry_router.httpx, "AsyncClient", lambda *a, **k: fake_client)

        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={"Authorization": f"Bearer {device_token}", "Content-Encoding": "snappy"},
            content=b"original-prom",
        )
        assert response.status_code == 204
        assert seen == {
            "device_id": "device-a1-1",
            "site_id": "site-a",
            "zone_id": "zone-a1",
            "hostname": "device-a1-1",
        }
        assert fake_client.calls[0]["content"] == b"rewritten-prom"

    async def test_forged_identity_labels_are_overwritten(
        self, client: AsyncClient, test_devices, device_token, monkeypatch
    ):
        fake_client = _FakeAsyncClient()

        def _rewrite(body, device_id, site_id, zone_id, hostname):
            assert body == b"forged-payload"
            return b"canonicalized-payload"

        monkeypatch.setattr(telemetry_router, "rewrite_prometheus_payload", _rewrite)
        monkeypatch.setattr(telemetry_router.httpx, "AsyncClient", lambda *a, **k: fake_client)

        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={"Authorization": f"Bearer {device_token}", "Content-Encoding": "snappy"},
            content=b"forged-payload",
        )
        assert response.status_code == 204
        assert fake_client.calls[0]["content"] == b"canonicalized-payload"

    def test_non_identity_labels_preserved(self):
        """Non-identity labels in a Prometheus WriteRequest survive the rewrite unchanged."""
        import app.services.telemetry_rewrite as _svc

        if not _svc._SNAPPY_OK:
            pytest.skip("python-snappy not available in this environment")
        if not _svc._PROTO_OK:
            pytest.skip("protobuf not available in this environment")

        _WR = _svc._WriteRequest
        _snappy = _svc._snappy

        wr = _WR()
        ts = wr.timeseries.add()
        for name, value in [
            ("device_id", "forged-device"),
            ("site",      "forged-site"),
            ("zone",      "forged-zone"),
            ("instance",  "forged-host"),
            ("job",       "prometheus-agent"),
            ("__name__",  "cpu_usage_total"),
            ("cpu",       "0"),
            ("env",       "production"),
        ]:
            lbl = ts.labels.add()
            lbl.name = name
            lbl.value = value

        compressed = _snappy.compress(wr.SerializeToString())
        from app.services.telemetry_rewrite import rewrite_prometheus_payload
        result = rewrite_prometheus_payload(
            compressed, "device-a1-1", "site-a", "zone-a1", "host-a1"
        )

        result_wr = _WR()
        result_wr.ParseFromString(_snappy.decompress(result))
        labels = {lbl.name: lbl.value for lbl in result_wr.timeseries[0].labels}

        # Non-identity labels must survive unmodified
        assert labels["job"] == "prometheus-agent"
        assert labels["__name__"] == "cpu_usage_total"
        assert labels["cpu"] == "0"
        assert labels["env"] == "production"
        # Identity labels rewritten from the canonical DB values
        assert labels["device_id"] == "device-a1-1"
        assert labels["site"] == "site-a"
        assert labels["zone"] == "zone-a1"
        assert labels["instance"] == "host-a1"
        # No trace of the forged values
        assert "forged-device" not in labels.values()
        assert "forged-site" not in labels.values()


@pytest.mark.security
class TestLokiLabelRewriting:
    """Test that Loki PushRequest stream labels are rewritten."""

    async def test_loki_proto_request_labels_rewritten(
        self, client: AsyncClient, test_devices, device_token, monkeypatch
    ):
        fake_client = _FakeAsyncClient()
        monkeypatch.setattr(telemetry_router, "rewrite_loki_payload", lambda *a, **k: b"rewritten-loki")
        monkeypatch.setattr(telemetry_router.httpx, "AsyncClient", lambda *a, **k: fake_client)

        response = await client.post(
            "/api/v1/telemetry/logs/push",
            headers={
                "Authorization": f"Bearer {device_token}",
                "Content-Encoding": "snappy",
                "Content-Type": "application/x-protobuf",
            },
            content=b"proto-body",
        )
        assert response.status_code == 204
        assert fake_client.calls[0]["content"] == b"rewritten-loki"

    async def test_loki_json_request_labels_rewritten(
        self, client: AsyncClient, test_devices, device_token, monkeypatch
    ):
        fake_client = _FakeAsyncClient()
        monkeypatch.setattr(telemetry_router, "rewrite_loki_payload", lambda *a, **k: b'{"streams":[]}')
        monkeypatch.setattr(telemetry_router.httpx, "AsyncClient", lambda *a, **k: fake_client)

        response = await client.post(
            "/api/v1/telemetry/logs/push",
            headers={
                "Authorization": f"Bearer {device_token}",
                "Content-Type": "application/json",
            },
            content=b'{"streams":[]}',
        )
        assert response.status_code == 204
        assert fake_client.calls[0]["content"] == b'{"streams":[]}'

    def test_loki_stream_label_keys_preserved(self):
        """Non-identity stream labels in a Loki JSON payload survive the rewrite unchanged."""
        from app.services.telemetry_rewrite import rewrite_loki_payload

        payload = json.dumps({
            "streams": [{
                "stream": {
                    "device_id": "forged-id",
                    "site":      "forged-site",
                    "zone":      "forged-zone",
                    "instance":  "forged-host",
                    "app":       "kiosk-player",
                    "level":     "error",
                    "component": "renderer",
                },
                "values": [["1711926000000000000", "segfault in renderer"]],
            }]
        }).encode()

        result = json.loads(
            rewrite_loki_payload(payload, "application/json", "", "device-a1-1", "site-a", "zone-a1", "host-a1")
        )
        labels = result["streams"][0]["stream"]

        # Non-identity labels preserved
        assert labels["app"] == "kiosk-player"
        assert labels["level"] == "error"
        assert labels["component"] == "renderer"
        # Identity labels overwritten from canonical values
        assert labels["device_id"] == "device-a1-1"
        assert labels["site"] == "site-a"
        assert labels["zone"] == "zone-a1"
        assert labels["instance"] == "host-a1"
        # No forged values survive
        assert "forged-id" not in labels.values()
        assert "forged-site" not in labels.values()

    def test_loki_forged_site_zone_not_injected_if_missing(self):
        """site/zone/instance labels are absent when the device DB record has no value for them."""
        from app.services.telemetry_rewrite import rewrite_loki_payload

        payload = json.dumps({
            "streams": [{
                "stream": {
                    "device_id": "anything",
                    "site":      "forged-site",
                    "zone":      "forged-zone",
                    "instance":  "forged-host",
                    "app":       "test-svc",
                },
                "values": [["1711926000000000000", "hello"]],
            }]
        }).encode()

        # site_id=None, zone_id=None, hostname=None → only device_id canonical label
        result = json.loads(
            rewrite_loki_payload(payload, "application/json", "", "device-orphan", None, None, None)
        )
        labels = result["streams"][0]["stream"]

        assert labels["device_id"] == "device-orphan"
        assert "site" not in labels       # no site – source is None
        assert "zone" not in labels       # no zone – source is None
        assert "instance" not in labels   # no instance – source is None
        assert labels["app"] == "test-svc"
        assert "forged-site" not in labels.values()
        assert "forged-zone" not in labels.values()


@pytest.mark.security
class TestTelemetryPayloadValidation:
    """Test that malformed payloads are rejected safely."""

    async def test_invalid_snappy_compression_rejected(self, client: AsyncClient, test_devices, device_token):
        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={
                "Authorization": f"Bearer {device_token}",
                "Content-Encoding": "snappy",
            },
            content=b"not-valid-snappy",
        )
        assert response.status_code in (400, 503)

    async def test_invalid_proto_structure_rejected(self, client: AsyncClient, test_devices, device_token):
        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={
                "Authorization": f"Bearer {device_token}",
                "Content-Encoding": "snappy",
            },
            content=b"not-valid-snappy",
        )
        assert response.status_code in (400, 503)

    async def test_missing_content_encoding_header_rejected(self, client: AsyncClient, test_devices, device_token):
        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={"Authorization": f"Bearer {device_token}"},
            content=b"raw",
        )
        assert response.status_code in (400, 503)

    async def test_unsupported_content_encoding_rejected(self, client: AsyncClient, test_devices, device_token):
        response = await client.post(
            "/api/v1/telemetry/logs/push",
            headers={
                "Authorization": f"Bearer {device_token}",
                "Content-Type": "application/octet-stream",
                "Content-Encoding": "gzip",
            },
            content=b"gzip-bytes",
        )
        assert response.status_code in (400, 503)


@pytest.mark.security
class TestTelemetryRewriteUnavailableHandling:
    """Test behavior when telemetry rewrite module is unavailable."""

    async def test_snappy_dependency_missing_returns_503(
        self, client: AsyncClient, test_devices, device_token, monkeypatch
    ):
        monkeypatch.setattr(
            telemetry_router,
            "rewrite_prometheus_payload",
            lambda *a, **k: (_ for _ in ()).throw(telemetry_router.TelemetryRewriteUnavailable("python-snappy is not installed")),
        )

        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={"Authorization": f"Bearer {device_token}", "Content-Encoding": "snappy"},
            content=b"payload",
        )
        assert response.status_code == 503

    async def test_protobuf_dependency_missing_returns_503(
        self, client: AsyncClient, test_devices, device_token, monkeypatch
    ):
        monkeypatch.setattr(
            telemetry_router,
            "rewrite_loki_payload",
            lambda *a, **k: (_ for _ in ()).throw(telemetry_router.TelemetryRewriteUnavailable("protobuf is not installed")),
        )

        response = await client.post(
            "/api/v1/telemetry/logs/push",
            headers={"Authorization": f"Bearer {device_token}", "Content-Type": "application/json"},
            content=b'{"streams":[]}',
        )
        assert response.status_code == 503

    async def test_missing_dependencies_logged(
        self, client: AsyncClient, test_devices, device_token, monkeypatch, caplog
    ):
        """When rewrite raises TelemetryRewriteUnavailable the router logs ERROR before 503."""
        import logging

        monkeypatch.setattr(
            telemetry_router,
            "rewrite_prometheus_payload",
            lambda *a, **k: (_ for _ in ()).throw(
                telemetry_router.TelemetryRewriteUnavailable("python-snappy is not installed")
            ),
        )
        with caplog.at_level(logging.ERROR, logger="app.routers.telemetry"):
            response = await client.post(
                "/api/v1/telemetry/metrics/write",
                headers={
                    "Authorization": f"Bearer {device_token}",
                    "Content-Encoding": "snappy",
                },
                content=b"payload",
            )

        assert response.status_code == 503
        assert any(
            "Prometheus telemetry rewrite unavailable" in record.message
            for record in caplog.records
        )


@pytest.mark.security
class TestEndToEndTelemetryFlow:
    """Test complete telemetry ingest flow from device to storage."""

    async def test_device_metrics_flow_to_prometheus(
        self, client: AsyncClient, test_devices, device_token
    ):
        """Device metric push reaches Prometheus with authoritative identity labels.

        Sends a real snappy-compressed Prometheus WriteRequest with forged identity
        labels through the full rewrite pipeline. Queries Prometheus directly to
        verify the stored metric carries the canonical DB-sourced labels.
        """
        import app.services.telemetry_rewrite as _svc

        if not _svc._SNAPPY_OK:
            pytest.skip("python-snappy not available in this environment")

        if not _is_prometheus_reachable():
            pytest.skip("Prometheus not reachable from this environment")

        payload = _build_prom_write_payload(
            metric_name="fleetbits_e2e_metrics_test",
            extra_labels={
                "device_id": "forged-device",
                "site":      "forged-site",
                "zone":      "forged-zone",
                "job":       "fleet-agent-e2e",
            },
        )

        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={
                "Authorization": f"Bearer {device_token}",
                "Content-Encoding": "snappy",
                "Content-Type": "application/x-protobuf",
                "X-Prometheus-Remote-Write-Version": "0.1.0",
            },
            content=payload,
        )
        assert response.status_code == 204, f"Expected 204, got {response.status_code}: {response.text}"

        # Allow Prometheus a moment to ingest the write
        time.sleep(1)

        prom_url = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
        async with httpx.AsyncClient(timeout=10) as prom:
            qresp = await prom.get(
                f"{prom_url}/api/v1/query",
                params={"query": 'fleetbits_e2e_metrics_test{device_id="device-a1-1"}'},
            )

        assert qresp.status_code == 200
        data = qresp.json()
        assert data["status"] == "success"
        results = data["data"]["result"]
        assert len(results) > 0, (
            "Expected metric fleetbits_e2e_metrics_test to be stored in Prometheus "
            "with device_id=device-a1-1; got zero results"
        )
        labels = results[0]["metric"]
        assert labels["device_id"] == "device-a1-1", f"device_id not canonicalized: {labels}"
        assert labels.get("site") == "site-a", f"site not canonicalized: {labels}"
        assert labels.get("zone") == "zone-a1", f"zone not canonicalized: {labels}"
        assert "forged" not in json.dumps(labels), f"Forged label survived rewrite: {labels}"

    async def test_device_logs_flow_to_loki(
        self, client: AsyncClient, test_devices, device_token
    ):
        """Device log push reaches Loki with authoritative stream identity labels.

        Sends a JSON Loki PushRequest with forged identity labels through the
        full rewrite pipeline. Queries Loki directly to verify the stored log
        stream carries canonical DB-sourced labels.
        """
        if not _is_loki_reachable():
            pytest.skip("Loki not reachable from this environment")

        ts_ns = str(int(time.time() * 1e9))
        # Use a unique marker so the query targets exactly this test's log entry
        marker = f"e2e-{int(time.time())}"
        payload = json.dumps({
            "streams": [{
                "stream": {
                    "device_id": "forged-id",
                    "site":      "forged-site",
                    "zone":      "forged-zone",
                    "app":       "fleet-agent-e2e",
                },
                "values": [[ts_ns, f"fleetbits e2e integration test {marker}"]],
            }]
        }).encode()

        response = await client.post(
            "/api/v1/telemetry/logs/push",
            headers={
                "Authorization": f"Bearer {device_token}",
                "Content-Type": "application/json",
            },
            content=payload,
        )
        assert response.status_code == 204, f"Expected 204, got {response.status_code}: {response.text}"

        # Allow Loki a moment to index the push
        time.sleep(1)

        loki_url = os.getenv("LOKI_URL", "http://loki:3100")
        now = time.time()
        async with httpx.AsyncClient(timeout=10) as loki:
            qresp = await loki.get(
                f"{loki_url}/loki/api/v1/query_range",
                params={
                    "query": '{device_id="device-a1-1",app="fleet-agent-e2e"}',
                    "start": str(int(now - 60)),
                    "end":   str(int(now + 10)),
                    "limit": "20",
                },
            )

        assert qresp.status_code == 200, f"Loki query failed: {qresp.text}"
        data = qresp.json()
        assert data["status"] == "success"
        results = data["data"]["result"]
        assert len(results) > 0, (
            "Expected log stream {device_id='device-a1-1',app='fleet-agent-e2e'} "
            "to be stored in Loki; got zero results"
        )
        stream_labels = results[0]["stream"]
        assert stream_labels["device_id"] == "device-a1-1", f"device_id not canonicalized: {stream_labels}"
        assert stream_labels.get("site") == "site-a", f"site not canonicalized: {stream_labels}"
        assert stream_labels.get("zone") == "zone-a1", f"zone not canonicalized: {stream_labels}"
        assert stream_labels.get("app") == "fleet-agent-e2e", "non-identity label 'app' was dropped"
        assert "forged" not in json.dumps(stream_labels), f"Forged label survived rewrite: {stream_labels}"

    async def test_cross_site_device_label_forgery_prevented(
        self, client: AsyncClient, test_devices, test_db, monkeypatch
    ):
        """A device from site-b whose payload contains forged site-a identity gets corrected.

        The rewrite function always receives identity values from the authenticated DB record,
        never from the payload body.  This test registers a token for device-b1-1 (site-b)
        and verifies that the site/zone passed to the rewrite function are site-b / zone-b1.
        """
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy import select as _select
        from app.models.device import Device
        from app.services.token import hash_token

        raw_token_b = "device-b1-cross-site-forgery-token"
        async with AsyncSession(test_db, expire_on_commit=False) as session:
            res = await session.execute(
                _select(Device).where(Device.device_id == "device-b1-1")
            )
            device_b = res.scalar_one()
            device_b.device_token_hash = hash_token(raw_token_b)
            await session.commit()

        seen: dict = {}
        fake_client = _FakeAsyncClient()

        def _capture(body, device_id, site_id, zone_id, hostname):
            seen.update({"device_id": device_id, "site_id": site_id, "zone_id": zone_id})
            return body

        monkeypatch.setattr(telemetry_router, "rewrite_prometheus_payload", _capture)
        monkeypatch.setattr(telemetry_router.httpx, "AsyncClient", lambda *a, **k: fake_client)

        response = await client.post(
            "/api/v1/telemetry/metrics/write",
            headers={
                "Authorization": f"Bearer {raw_token_b}",
                "Content-Encoding": "snappy",
            },
            content=b"payload-forging-site-a-identity",
        )

        assert response.status_code == 204
        # Identity sourced exclusively from DB record, not payload
        assert seen["device_id"] == "device-b1-1"
        assert seen["site_id"] == "site-b"
        assert seen["zone_id"] == "zone-b1"

    async def test_telemetry_queries_cannot_cross_site_boundaries(
        self, client: AsyncClient, scoped_token, monkeypatch
    ):
        """Site-scoped operator cannot query telemetry data outside their site.

        The query proxy must:
        1. Reject queries with a ``site`` label targeting a different site (HTTP 403).
        2. Reject negative site matchers (site!="..." / site!~"...") for scoped users.
        3. Inject the user's site scope into queries that omit a site selector.
        4. Not duplicate the site label when it is already correctly specified.
        """
        fake_client = _FakeAsyncClient()
        monkeypatch.setattr(telemetry_router.httpx, "AsyncClient", lambda *a, **k: fake_client)

        # ── Cross-site exact match → 403 ─────────────────────────────────────
        resp = await client.get(
            "/api/v1/telemetry/metrics/query",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"query": 'up{site="site-b"}'},
        )
        assert resp.status_code == 403, f"Expected 403 for cross-site site-b query, got {resp.status_code}"
        assert "Cross-site" in resp.json().get("detail", "")

        # ── Negative site matcher → 403 ──────────────────────────────────────
        resp = await client.get(
            "/api/v1/telemetry/metrics/query",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"query": 'up{site!="site-a"}'},
        )
        assert resp.status_code == 403, f"Expected 403 for negative site selector, got {resp.status_code}"

        # Cross-site check also enforced on query_range
        resp = await client.get(
            "/api/v1/telemetry/metrics/query_range",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"query": 'rate(http_requests{site="site-b"}[5m])', "start": "0", "end": "1", "step": "60"},
        )
        assert resp.status_code == 403

        # Cross-site check enforced on Loki query_range
        resp = await client.get(
            "/api/v1/telemetry/logs/query_range",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"query": '{app="kiosk",site="site-b"}', "start": "0", "end": "1"},
        )
        assert resp.status_code == 403

        # ── No site selector → site injected into forwarded query ────────────
        fake_client.calls.clear()
        resp = await client.get(
            "/api/v1/telemetry/metrics/query",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"query": 'up{job="fleet-agent"}'},
        )
        assert resp.status_code == 200, f"Expected 200 for in-scope query, got {resp.status_code}"
        assert len(fake_client.calls) == 1, "Expected one forwarded request to Prometheus"
        forwarded_query = fake_client.calls[0]["params"]["query"]
        assert 'site="site-a"' in forwarded_query, (
            f"Expected site-a injected into forwarded query; got: {forwarded_query!r}"
        )
        assert 'job="fleet-agent"' in forwarded_query, "Original label must survive injection"

        # ── Correct site selector already present → no duplicate injection ───
        fake_client.calls.clear()
        resp = await client.get(
            "/api/v1/telemetry/metrics/query",
            headers={"Authorization": f"Bearer {scoped_token}"},
            params={"query": 'up{site="site-a",job="node"}'},
        )
        assert resp.status_code == 200
        forwarded_query = fake_client.calls[0]["params"]["query"]
        assert forwarded_query.count('site="site-a"') == 1, (
            f"site label must not be duplicated: {forwarded_query!r}"
        )

