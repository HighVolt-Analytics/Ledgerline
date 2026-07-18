"""Institution profile schemas (timezone, locale, country, jurisdiction)."""

from pydantic import BaseModel, Field


class InstitutionSettingsResponse(BaseModel):
    name: str
    country: str
    timezone: str
    locale: str
    currency: str
    tax_label: str = "Tax"
    statutory_tax_rate: float | None = None
    tax_id_kind: str = "generic"
    tax_id_label: str = "Tax ID"
    bank_routing_label: str = "Bank code"
    field_labels: dict[str, str] = Field(default_factory=dict)
    # Last-resort vision soft-bundle key (extracted_fields name). Empty = skip.
    custom_bundle_field_key: str = ""


class UpdateInstitutionSettingsRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, min_length=3, max_length=64)
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    custom_bundle_field_key: str | None = Field(default=None, max_length=64)
