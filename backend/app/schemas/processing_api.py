"""Processing API request bodies."""

from pydantic import BaseModel, ConfigDict


class TriggerProcessingRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    mailbox_id: int | None = None
