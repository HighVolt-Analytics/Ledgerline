"""Field registry API schemas."""

from pydantic import BaseModel, Field


class RegistryFieldResponse(BaseModel):
    key: str
    label: str
    data_type: str = "string"
    category: str = "general"
    posting_critical: bool = False
    grounding_required: bool = True
    synonyms: list[str] = Field(default_factory=list)


class RegistryFieldsResponse(BaseModel):
    version: str = "1"
    use_field_registry: bool = False
    fields: list[RegistryFieldResponse] = Field(default_factory=list)
