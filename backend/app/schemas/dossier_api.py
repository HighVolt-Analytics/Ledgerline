"""Dossier list query parameters."""

from pydantic import BaseModel, ConfigDict, Field


class DossierListRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(1, ge=1)
    page_size: int = Field(12, ge=1, le=100)
    document_type_code: str | None = None
    q: str | None = Field(None, description="Search vendor, ref, PO, document type")
