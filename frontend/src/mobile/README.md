# Mobile UI

**Login first** (same LedgerLink email → OTP → tenant flow) → then this phone UI.

## Wired now

- **Profile / settings identity** from signed-in session
- **Sign out** + **Switch organisation**
- **Home → Recent activity** — live `GET /api/invoices` (demo rows removed). Tap a document to open **DT extraction fields** (same keys as desktop). Edits `PATCH` immediately (two-way with LedgerLink). Pending captures still appear at the top.

## Open

http://localhost:5173/m

Camera needs HTTPS (or localhost). On a phone use your Vite/ngrok URL.
