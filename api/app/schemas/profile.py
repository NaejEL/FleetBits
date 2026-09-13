from pydantic import BaseModel, ConfigDict


class ProfileBase(BaseModel):
    name: str
    baseline_stack: dict


class ProfileCreate(ProfileBase):
    profile_id: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    baseline_stack: dict | None = None


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    profile_id: str
