from datetime import datetime

from sqlalchemy import ARRAY, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Device(Base):
    __tablename__ = "device"

    device_id: Mapped[str] = mapped_column(Text, primary_key=True)
    zone_id: Mapped[str | None] = mapped_column(Text, ForeignKey("zone.zone_id"), nullable=True)
    site_id: Mapped[str | None] = mapped_column(Text, ForeignKey("site.site_id"), nullable=True)
    # For mini-shared devices that span multiple zones
    shared_zones: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # Free-text label set at provisioning, e.g. "rpi-puzzle", "mini-pc-orchestrator"
    role: Mapped[str] = mapped_column(Text, nullable=False)
    hostname: Mapped[str] = mapped_column(Text, nullable=False)
    local_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    headscale_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    os_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Current deployment ring (0=lab, 1=canary, 2=prod)
    ring: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SHA-256 hex digest of the long-lived opaque device token (set at first-boot enrollment)
    device_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    zone: Mapped["Zone | None"] = relationship("Zone", back_populates="devices")
    site: Mapped["Site | None"] = relationship("Site", back_populates="devices")
    service_units: Mapped[list["ServiceUnit"]] = relationship(
        "ServiceUnit", back_populates="device", lazy="select", cascade="all, delete-orphan"
    )
    provision_tokens: Mapped[list["ProvisionToken"]] = relationship(
        "ProvisionToken", back_populates="device", lazy="select"
    )


class ServiceUnit(Base):
    """Represents a known systemd unit running on a device."""

    __tablename__ = "service_unit"

    service_id: Mapped[str] = mapped_column(Text, primary_key=True)
    device_id: Mapped[str] = mapped_column(Text, ForeignKey("device.device_id"), nullable=False)
    unit_name: Mapped[str] = mapped_column(Text, nullable=False)
    current_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Last known systemd state: active | inactive | failed | activating | deactivating
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_failure: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    device: Mapped["Device"] = relationship("Device", back_populates="service_units")
