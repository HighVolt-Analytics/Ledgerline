"""Document type class normalization — two coarse values only."""

from __future__ import annotations

from typing import Literal, Protocol

DocumentTypeKlass = Literal["Transactional", "Non-transactional"]

KLASS_TRANSACTIONAL: DocumentTypeKlass = "Transactional"
KLASS_NON_TRANSACTIONAL: DocumentTypeKlass = "Non-transactional"

# Back-compat aliases used during refactor.
KLASS_TRANS_POSTING = KLASS_TRANSACTIONAL
KLASS_NON_TRANS_NON_POSTING = KLASS_NON_TRANSACTIONAL

_LEGACY_TRANSACTIONAL = frozenset(
    {
        "transactional",
        "pre-transactional",
        "trans-posting",
        "trans posting",
    }
)
_LEGACY_NON_TRANSACTIONAL = frozenset(
    {
        "non-transactional",
        "non-trans, non-posting",
        "non-trans-non-posting",
        "supporting",
        "reconciliation",
        "informational",
        "master-data",
        "non-actionable",
        "compliance",
    }
)


def normalize_document_type_klass(raw: str | None) -> DocumentTypeKlass:
    token = (raw or "").strip().lower()
    if token in _LEGACY_TRANSACTIONAL:
        return KLASS_TRANSACTIONAL
    if token in _LEGACY_NON_TRANSACTIONAL:
        return KLASS_NON_TRANSACTIONAL
    return KLASS_NON_TRANSACTIONAL


class _KlassPostingSource(Protocol):
    klass: str
    posting: str
    playbook_profile: str


def is_trans_posting(defn: _KlassPostingSource) -> bool:
    return normalize_document_type_klass(defn.klass) == KLASS_TRANSACTIONAL


def derive_posting_from_klass_and_profile(
    klass: str | None,
    playbook_profile: str | None,
    *,
    existing_posting: str | None = None,
) -> str:
    normalized_klass = normalize_document_type_klass(klass)
    if normalized_klass == KLASS_NON_TRANSACTIONAL:
        return "No"
    profile = (playbook_profile or "").strip().lower()
    if profile == "pre_transactional":
        return "Down-payment"
    existing = (existing_posting or "").strip()
    if existing.lower() == "conditional":
        return "Conditional"
    return "Yes"


def normalize_document_type_identity(defn: _KlassPostingSource) -> tuple[str, str]:
    """Return (klass, posting) after collapsing legacy values."""
    klass = normalize_document_type_klass(defn.klass)
    posting = derive_posting_from_klass_and_profile(
        klass,
        defn.playbook_profile,
        existing_posting=defn.posting,
    )
    return klass, posting
