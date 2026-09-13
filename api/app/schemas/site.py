from pydantic import BaseModel, ConfigDict


class SiteBase(BaseModel):
    name: str
    timezone: str | None = None
    quiet_hours: dict | None = None


class SiteCreate(SiteBase):
    site_id: str


class SiteUpdate(BaseModel):
    name: str | None = None
    timezone: str | None = None
    quiet_hours: dict | None = None


class SiteRead(SiteBase):
    model_config = ConfigDict(from_attributes=True)

    site_id: str
