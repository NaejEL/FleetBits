"""Server-side telemetry identity canonicalization.

Rewrites device identity labels (device_id, site, zone, instance) in inbound
Prometheus remote-write and Loki push payloads before forwarding to the
internal Prometheus / Loki instances.

Prevents a compromised device from poisoning telemetry data with forged
identity values.  The caller has already authenticated the device bearer token;
the canonical values are sourced exclusively from the Device DB record.

Protocol support
----------------
Prometheus   snappy-compressed proto3 WriteRequest (prompb remote-write 0.1.0)
Loki         snappy-compressed proto3 PushRequest  (logproto)
Loki JSON    application/json PushRequest (fallback, accepted by Loki)

Behaviour when dependencies are unavailable
-------------------------------------------
If python-snappy or protobuf are not importable the functions raise
``TelemetryRewriteUnavailable`` so the caller can return HTTP 503 promptly
rather than passing unverified payloads through.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Final

logger = logging.getLogger(__name__)

# Identity labels that are always authoritative from the DB record.
_IDENTITY_LABELS: Final[frozenset[str]] = frozenset({"device_id", "site", "zone", "instance"})


class TelemetryRewriteUnavailable(RuntimeError):
    """Raised when the required binary dependencies are not present."""


# ── Optional binary dependencies (python-snappy + protobuf) ──────────────────

try:
    import snappy as _snappy  # python-snappy

    _SNAPPY_OK = True
except ImportError:  # pragma: no cover
    _SNAPPY_OK = False
    logger.error(
        "telemetry_rewrite: python-snappy not available. "
        "Add python-snappy to requirements.txt. Label rewrite disabled."
    )

try:
    from google.protobuf import descriptor_pb2 as _dpb2
    from google.protobuf import descriptor_pool as _dpool
    from google.protobuf import message_factory as _mfactory

    def _build_proto_pool() -> _dpool.DescriptorPool:
        """Build a minimal proto descriptor pool for Prometheus WriteRequest and Loki PushRequest.

        Only the fields required for identity-label canonicalization are fully
        typed.  Opaque fields (samples, exemplars, log entries) are typed as
        ``repeated bytes`` so they pass through unchanged without needing any
        nested message definitions.
        """
        pool = _dpool.DescriptorPool()
        fdp = _dpb2.FileDescriptorProto()
        fdp.name = "fleetbits_telemetry_rewrite.proto"
        fdp.syntax = "proto3"
        fdp.package = "fb"

        def _msg(name: str, fields: list[tuple]) -> None:
            """Add a message to *fdp*.

            Each tuple is ``(field_number, field_name, field_type, label, type_name)``.
            Protobuf wire-type constants used here:
              9=string  11=message  12=bytes
              1=double  3=int64     5=int32
            Label constants: 1=optional, 3=repeated.
            """
            m = fdp.message_type.add()
            m.name = name
            for num, fname, ftype, flabel, type_name in fields:
                f = m.field.add()
                f.number = num
                f.name = fname
                f.type = ftype
                f.label = flabel
                if type_name:
                    f.type_name = type_name

        # ── Prometheus WriteRequest (prompb 0.1.0) ────────────────────────────

        # Label { string name = 1; string value = 2; }
        _msg("PLabel", [(1, "name", 9, 1, ""), (2, "value", 9, 1, "")])

        # TimeSeries {
        #   repeated Label labels    = 1;   ← rewrite target
        #   repeated bytes  samples   = 2;  ← opaque passthrough
        #   repeated bytes  exemplars = 3;  ← opaque passthrough
        # }
        # Treating samples/exemplars as repeated bytes is safe: protobuf wire
        # type 2 (length-delimited) is shared by both message and bytes fields,
        # so the round-trip is bit-exact.
        _msg(
            "PTimeSeries",
            [
                (1, "labels", 11, 3, ".fb.PLabel"),
                (2, "samples", 12, 3, ""),
                (3, "exemplars", 12, 3, ""),
            ],
        )

        # WriteRequest {
        #   repeated TimeSeries timeseries = 1; ← recurse into
        #   repeated bytes      metadata   = 3; ← opaque passthrough
        # }
        _msg(
            "PWriteRequest",
            [
                (1, "timeseries", 11, 3, ".fb.PTimeSeries"),
                (3, "metadata", 12, 3, ""),
            ],
        )

        # ── Loki PushRequest (logproto) ───────────────────────────────────────

        # StreamAdapter {
        #   string labels  = 1;  ← rewrite target (Prometheus label-set string)
        #   repeated bytes entries = 2;  ← opaque passthrough (EntryAdapter)
        # }
        _msg("LStream", [(1, "labels", 9, 1, ""), (2, "entries", 12, 3, "")])

        # PushRequest { repeated StreamAdapter streams = 1; }
        _msg("LPushRequest", [(1, "streams", 11, 3, ".fb.LStream")])

        pool.Add(fdp)
        return pool

    _proto_pool = _build_proto_pool()

    def _proto_cls(name: str):
        return _mfactory.GetMessageClass(_proto_pool.FindMessageTypeByName(f"fb.{name}"))

    _WriteRequest = _proto_cls("PWriteRequest")
    _LPushRequest = _proto_cls("LPushRequest")

    _PROTO_OK = True

except Exception as _proto_import_err:  # pragma: no cover
    _PROTO_OK = False
    logger.error(
        "telemetry_rewrite: protobuf not available (%s). "
        "Add protobuf>=4.25.0 to requirements.txt. Label rewrite disabled.",
        _proto_import_err,
    )


# ── Prometheus label-set helper (Prometheus-style {k="v",...} in Loki streams)

_LABEL_PAIR_RE: Final = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def _parse_label_set(labels_str: str) -> dict[str, str]:
    """Parse a Prometheus-style label selector string into a dict."""
    return {m.group(1): m.group(2) for m in _LABEL_PAIR_RE.finditer(labels_str)}


def _format_label_set(labels: dict[str, str]) -> str:
    """Serialise a label dict back to {key="value",...} format."""
    return "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"


def _build_canonical(
    device_id: str,
    site_id: str | None,
    zone_id: str | None,
    hostname: str | None,
) -> dict[str, str]:
    """Return the authoritative identity labels for a device."""
    labels: dict[str, str] = {"device_id": device_id}
    if site_id:
        labels["site"] = site_id
    if zone_id:
        labels["zone"] = zone_id
    if hostname:
        labels["instance"] = hostname
    return labels


# ── Public API ────────────────────────────────────────────────────────────────


def rewrite_prometheus_payload(
    body: bytes,
    device_id: str,
    site_id: str | None,
    zone_id: str | None,
    hostname: str | None,
) -> bytes:
    """Decompress, canonicalize identity labels, and recompress a Prometheus WriteRequest.

    Args:
        body:      Raw snappy-compressed proto3 WriteRequest bytes from the device.
        device_id: Authoritative device identifier from the DB record.
        site_id:   Authoritative site from the DB record (may be None).
        zone_id:   Authoritative zone from the DB record (may be None).
        hostname:  Authoritative hostname from the DB record (may be None).

    Returns:
        Rewritten snappy-compressed proto3 WriteRequest bytes ready to forward.

    Raises:
        TelemetryRewriteUnavailable: if python-snappy or protobuf are missing.
        ValueError: if the payload cannot be decompressed or parsed.
    """
    if not _SNAPPY_OK:
        raise TelemetryRewriteUnavailable("python-snappy is not installed")
    if not _PROTO_OK:
        raise TelemetryRewriteUnavailable("protobuf is not installed")

    try:
        decompressed = _snappy.decompress(body)
    except Exception as exc:
        raise ValueError(f"snappy decompress failed: {exc}") from exc

    wr = _WriteRequest()
    try:
        wr.ParseFromString(decompressed)
    except Exception as exc:
        raise ValueError(f"WriteRequest proto parse failed: {exc}") from exc

    canonical = _build_canonical(device_id, site_id, zone_id, hostname)

    for ts in wr.timeseries:
        kept = [lbl for lbl in ts.labels if lbl.name not in _IDENTITY_LABELS]
        del ts.labels[:]
        ts.labels.extend(kept)
        for name, value in canonical.items():
            new_lbl = ts.labels.add()
            new_lbl.name = name
            new_lbl.value = value

    rewritten = wr.SerializeToString()

    try:
        return _snappy.compress(rewritten)
    except Exception as exc:
        raise ValueError(f"snappy compress failed: {exc}") from exc


def rewrite_loki_payload(
    body: bytes,
    content_type: str,
    content_encoding: str,
    device_id: str,
    site_id: str | None,
    zone_id: str | None,
    hostname: str | None,
) -> bytes:
    """Rewrite identity labels in a Loki push payload.

    Supports snappy-compressed proto3 PushRequest (Alloy/Promtail default) and
    JSON PushRequest (Loki legacy / explicit JSON mode).

    Args:
        body:             Raw payload bytes from the device.
        content_type:     Value of the Content-Type request header.
        content_encoding: Value of the Content-Encoding request header.
        device_id:        Authoritative device identifier from the DB record.
        site_id:          Authoritative site (may be None).
        zone_id:          Authoritative zone (may be None).
        hostname:         Authoritative hostname (may be None).

    Returns:
        Rewritten payload bytes in the same encoding format as the input.

    Raises:
        TelemetryRewriteUnavailable: if required dependencies are missing.
        ValueError: if the payload cannot be parsed or format is unrecognised.
    """
    canonical = _build_canonical(device_id, site_id, zone_id, hostname)

    enc_lower = content_encoding.lower()
    ct_lower = content_type.lower()

    if "snappy" in enc_lower:
        return _rewrite_loki_proto(body, canonical)
    if "application/json" in ct_lower:
        return _rewrite_loki_json(body, canonical)

    raise ValueError(
        f"Unsupported Loki payload format: Content-Type={content_type!r} "
        f"Content-Encoding={content_encoding!r}"
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _rewrite_loki_json(body: bytes, canonical: dict[str, str]) -> bytes:
    try:
        push = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Loki JSON parse failed: {exc}") from exc

    for stream in push.get("streams", []):
        existing: dict[str, str] = stream.get("stream", {})
        for key in _IDENTITY_LABELS:
            existing.pop(key, None)
        existing.update(canonical)
        stream["stream"] = existing

    return json.dumps(push, separators=(",", ":")).encode()


def _rewrite_loki_proto(body: bytes, canonical: dict[str, str]) -> bytes:
    if not _SNAPPY_OK:
        raise TelemetryRewriteUnavailable("python-snappy is not installed")
    if not _PROTO_OK:
        raise TelemetryRewriteUnavailable("protobuf is not installed")

    try:
        decompressed = _snappy.decompress(body)
    except Exception as exc:
        raise ValueError(f"snappy decompress failed: {exc}") from exc

    pr = _LPushRequest()
    try:
        pr.ParseFromString(decompressed)
    except Exception as exc:
        raise ValueError(f"LPushRequest proto parse failed: {exc}") from exc

    for stream in pr.streams:
        existing = _parse_label_set(stream.labels)
        for key in _IDENTITY_LABELS:
            existing.pop(key, None)
        existing.update(canonical)
        stream.labels = _format_label_set(existing)

    rewritten = pr.SerializeToString()

    try:
        return _snappy.compress(rewritten)
    except Exception as exc:
        raise ValueError(f"snappy compress failed: {exc}") from exc
