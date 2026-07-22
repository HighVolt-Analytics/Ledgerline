"""Vision-path soft document bundling — invoice-first linkage key resolution.

Priority (first non-empty wins):
  invoice_no → proforma_invoice_no → po_reference → so_reference → org custom field

Used on the vision-understood hold (awaiting_classification). Does not replace
legacy post-classification VR-PB02 PO/SO-first linkage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.services.extraction.extraction_field_values import merge_invoice_extracted_fields
from app.services.purchase.po_reference import is_plausible_po_reference
from app.services.sales.so_reference import is_plausible_so_reference, resolve_so_reference_from_invoice

VisionBundleKind = Literal[
    "invoice_no",
    "proforma_invoice_no",
    "po_reference",
    "so_reference",
    "custom",
    "none",
]

PROFORMA_INVOICE_NO_KEY = "proforma_invoice_no"
VISION_BUNDLE_KIND_KEY = "vision_bundle_kind"
VISION_BUNDLE_KEY_KEY = "vision_bundle_key"

_KIND_LABEL: dict[str, str] = {
    "invoice_no": "Invoice no",
    "proforma_invoice_no": "Proforma invoice no",
    "po_reference": "PO reference",
    "so_reference": "SO reference",
    "custom": "Custom reference",
}


def vision_document_type_label(invoice: Invoice) -> str:
    """AI / printed document name from vision header (no catalogue DT required)."""
    from app.services.invoice.vision_header_extract import derive_canonical_document_type

    fields = invoice.extracted_fields if isinstance(invoice.extracted_fields, dict) else {}
    canonical = str(fields.get("canonical_document_type") or "").strip()
    heading = (invoice.document_heading or "").strip() or str(
        fields.get("document_heading") or ""
    ).strip()
    return derive_canonical_document_type(
        document_heading=heading,
        canonical_document_type=canonical,
    ) or heading


@dataclass(frozen=True)
class VisionBundleLink:
    kind: VisionBundleKind
    key: str | None
    custom_field_key: str | None = None

    @property
    def has_key(self) -> bool:
        return bool(self.key) and self.kind != "none"

    @property
    def linkage_label(self) -> str:
        if not self.has_key or not self.key:
            return "No external linkage key"
        if self.kind == "custom" and self.custom_field_key:
            return f"{self.custom_field_key} · {self.key}"
        prefix = _KIND_LABEL.get(self.kind, self.kind)
        if self.kind == "po_reference":
            return f"Linked on {self.key}"
        if self.kind == "so_reference":
            return f"SO reference · {self.key}"
        return f"{prefix} · {self.key}"


def _extracted_str(invoice: Invoice, key: str) -> str:
    fields = invoice.extracted_fields if isinstance(invoice.extracted_fields, dict) else {}
    val = fields.get(key)
    if isinstance(val, str):
        return val.strip()
    if val is None:
        return ""
    return str(val).strip()


def resolve_vision_bundle_key(
    invoice: Invoice,
    *,
    custom_field_key: str | None = None,
) -> VisionBundleLink:
    """Resolve soft-bundle linkage key for the vision-understood path."""
    invoice_no = (invoice.invoice_no or "").strip()
    if invoice_no:
        return VisionBundleLink(kind="invoice_no", key=invoice_no)

    proforma = _extracted_str(invoice, PROFORMA_INVOICE_NO_KEY)
    if proforma:
        return VisionBundleLink(kind="proforma_invoice_no", key=proforma)

    po_ref = (invoice.po_reference or "").strip()
    if po_ref and is_plausible_po_reference(po_ref):
        return VisionBundleLink(kind="po_reference", key=po_ref)
    if po_ref:
        # Still use non-empty PO even if plausibility heuristics fail — soft bundling.
        return VisionBundleLink(kind="po_reference", key=po_ref)

    so_ref = (resolve_so_reference_from_invoice(invoice) or "").strip()
    if so_ref and is_plausible_so_reference(so_ref):
        return VisionBundleLink(kind="so_reference", key=so_ref)
    if so_ref:
        return VisionBundleLink(kind="so_reference", key=so_ref)

    custom_key = (custom_field_key or "").strip()
    if custom_key:
        custom_val = _extracted_str(invoice, custom_key)
        if not custom_val and custom_key == "other_reference":
            # other_reference may only live in extracted_fields (already checked).
            custom_val = _extracted_str(invoice, "other_reference")
        if custom_val:
            return VisionBundleLink(
                kind="custom",
                key=custom_val,
                custom_field_key=custom_key,
            )

    return VisionBundleLink(kind="none", key=None)


def persist_vision_bundle_snapshot(invoice: Invoice, link: VisionBundleLink) -> None:
    """Write linkage snapshot onto extracted_fields for UI / linked-docs API."""
    patch: dict[str, str] = {
        VISION_BUNDLE_KIND_KEY: link.kind,
    }
    if link.key:
        patch[VISION_BUNDLE_KEY_KEY] = link.key
    if link.kind == "custom" and link.custom_field_key:
        patch["vision_bundle_custom_field"] = link.custom_field_key
    merge_invoice_extracted_fields(invoice, patch)


def read_vision_bundle_snapshot(invoice: Invoice) -> VisionBundleLink | None:
    """Return persisted vision bundle link if present."""
    kind = _extracted_str(invoice, VISION_BUNDLE_KIND_KEY)
    key = _extracted_str(invoice, VISION_BUNDLE_KEY_KEY) or None
    if not kind:
        return None
    if kind == "none" or not key:
        return VisionBundleLink(kind="none", key=None)
    custom_field = _extracted_str(invoice, "vision_bundle_custom_field") or None
    if kind not in {
        "invoice_no",
        "proforma_invoice_no",
        "po_reference",
        "so_reference",
        "custom",
        "none",
    }:
        return None
    return VisionBundleLink(
        kind=kind,  # type: ignore[arg-type]
        key=key,
        custom_field_key=custom_field,
    )


_VISION_SOFT_BUNDLE_EVAL = frozenset(
    {
        "awaiting_classification",
        "vision_vaulted",
        "vision_header_review",
    }
)


def should_use_vision_bundle_linkage(invoice: Invoice) -> bool:
    """True when linked-docs should prefer the vision invoice-first chain."""
    eval_status = (invoice.evaluation_status or "").strip().lower()
    if eval_status in _VISION_SOFT_BUNDLE_EVAL:
        return True
    # Snapshot present and DT not confirmed yet (edge cases / reloads).
    if _extracted_str(invoice, VISION_BUNDLE_KEY_KEY) and not (invoice.document_type_code or "").strip():
        return True
    return False


async def fetch_siblings_for_vision_bundle(
    session: AsyncSession,
    invoice: Invoice,
    link: VisionBundleLink,
) -> list[Invoice]:
    """Find tenant siblings sharing the resolved vision bundle key."""
    if not link.has_key or not link.key:
        return []

    if link.kind == "invoice_no":
        from app.services.dossier.dossier_service import fetch_linked_invoices_by_invoice_no

        return await fetch_linked_invoices_by_invoice_no(session, invoice)

    if link.kind == "po_reference":
        from app.services.dossier.dossier_service import fetch_linked_invoices_by_po_reference

        return await fetch_linked_invoices_by_po_reference(session, invoice)

    if link.kind == "so_reference":
        from app.services.dossier.dossier_service import fetch_linked_invoices_by_so_reference

        return await fetch_linked_invoices_by_so_reference(session, invoice)

    # proforma_invoice_no or custom → match extracted_fields JSON key
    field_key = (
        PROFORMA_INVOICE_NO_KEY
        if link.kind == "proforma_invoice_no"
        else (link.custom_field_key or "").strip()
    )
    if not field_key:
        return []

    token = link.key.strip()
    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == invoice.tenant_id,
                Invoice.id != invoice.id,
                or_(
                    Invoice.extracted_fields[field_key].as_string() == token,
                    func.upper(Invoice.extracted_fields[field_key].as_string()) == token.upper(),
                ),
            )
            .order_by(Invoice.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def apply_vision_bundle_on_hold(
    session: AsyncSession,
    invoice: Invoice,
    *,
    custom_field_key: str | None,
    reprocess_po_siblings,
    reprocess_so_siblings,
) -> VisionBundleLink:
    """
    Resolve + persist vision bundle key and nudge PO/SO siblings when those win.

    ``reprocess_po_siblings`` / ``reprocess_so_siblings`` are callables matching
    pipeline ``_maybe_reprocess_held_commercial_siblings`` signature wrappers.
    """
    link = resolve_vision_bundle_key(invoice, custom_field_key=custom_field_key)
    persist_vision_bundle_snapshot(invoice, link)

    if link.kind == "po_reference" and link.key:
        await reprocess_po_siblings(link.key)
    elif link.kind == "so_reference" and link.key:
        await reprocess_so_siblings(link.key)

    return link
