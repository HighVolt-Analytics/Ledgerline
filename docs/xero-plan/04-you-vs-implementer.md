# You vs implementer

Handshake (Connect) is **done**. Secrets, Standard Web App, redirect URI, and write-capable scopes are already in `.env`.

| Step | You | Implementer |
|------|-----|-------------|
| After Connect | Confirm Integrations shows connected | Sync / export ([03-after-connect.md](03-after-connect.md)) |
| Master write-back | Create vendor / GL in LedgerLink and confirm they appear in Xero | [Xero-write-backend.md](../../Xero-write-backend.md) |
| Before webhooks (later) | Signing key, public HTTPS URL | HMAC handler in new layer |
