"""Rule book evaluation API schemas."""

from pydantic import BaseModel, Field

from app.schemas.rule_book_config import RuleBookRulesPayload


class RuleBookEvaluateRequest(BaseModel):
    """Evaluate saved or draft config against org documents."""

    config: RuleBookRulesPayload | None = Field(
        default=None,
        description="Draft rules from the UI; uses saved org config when omitted.",
    )
    invoice_ids: list[int] | None = Field(
        default=None,
        description="Optional invoice IDs; newest org invoices when omitted.",
    )
    limit: int = Field(default=50, ge=1, le=200)


class RuleBookEvalDocument(BaseModel):
    id: str
    doc_number: str
    invoice_no: str
    vendor: str
    primary_account: str
    document_type_code: str | None = None


class RuleBookEvalEmailRule(BaseModel):
    id: str
    name: str


class RuleBookEvalVendorMatch(BaseModel):
    vendor_id: str
    vendor_name: str
    confidence: float


class RuleBookEvalCategoryRule(BaseModel):
    label: str
    kind: str


class RuleBookEvalRow(BaseModel):
    document: RuleBookEvalDocument
    email_rule: RuleBookEvalEmailRule | None = None
    email_rule_disabled: RuleBookEvalEmailRule | None = None
    vendor_match: RuleBookEvalVendorMatch | None = None
    category_rule: RuleBookEvalCategoryRule | None = None
    category_rule_disabled: RuleBookEvalCategoryRule | None = None
    auto_coded: bool


class RuleBookEvaluateResponse(BaseModel):
    source: str
    rows: list[RuleBookEvalRow]
