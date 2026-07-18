"""Canonical intake facade shared by upload, email, WhatsApp, and Viber."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.audit.audit_service import log_event
from app.services.dossier.document_duplicate_service import ConfidenceTier, MatchKind
from app.services.extraction.pdf_page_text_service import PdfPageTextExtraction
from app.services.ingest.filename_normalize import normalize_attachment_filename
from app.services.ingest.ingest_fanout_service import (
    IngestSourceMetadata,
    IngestUploadResult,
    _ingest_file_with_fanout_core,
)
from app.services.master_data.vendor_resolver import UNKNOWN_SLUG

_ALLOWED_SUFFIXES = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".docx", ".webp"})
_CHANNEL_ALIASES = {
    "upload": "upload",
    "email": "email",
    "mailbox": "email",
    "graph": "email",
    "whatsapp": "whatsapp",
    "viber": "viber",
}


class IntakeValidationError(ValueError):
    """Raised when bytes/filename fail shared intake validation."""


@dataclass(frozen=True)
class IntakeOutcome:
    """Adapter-facing result of canonical intake."""

    result: IngestUploadResult
    action: str
    match_kind: MatchKind | None
    confidence_tier: ConfidenceTier
    review_suggested: bool
    user_message_key: str | None


def canonical_intake_enabled_for(channel: str | None) -> bool:
    """Return True when ``CANONICAL_INTAKE_CHANNELS`` includes this capture source."""
    raw = (get_settings().canonical_intake_channels or "").strip()
    if not raw:
        return False
    enabled = {part.strip().lower() for part in raw.split(",") if part.strip()}
    key = _CHANNEL_ALIASES.get((channel or "upload").strip().lower(), (channel or "").strip().lower())
    return key in enabled


def validate_intake_file(*, filename: str, data: bytes) -> str:
    """Validate empty body and allowed extension. Returns sanitized basename."""
    safe = Path((filename or "").strip() or "attachment.bin").name.strip() or "attachment.bin"
    if not data:
        raise IntakeValidationError("Empty file")
    suffix = Path(safe).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise IntakeValidationError(
            f"Unsupported file type '{suffix or '(none)'}'. Accepted: PDF, JPG, PNG, DOCX, WEBP"
        )
    return safe


def build_ingest_source_metadata(
    *,
    capture_source: str,
    storage_vendor_slug: str = UNKNOWN_SLUG,
    email_sender: str | None = None,
    email_subject: str | None = None,
    email_message_id: str | None = None,
    email_attachment_name: str | None = None,
    connected_mailbox_id: int | None = None,
    viber_connection_id: int | None = None,
    whatsapp_connection_id: int | None = None,
    matched_rule_ids: str | None = None,
    route_target: str | None = None,
) -> IngestSourceMetadata:
    return IngestSourceMetadata(
        storage_vendor_slug=storage_vendor_slug or UNKNOWN_SLUG,
        email_sender=email_sender,
        email_subject=email_subject,
        email_message_id=email_message_id,
        email_attachment_name=email_attachment_name,
        connected_mailbox_id=connected_mailbox_id,
        viber_connection_id=viber_connection_id,
        whatsapp_connection_id=whatsapp_connection_id,
        capture_source=capture_source,
        matched_rule_ids=matched_rule_ids,
        route_target=route_target,
    )


def _user_message_key(action: str, *, review_suggested: bool) -> str | None:
    if action == "skip_in_progress":
        return "duplicate_wait"
    if action in {"shadow_duplicate", "skip_logged"}:
        return "duplicate_known"
    if action == "reingest_rejected":
        return "duplicate_reingest"
    if action in {"allow", "allow_weak"}:
        return "received" if not review_suggested else "received_review"
    return None


async def intake_document(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    tenant_name: str | None,
    filename: str,
    data: bytes,
    source: IngestSourceMetadata,
    purchase_document_type: str | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
    prefetched_extraction: PdfPageTextExtraction | None = None,
    log_upload_event: bool = False,
    skip_validation: bool = False,
) -> IntakeOutcome:
    """
    Shared validate → dedupe → create → audit path for all capture channels.

    Channel adapters own replies, Rule Book capture, and folder moves.
    """
    if not skip_validation:
        filename = validate_intake_file(filename=filename, data=data)
    else:
        filename = Path((filename or "").strip() or "attachment.bin").name.strip() or "attachment.bin"

    if source.email_attachment_name is None:
        source.email_attachment_name = filename

    result = await _ingest_file_with_fanout_core(
        session,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        filename=filename,
        data=data,
        purchase_document_type=purchase_document_type,
        source=source,
        log_upload_event=log_upload_event,
        prefetched_extraction=prefetched_extraction,
        actor_name=actor_name,
        actor_email=actor_email,
    )

    action = result.action
    match_kind = result.match_kind
    confidence_tier = result.confidence_tier
    review_suggested = result.review_suggested

    for invoice_id in result.invoice_ids:
        await log_event(
            session,
            "document_ingested",
            invoice_id=invoice_id,
            detail={
                "capture_source": source.capture_source,
                "filename": filename,
                "normalized_filename": normalize_attachment_filename(
                    source.email_attachment_name or filename
                ),
                "parent_file_hash": result.parent_file_hash,
                "segment_count": result.segment_count,
                "action": action,
                "match_kind": match_kind,
                "confidence_tier": confidence_tier,
                "duplicate_handled": result.duplicate_handled,
                "review_suggested": review_suggested,
            },
            actor_name=actor_name,
            actor_email=actor_email,
        )

    return IntakeOutcome(
        result=result,
        action=action,
        match_kind=match_kind,
        confidence_tier=confidence_tier,
        review_suggested=review_suggested,
        user_message_key=_user_message_key(action, review_suggested=review_suggested),
    )
