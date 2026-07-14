"""Tenant organisation context for perspective inference and LLM prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models.tenant import Tenant
from app.schemas.rule_book_config import AiClassificationConfig, OrgContextConfig, RuleBookConfigPayload
from app.tenant_settings import DEFAULT_COUNTRY, tenant_country

_VALID_PERSPECTIVES = frozenset({"buyer", "seller", "mixed"})


def normalize_org_perspective(value: object) -> str:
    token = str(value or "buyer").strip().lower()
    if token in _VALID_PERSPECTIVES:
        return token
    return "buyer"


@dataclass(frozen=True)
class OrgContext:
    legal_name: str = ""
    abn: str = ""
    aliases: list[str] = field(default_factory=list)
    default_perspective: str = "buyer"
    intake_summary: str = ""
    classification_hints: str = ""
    country: str = DEFAULT_COUNTRY


def _org_context_from_mapping(block: dict[str, Any], *, country: str = DEFAULT_COUNTRY) -> OrgContext:
    aliases_raw = block.get("aliases") or []
    aliases = [str(a).strip() for a in aliases_raw if str(a).strip()]
    return OrgContext(
        legal_name=str(block.get("legal_name") or block.get("legalName") or "").strip(),
        abn=str(block.get("abn") or "").strip(),
        aliases=aliases,
        default_perspective=normalize_org_perspective(
            block.get("default_perspective") or block.get("defaultPerspective")
        ),
        intake_summary=str(
            block.get("intake_summary") or block.get("intakeSummary") or ""
        ).strip(),
        classification_hints=str(
            block.get("classification_hints") or block.get("classificationHints") or ""
        ).strip(),
        country=country,
    )


def _settings_dict(tenant: Tenant | None) -> dict[str, Any]:
    raw = tenant.settings_json if tenant else None
    return raw if isinstance(raw, dict) else {}


def org_context_from_settings(settings: dict[str, Any], *, country: str | None = None) -> OrgContext:
    code = (country or DEFAULT_COUNTRY).strip().upper() or DEFAULT_COUNTRY
    block = settings.get("org_context")
    if not isinstance(block, dict):
        return OrgContext(country=code)
    return _org_context_from_mapping(block, country=code)


def org_context_for_tenant(tenant: Tenant | None) -> OrgContext:
    country = tenant_country(tenant)
    ctx = org_context_from_settings(_settings_dict(tenant), country=country)
    if ctx.legal_name:
        return ctx
    if tenant and tenant.name:
        return OrgContext(
            legal_name=tenant.name.strip(),
            default_perspective=ctx.default_perspective,
            intake_summary=ctx.intake_summary,
            classification_hints=ctx.classification_hints,
            abn=ctx.abn,
            aliases=list(ctx.aliases),
            country=country,
        )
    return ctx


def ai_classification_from_config(config: RuleBookConfigPayload | None) -> AiClassificationConfig:
    if config is None or config.ai_classification is None:
        return AiClassificationConfig()
    return config.ai_classification


def org_context_from_config(config: RuleBookConfigPayload | None, tenant: Tenant | None) -> OrgContext:
    country = tenant_country(tenant)
    if config is not None and config.org_context is not None:
        oc = config.org_context
        return OrgContext(
            legal_name=oc.legal_name.strip(),
            abn=oc.abn.strip(),
            aliases=list(oc.aliases),
            default_perspective=normalize_org_perspective(oc.default_perspective),
            intake_summary=oc.intake_summary.strip(),
            classification_hints=oc.classification_hints.strip(),
            country=country,
        )
    return org_context_for_tenant(tenant)


def _normalize_abn(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


_LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:pty\.?\s*ltd\.?|pvt\.?\s*ltd\.?|limited|ltd\.?|inc\.?|corp\.?|"
    r"corporation|company|co\.?|llc|gmbh|plc)\b",
    re.I,
)


def _canon_party_name(value: str) -> str:
    """Lowercase alphanumeric tokens with legal suffixes stripped for matching."""
    from app.services.master_data.vendor_detection import normalize_match_text

    cleaned = _LEGAL_SUFFIX_RE.sub(" ", value or "")
    return normalize_match_text(cleaned)


def party_matches_tenant(name: str, abn: str, org: OrgContext) -> bool:
    """True when the party is the tenant org (tax id, fuzzy name, or alias)."""
    if org.abn and abn:
        if _normalize_abn(org.abn) == _normalize_abn(abn):
            return True

    token = _canon_party_name(name)
    if len(token) < 4:
        return False

    from app.services.master_data.vendor_detection import NAME_FUZZY_MIN_RATIO, levenshtein_ratio

    candidates = [org.legal_name, *org.aliases]
    for entry in candidates:
        hay = _canon_party_name(entry)
        if len(hay) < 4:
            continue
        if token == hay:
            return True
        # Bidirectional containment only for longer anchors (avoids "Co"/"Pty" FPs).
        if len(hay) >= 8 and (hay in token or token in hay):
            return True
        if len(token) >= 8 and (token in hay or hay in token):
            return True
        if levenshtein_ratio(token, hay) >= NAME_FUZZY_MIN_RATIO:
            return True
    return False


def infer_perspective(
    *,
    org: OrgContext,
    seller_name: str,
    seller_abn: str,
    buyer_name: str,
    buyer_abn: str,
    llm_perspective: str,
) -> str:
    seller_match = party_matches_tenant(seller_name, seller_abn, org)
    buyer_match = party_matches_tenant(buyer_name, buyer_abn, org)
    # Both sides look like us → ambiguous (do not guess).
    if seller_match and buyer_match:
        return "unknown"
    if seller_match and not buyer_match:
        return "sales"
    if buyer_match and not seller_match:
        return "purchase"
    if llm_perspective in {"purchase", "sales"}:
        return llm_perspective
    if org.default_perspective == "buyer":
        return "purchase"
    if org.default_perspective == "seller":
        return "sales"
    return "unknown"
