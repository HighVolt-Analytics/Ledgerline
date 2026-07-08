"""Setup checklist schemas."""

from pydantic import BaseModel, Field


class SetupChecklistItem(BaseModel):
    id: str
    label: str
    group: str
    done: bool
    route: str
    optional: bool = False


class SetupChecklistStateResponse(BaseModel):
    complete: bool
    show: bool
    progress: int = Field(ge=0, le=100)
    items: list[SetupChecklistItem] = Field(default_factory=list)
