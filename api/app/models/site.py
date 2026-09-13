from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Site(Base):
    __tablename__ = "site"

    site_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. {"start": "22:00", "end": "08:00", "days": ["Mon","Tue","Wed","Thu","Fri"]}
    quiet_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    zones: Mapped[list["Zone"]] = relationship("Zone", back_populates="site", lazy="select")
    devices: Mapped[list["Device"]] = relationship("Device", back_populates="site", lazy="select")
