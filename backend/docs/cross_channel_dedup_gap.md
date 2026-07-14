# Cross-channel duplicate detection gap (Layer 6)

Status: **audit complete** — matching-scope fix **held for separate review**.

## Entry points

| Path | Dedup helper |
|------|----------------|
| Manual upload | `ingest_upload_file` → `ingest_file_with_fanout` → `find_existing_ingest_duplicate` |
| Email | Pre-check `find`/`resolve`, then `ingest_file_with_fanout` |
| WhatsApp / Viber | `ingest_file_with_fanout` only |

All live channels converge on the same ingest duplicate helpers.

## Bundle segment vs standalone

| Signal | Catches same content as bundle page? |
|--------|--------------------------------------|
| `file_hash` | **No** — segment bytes ≠ original standalone file |
| `content_fingerprint` (page range) | **Yes** when text extraction succeeds — tenant-wide |
| `source_file_hash` | Catches re-upload of the **same parent** PDF, not arbitrary standalone |
| Identity overlap | Sometimes, if invoice#/vendor harvested |

## Residual gap (not fixed this pass)

If a multi-doc PDF **does not split** (segmentation skipped) and is stored as one row, its
full-document `content_fingerprint` may not equal a prior standalone page fingerprint.
OCR failure (`content_fingerprint is None`) plus weak identity harvest can also miss.

## Decision needed (separate review)

Whether to add explicit cross-scope matching (e.g. always compare page-range fingerprints
against existing invoices even when the upload stays single-file, or require split for
known multi-heading PDFs).
