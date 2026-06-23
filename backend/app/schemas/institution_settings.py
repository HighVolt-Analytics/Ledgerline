"""Institution profile schemas (timezone, locale, country)."""

from pydantic import BaseModel, Field


class InstitutionSettingsResponse(BaseModel):
    country: str
    timezone: str
    locale: str


class UpdateInstitutionSettingsRequest(BaseModel):
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, min_length=3, max_length=64)
    locale: str | None = Field(default=None, min_length=2, max_length=16)
