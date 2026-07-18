# Cross-channel duplicate detection (Layer 6)

Status: **page-fingerprint last-resort closed** the residual unsplit/segment gap when page text is available. OCR-empty pages still fall through to T4 (allow + review flag) and post-OCR VR02.

## Entry points

| Path | Dedup helper |
|------|----------------|
| Manual upload | `intake_document` / `ingest_upload_file` → `_ingest_file_with_fanout_core` |
| Email | Capture rules + Exceptions quirk in adapter → same core via `ingest_file_with_fanout` |
| WhatsApp / Viber | Channel gates + replies in adapter → `intake_document` |

All live channels converge on the same ingest duplicate helpers (`find_existing_ingest_duplicate_match` + `resolve_ingest_duplicate`).

## Confidence waterfall

1. **T1** — `file_hash` / `source_file_hash`
2. **T2** — `business_fingerprint` / `content_fingerprint` / identity overlap
3. **T3** — page fingerprints (`invoice_page_fingerprints`) **only if T1+T2 miss**
4. **T4** — allow create; set `duplicate_review_suggested` when signals are sparse

Normalized filename is stored and may label a match as `filename_combo` when identity already matched; it never blocks alone.

## Bundle segment vs standalone

| Signal | Catches same content as bundle page? |
|--------|--------------------------------------|
| `file_hash` | **No** — segment bytes ≠ original standalone file |
| `content_fingerprint` (page range) | **Yes** when text extraction succeeds |
| `page_fingerprint` (persisted) | **Yes** via T3 last-resort lookup |
| `source_file_hash` | Catches re-upload of the **same parent** PDF |
| Identity overlap | Sometimes, if invoice#/vendor harvested |

## Residual gap

If page text is empty (OCR failure) and identity harvest is weak, T3 cannot fire — invoice is created with `duplicate_review_suggested` and VR02 remains the post-extract safety net.

## Rule Book boundary

Email capture rules stay email-only. WhatsApp/Viber do not evaluate the Rule Book capture engine; they use employee match + hard-coded `ingest:whatsapp` / `ingest:viber`.
