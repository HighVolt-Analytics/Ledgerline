# Duplicate detection — confidence-tiered stack (stakeholder summary)

| Layer | Mode | Flag default | Status |
|-------|------|--------------|--------|
| L1 Exact (file hash / source_file_hash) | Hard — T1 | always on | done |
| L2 Supplier/invoice business + content fingerprint | Hard — T2 | always on | done |
| L3 Page-level fingerprint (last resort after T1+T2 miss) | Hard — T3 | always on | done |
| L4 Weak / sparse signals | Allow + `duplicate_review_suggested` | always on | done |
| Filename normalize | Confidence booster only (never standalone block) | always on | done |
| Fuzzy business match (post-OCR VR02) | Review warn | `FUZZY_DUPLICATE_CHECK_ENABLED=false` | done |
| Content similarity | Boosts fuzzy confidence | `CONTENT_SIMILARITY_CHECK_ENABLED=false` | done |
| Canonical intake facade | Shared validate→dedupe→create→audit | `CANONICAL_INTAKE_CHANNELS=upload,email,whatsapp,viber` | done |

**Blocking automatically (T1–T3):** identical files, strong business/content fingerprints, page overlap when cheaper signals miss. Actions follow the existing matrix (`skip_in_progress` / `shadow_duplicate` / `reingest_rejected` / `skip_logged`).

**Allow with review (T4):** filename-only noise, or when ≥3 of 4 signal families are unavailable — never auto-skip. Visible in Upload as filter **Possible duplicates** (`duplicate_review_suggested`), separate from evaluation **Needs review only**.

**Channel adapters:** WhatsApp/Viber replies, email Rule Book capture, and Graph folder moves stay outside the canonical core.

**Rollout:** See [`canonical_intake_rollout.md`](canonical_intake_rollout.md) — `CANONICAL_INTAKE_CHANNELS` is a per-channel allowlist (e.g. `upload,email` leaves WhatsApp on the legacy path). Restart workers after changes; do not flip mid-backfill. Smoke T4 via Upload → **Possible duplicates**.

