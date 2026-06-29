"""Org AI brief (tenant org_context stored in rule book config)."""

from pydantic import BaseModel, Field

from app.schemas.rule_book_config import OrgContextConfig


class OrgAiBriefResponse(BaseModel):
    legal_name: str = ""
    abn: str = ""
    aliases: list[str] = Field(default_factory=list)
    default_perspective: str = "buyer"
    intake_summary: str = ""
    classification_hints: str = ""

    @classmethod
    def from_org_context(cls, org: OrgContextConfig | None) -> "OrgAiBriefResponse":
        if org is None:
            return cls()
        return cls(
            legal_name=org.legal_name,
            abn=org.abn,
            aliases=list(org.aliases),
            default_perspective=org.default_perspective,
            intake_summary=org.intake_summary,
            classification_hints=org.classification_hints,
        )


class UpdateOrgAiBriefRequest(BaseModel):
    legal_name: str = ""
    abn: str = ""
    aliases: list[str] = Field(default_factory=list)
    default_perspective: str = "buyer"
    intake_summary: str = ""
    classification_hints: str = ""

    def to_org_context(self) -> OrgContextConfig:
        return OrgContextConfig.model_validate(self.model_dump())
