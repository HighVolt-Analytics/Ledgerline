"""
Proposal: link invoices to vendor_masters via nullable FK (Layer 3).

Status: PROPOSAL ONLY — do not implement until explicitly approved.
No Alembic revision should be generated from this document without a go-ahead.

## Problem

`invoices.vendor` is free-text. There is no `vendor_master_id` (or equivalent) FK.
Duplicate detection and VR12 vendor-master checks therefore re-resolve names on every
pass, and two master rows for the same legal entity ("3B Semiconductors Pvt Ltd" vs
"3B Semiconductors Private Limited") are invisible to invoice-level identity matching.

## Recommended schema (nullable, additive)

Add to `invoices`:

- `vendor_master_id` — `Integer`, nullable, `ForeignKey("vendor_masters.id")`, indexed
- Keep `vendor` free-text for display / audit / OCR provenance

Do **not** drop `vendor` or make the FK required in v1.

## Backfill approach

1. Ship column nullable (default NULL).
2. Nightly/job backfill per tenant:
   - Prefer exact ABN match to a single `vendor_masters` row.
   - Else normalized name match (Layer 2 `normalize_vendor_name` + lower) to a single row.
   - Else leave NULL (ambiguous / unknown).
3. Dual-read period: pipelines that today use free-text continue to work; new code paths
   prefer `vendor_master_id` when set, fall back to name.
4. Optional write-path: after extraction + VR12 match, persist `vendor_master_id`.

## Application usage (post-migration)

- Layer 3 report (`find_probable_duplicate_vendors`) stays available for master hygiene.
- Invoice dedup (VR02 / fuzzy) can optionally group by `vendor_master_id` when both
  sides are linked — only after dual-read proves safe.
- Do **not** auto-merge vendor_masters; merges remain a manual admin action.

## Risks

- False backfill links if two masters share a similar name and no ABN.
- Historical invoices with OCR garbage names stay NULL forever (acceptable).
- RLS / tenant isolation: FK must always enforce `invoice.tenant_id == master.tenant_id`
  in application code (or a composite check constraint if Postgres).

## Rollback

Drop the column (or stop writing it and ignore reads). Free-text `vendor` remains source of truth.

## Out of scope for this proposal

- Auto-merge of vendor_masters
- Blocking invoice ingest on unresolved vendor_master_id
- New PyPI dependencies
"""
