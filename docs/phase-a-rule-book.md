# Phase A — Pipeline correctness (architecture alignment)

Implements the first three items from the v4 Rule Book Architecture spec.

## A.1 Email Capture gate

Inbound email attachments are evaluated against `email_capture_rules` **before** an `Invoice` row is created.

| Outcome | Behaviour |
|---------|-----------|
| Rule matches | Attachment saved, invoice created, early `route_target` set (unchanged) |
| No rule matches | `email_skipped` audit event with `reason: no_capture_rule_match` — **no document** |

Module: `pipeline.ingest_email_attachments`

## A.2 Legacy cascade

After v4 books (purchase → team → expense → vendor master), the v3 backstop runs:

`po_code` → `doc_code` → `vendor` → `keyword` → suspense fallback

Config block: `legacy_cascade` on org rule book JSON. Pre-v4 root keys (`po_codes`, `keywords`, …) are auto-migrated on load.

Module: `legacy_cascade.py`, wired in `rule_book_mapper.resolve_config_mapping`

## A.3 Upload path routing

Manual uploads have no email metadata. After PDF parse (vendor / PO / lines populated), `apply_invoice_evaluation` runs **before** validation so `route_target` and team policy checks use category rules.

Module: `pipeline.process_invoice`

## Config

Template: `backend/app/rule_book_config.json` includes seeded `legacy_cascade`. Existing org files pick up legacy data via migration when old root keys are present.

## Verify

```powershell
cd backend
pytest tests/test_phase_a_pipeline.py tests/test_phase6_ingest.py tests/test_rule_book_mapper.py -q
```

Restart API after deploy. Emails that do not match an enabled capture rule will no longer appear in Inbox.
