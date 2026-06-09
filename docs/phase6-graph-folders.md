# Phase 6 — Graph mail folders (Processed / Exceptions)

After the pipeline runs, each polled email is moved out of **Inbox** into:

| Folder | When |
|--------|------|
| **Processed** | Every invoice linked to that message has status `processed` |
| **Exceptions** | Any `exception`, `duplicate_skipped`, still `pending`, or email skipped (no PDF) |

## Requirements

- Same Graph app as Phase 1 (`Mail.ReadWrite` application permission)
- Folders are created automatically under Inbox if missing

## Configuration

```env
GRAPH_FOLDER_MOVES_ENABLED=true
GRAPH_PROCESSED_FOLDER=Processed
GRAPH_EXCEPTIONS_FOLDER=Exceptions
```

Set `GRAPH_FOLDER_MOVES_ENABLED=false` to restore Phase 1 behaviour (mark as read only).

## Database

Migration `004` adds `invoices.email_message_id` to link rows to Graph `message_id`.

```powershell
cd backend && alembic upgrade head
```

## Flow

1. Beat/worker polls unread inbox messages
2. Attachments ingested → `email_message_id` stored on invoice
3. Invoices processed (parse → validate → journal)
4. `finalize_graph_messages` moves each message and writes `email_moved` audit event

## Verify

1. Send test email with invoice PDF to the mailbox
2. `POST /api/process/trigger`
3. Check Outlook: **Processed** or **Exceptions** folder
4. `GET /api/audit-log?event=email_moved`

## Upload path

Manual `POST /api/invoices/upload` has no `email_message_id` — folder moves do not apply.
