"""Report-only probable duplicate vendors in vendor_masters (Layer 3)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor_master import VendorMasterRecord
from app.services.master_data.vendor_detection import levenshtein_ratio
from app.services.master_data.vendor_name_utils import normalize_vendor_name


@dataclass(frozen=True)
class ProbableVendorDuplicate:
    left_id: int
    right_id: int
    left_master_id: str
    right_master_id: str
    left_name: str
    right_name: str
    reasons: tuple[str, ...]
    score: float


def _norm_name(name: str) -> str:
    cleaned = normalize_vendor_name(name) or name
    return re.sub(r"\s+", " ", cleaned.strip().lower())


def _norm_abn(value: str | None) -> str:
    return re.sub(r"\D", "", (value or "").strip())


def _norm_address(addr: dict[str, Any] | None) -> str:
    if not isinstance(addr, dict):
        return ""
    parts = [
        str(addr.get(k) or "").strip().lower()
        for k in ("street", "suburb", "postcode", "country", "line1", "city", "state")
    ]
    joined = " ".join(p for p in parts if p)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", joined)).strip()


async def find_probable_duplicate_vendors(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name_similarity_threshold: float = 0.88,
) -> list[ProbableVendorDuplicate]:
    """Pairwise scan of vendor_masters for likely duplicates. Report-only — no merge."""
    rows = (
        await session.execute(
            select(VendorMasterRecord)
            .where(VendorMasterRecord.tenant_id == tenant_id)
            .order_by(VendorMasterRecord.id.asc())
        )
    ).scalars().all()

    pairs: list[ProbableVendorDuplicate] = []
    for i, left in enumerate(rows):
        left_name = _norm_name(left.name)
        left_abn = _norm_abn(left.abn)
        left_addr = _norm_address(left.billing_address if isinstance(left.billing_address, dict) else None)
        for right in rows[i + 1 :]:
            reasons: list[str] = []
            score = 0.0
            right_name = _norm_name(right.name)
            right_abn = _norm_abn(right.abn)
            right_addr = _norm_address(
                right.billing_address if isinstance(right.billing_address, dict) else None
            )

            if left_abn and right_abn and left_abn == right_abn:
                reasons.append("shared_abn")
                score = max(score, 1.0)

            if left_addr and right_addr and left_addr == right_addr:
                reasons.append("shared_address")
                score = max(score, 0.95)

            if left_name and right_name:
                ratio = levenshtein_ratio(left_name, right_name)
                if ratio >= name_similarity_threshold or left_name == right_name:
                    reasons.append("name_similarity")
                    score = max(score, ratio)

            if not reasons:
                continue
            pairs.append(
                ProbableVendorDuplicate(
                    left_id=left.id,
                    right_id=right.id,
                    left_master_id=left.master_id,
                    right_master_id=right.master_id,
                    left_name=left.name,
                    right_name=right.name,
                    reasons=tuple(reasons),
                    score=round(score, 4),
                )
            )
    pairs.sort(key=lambda p: p.score, reverse=True)
    return pairs
