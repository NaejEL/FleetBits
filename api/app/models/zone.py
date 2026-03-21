from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Zone(Base):
    __tablename__ = "zone"

    zone_id: Mapped[str] = mapped_column(Text, primary_key=True)
    site_id: Mapped[str] = mapped_column(Text, ForeignKey("site.site_id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # 'standard' | 'high'
    criticality: Mapped[str] = mapped_column(Text, nullable=False, default="standard")
    profile_id: Mapped[str | None] = mapped_column(Text, ForeignKey("profile.profile_id"), nullable=True)

    site: Mapped["Site"] = relationship("Site", back_populates="zones")
    profile: Mapped["Profile | None"] = relationship("Profile", back_populates="zones")
    devices: Mapped[list["Device"]] = relationship("Device", back_populates="zone", lazy="select")
