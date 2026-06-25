"""Cluster uploaded samples by document similarity."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.document_type_sample_types import ParsedDocumentSample


@dataclass(frozen=True)
class SampleCluster:
    cluster_id: int
    filenames: tuple[str, ...]
    heading: str | None
    layout_hint: str | None


def _normalize_heading(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def _extraction_keys(sample: ParsedDocumentSample) -> set[str]:
    keys: set[str] = set()
    parsed = sample.parsed
    if (parsed.vendor or sample.invoice.vendor or "").strip():
        keys.add("vendor")
    if (parsed.invoice_no or sample.invoice.invoice_no or "").strip():
        keys.add("invoice_no")
    if (parsed.po_reference or sample.invoice.po_reference or "").strip():
        keys.add("po_reference")
    if parsed.total is not None or sample.invoice.total is not None:
        keys.add("total")
    if (parsed.document_heading or "").strip():
        keys.add("document_heading")
    if parsed.line_items:
        keys.add("line_items")
    return keys


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _samples_similar(left: ParsedDocumentSample, right: ParsedDocumentSample) -> bool:
    left_heading = _normalize_heading(left.parsed.document_heading)
    right_heading = _normalize_heading(right.parsed.document_heading)
    if left_heading and right_heading and left_heading == right_heading:
        return True
    left_hint = (left.layout_hint or left.parsed.raw_fields.get("layout_hint") or "").strip().lower()
    right_hint = (right.layout_hint or right.parsed.raw_fields.get("layout_hint") or "").strip().lower()
    if left_hint and right_hint and left_hint == right_hint:
        return _jaccard(_extraction_keys(left), _extraction_keys(right)) >= 0.4
    if _jaccard(_extraction_keys(left), _extraction_keys(right)) >= 0.6:
        return True
    return False


def cluster_document_samples(
    samples: list[ParsedDocumentSample],
) -> list[SampleCluster]:
    if not samples:
        return []
    clusters: list[list[ParsedDocumentSample]] = []
    for sample in samples:
        placed = False
        for group in clusters:
            if any(_samples_similar(sample, member) for member in group):
                group.append(sample)
                placed = True
                break
        if not placed:
            clusters.append([sample])

    output: list[SampleCluster] = []
    for index, group in enumerate(clusters):
        headings = [_normalize_heading(s.parsed.document_heading) for s in group]
        primary_heading = next((h for h in headings if h), None)
        hints = [
            (s.layout_hint or s.parsed.raw_fields.get("layout_hint") or "").strip().lower()
            for s in group
        ]
        primary_hint = next((h for h in hints if h), None)
        output.append(
            SampleCluster(
                cluster_id=index,
                filenames=tuple(s.filename for s in group),
                heading=primary_heading,
                layout_hint=primary_hint,
            )
        )
    return output


def select_primary_cluster_samples(
    samples: list[ParsedDocumentSample],
) -> tuple[list[ParsedDocumentSample], list[str]]:
    """Return samples from the largest cluster and advisory notes."""
    clusters = cluster_document_samples(samples)
    if len(clusters) <= 1:
        return samples, []

    largest = max(clusters, key=lambda cluster: len(cluster.filenames))
    selected = [sample for sample in samples if sample.filename in largest.filenames]
    notes = [
        "Samples appear to be different document types — analyzing the largest similar group "
        f"({len(largest.filenames)} of {len(samples)} files). "
        "Upload one document type per analysis for best results."
    ]
    for cluster in clusters:
        if cluster.cluster_id == largest.cluster_id:
            continue
        notes.append(
            f"Excluded cluster: {', '.join(cluster.filenames)}"
            + (f" (hint: {cluster.layout_hint})" if cluster.layout_hint else "")
        )
    return selected, notes
