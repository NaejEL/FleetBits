from pydantic import BaseModel, ConfigDict, field_validator


class ZoneBase(BaseModel):
    name: str
    site_id: str
    criticality: str = "standard"
    profile_id: str | None = None

    @field_validator("criticality")
    @classmethod
    def criticality_must_be_valid(cls, v: str) -> str:
        if v not in ("standard", "high"):
            raise ValueError("criticality must be 'standard' or 'high'")
        return v


class ZoneCreate(ZoneBase):
    zone_id: str


class ZoneUpdate(BaseModel):
    name: str | None = None
    criticality: str | None = None
    profile_id: str | None = None


class ZoneRead(ZoneBase):
    model_config = ConfigDict(from_attributes=True)

    zone_id: str
