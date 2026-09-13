from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Profile(Base):
    __tablename__ = "profile"

    profile_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Component list with default versions — see §5.2 for shape
    baseline_stack: Mapped[dict] = mapped_column(JSONB, nullable=False)

    zones: Mapped[list["Zone"]] = relationship("Zone", back_populates="profile", lazy="select")
    devices: Mapped[list["Device"]] = relationship("Device", back_populates="profile", lazy="select")
