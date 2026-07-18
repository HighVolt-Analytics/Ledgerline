# Ingest policy decisions (locked defaults)

These are product decisions for remaining ingest gaps — not build work.

| Topic | Locked default | Notes |
|-------|----------------|-------|
| **Body-only email** | Intentionally ignore | Attachments are required. Text/HTML-only messages are skipped (`no_attachments` / filter-class audits). No body-OCR capture path. |
| **MIME allow-lists** | Keep WA/Viber `webp` | Do **not** unify email vs chat allow-lists without an explicit product confirmation. WhatsApp/Viber continue to accept `image/webp`; email filter stays as today. |
| **Chat Rule Book** | Deferred | Capture-rule engine for WhatsApp/Viber is backlog only — no build in this roadmap. |

## Related

- Durable skip reasons: `ingest_skipped` event + Phase 1 taxonomy (`backend/app/services/ingest/ingest_skip_service.py`).
- Mailbox lifecycle: `mailbox_messages` outcomes are source of truth; Graph folder moves / Gmail labels are side effects.
- **Message-ID limitation:** lifecycle uniqueness is `(connected_mailbox_id, stable_message_id)` using RFC `internetMessageId` when present. If production shows frequent collisions on forwards that reuse the same Message-ID, a follow-up may composite with `provider_message_id` — not in the initial schema.
