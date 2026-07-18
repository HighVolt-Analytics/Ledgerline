# Canonical intake — rollout runbook

## Per-channel flag (independent, not all-or-nothing)

`CANONICAL_INTAKE_CHANNELS` is a **comma-separated allowlist**. Each channel is checked on its own:

| Value | Effect |
|-------|--------|
| `upload` | Only manual upload uses canonical intake |
| `upload,email` | Upload + email; WhatsApp/Viber stay on legacy pre-dedup / fanout path |
| `upload,email,whatsapp,viber` | All channels (current default) |
| *(empty)* | Facade off for every channel |

Aliases: `mailbox` / `graph` count as `email`.

Sequential rollout example:

```env
# Phase 1
CANONICAL_INTAKE_CHANNELS=upload

# Phase 2
CANONICAL_INTAKE_CHANNELS=upload,email

# Phase 3a
CANONICAL_INTAKE_CHANNELS=upload,email,whatsapp

# Phase 3b
CANONICAL_INTAKE_CHANNELS=upload,email,whatsapp,viber
```

Settings are cached (`get_settings` LRU). After changing the env var, **restart API workers / Celery / inline poller** so the new allowlist is picked up.

## In-flight items when a channel is flipped

The flag is read only at **intake create time** (when a new file becomes invoice row(s)). It does **not** change:

- Invoice rows already created (pending / parsing / later pipeline steps)
- `process_invoice` / Celery processing of existing IDs
- Duplicate decision matrices already applied to stored rows

So an email polled and ingested under the old path keeps processing normally after the flag flips. The flip only affects the **next** ingest call for that channel.

### Operational rule

- Do **not** flip a channel’s flag during an **active mailbox backfill** or a long poll batch you care about for mixed behavior audit trails.
- Preferred: wait for backfill/sync job to finish → set env → restart workers → enable the next channel.
- Safe anytime: flip while only idle invoices are in the pipeline (already-created rows are unaffected).

## Smoke-test T4 (possible duplicate)

1. Ingest a document with weak/empty text so ingest sets `duplicate_review_suggested`.
2. Open Upload → filter **Possible duplicates** (not **Needs review only**).
3. Confirm the row shows badge **Possible duplicate — review suggested**.
4. Open Approvals card / detail drawer and confirm the same label appears.

## Ops watch — T4 volume after fingerprint DI fallback

After shipping the ingest DI fallback (empty/thin local text → full DI before fingerprint give-up):

- Monitor share of **new** invoices with `duplicate_review_suggested=true` (and `duplicate_weak_signal` audit rate).
- Slice by `capture_source` / document type. If one doc type often fails DI, **Possible duplicates** can become a dumping ground.
- Trend only — not a page-worthy alert unless volume proves systemic. No fake fingerprints: DI miss still means T4 only.
