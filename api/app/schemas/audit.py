import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    action: str
    actor: str
    actor_role: str | None = None
    target: dict
    payload: dict | None = None
    ip_address: str | None = None
    created_at: datetime
