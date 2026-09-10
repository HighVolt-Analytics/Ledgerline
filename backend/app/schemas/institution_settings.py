"""Institution profile schemas (timezone, locale, country, jurisdiction)."""

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


MobileQuickActionPhotoMode = Literal["compulsory", "optional", "none"]


class MobileQuickActionFieldConfig(BaseModel):
    visible: bool = True
    required: bool = False

    model_config = {"populate_by_name": True}


class MobileQuickActionFieldsConfig(BaseModel):
    """Quick Action form setup.

    ``parent_ledger`` replaces legacy ``expenseType`` (DT Post-to ledger).
    ``amount`` was removed — use DT detail fields (e.g. ``total``) instead.
    DT extraction/required fields are not configured here; mobile reads them
    from the document type (compulsory DT fields stay required on mobile).
    """

    parent_ledger: MobileQuickActionFieldConfig = Field(
        default_factory=lambda: MobileQuickActionFieldConfig(visible=True, required=True),
        alias="parentLedger",
    )
    adjust_advance: MobileQuickActionFieldConfig = Field(
        default_factory=lambda: MobileQuickActionFieldConfig(visible=True, required=False),
        alias="adjustAdvance",
    )
    spent_for: MobileQuickActionFieldConfig = Field(
        default_factory=lambda: MobileQuickActionFieldConfig(visible=True, required=True),
        alias="spentFor",
    )
    remarks: MobileQuickActionFieldConfig = Field(
        default_factory=lambda: MobileQuickActionFieldConfig(visible=True, required=False),
    )

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        # Legacy expenseType → parentLedger when parent ledger missing.
        if "parentLedger" not in out and "parent_ledger" not in out:
            legacy = out.get("expenseType") or out.get("expense_type")
            if legacy is not None:
                out["parentLedger"] = legacy
        out.pop("amount", None)
        out.pop("expenseType", None)
        out.pop("expense_type", None)
        out.pop("detailFields", None)
        out.pop("detail_fields", None)
        return out


class MobileQuickActionItem(BaseModel):
    """One mobile home Quick Action, bound to an org document type."""

    id: str = Field(default_factory=lambda: f"mqa_{uuid4().hex[:10]}")
    document_type_code: str = Field(min_length=1, max_length=16, alias="documentTypeCode")
    label: str = Field(default="", max_length=48)
    enabled: bool = True
    allow_with_doc: bool = Field(default=True, alias="allowWithDoc")
    allow_without_doc: bool = Field(default=True, alias="allowWithoutDoc")
    photo_required: MobileQuickActionPhotoMode = Field(
        default="optional",
        alias="photoRequired",
    )
    fields: MobileQuickActionFieldsConfig = Field(
        default_factory=MobileQuickActionFieldsConfig,
    )

    model_config = {"populate_by_name": True}

    @field_validator("document_type_code")
    @classmethod
    def _norm_code(cls, value: str) -> str:
        token = (value or "").strip().upper()
        if not token:
            raise ValueError("document_type_code is required")
        return token

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        return (value or "").strip()

    @model_validator(mode="after")
    def _at_least_one_path(self) -> "MobileQuickActionItem":
        if not self.allow_with_doc and not self.allow_without_doc:
            object.__setattr__(self, "allow_with_doc", True)
        return self


class MobileQuickActionsSettings(BaseModel):
    """Tenant mobile Quick Actions plan — selected document types + form setup."""

    items: list[MobileQuickActionItem] = Field(default_factory=list)

    @field_validator("items")
    @classmethod
    def _limit_and_dedupe(cls, value: list[MobileQuickActionItem]) -> list[MobileQuickActionItem]:
        if len(value) > 12:
            raise ValueError("At most 12 mobile Quick Actions are allowed")
        seen_ids: set[str] = set()
        seen_codes: set[str] = set()
        out: list[MobileQuickActionItem] = []
        for item in value:
            if item.id in seen_ids or item.document_type_code in seen_codes:
                continue
            seen_ids.add(item.id)
            seen_codes.add(item.document_type_code)
            out.append(item)
        return out


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
    # Fully-loaded labour cost / hour in books currency (dashboard cost-saved KPIs).
    labor_rate_per_hour: float = 45.0
    has_ledger_activity: bool = False
    mobile_quick_actions: MobileQuickActionsSettings = Field(
        default_factory=MobileQuickActionsSettings
    )


class UpdateInstitutionSettingsRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = Field(default=None, min_length=3, max_length=64)
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    custom_bundle_field_key: str | None = Field(default=None, max_length=64)
    labor_rate_per_hour: float | None = Field(default=None, gt=0, le=1_000_000)
    mobile_quick_actions: MobileQuickActionsSettings | None = None
