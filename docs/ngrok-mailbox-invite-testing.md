# ngrok — external mailbox invite testing

Use this when you run LedgerLink locally but need someone **outside your laptop** to open an invite link and complete Microsoft OAuth.

## Setup (one ngrok tunnel on the API)

1. Start the API on port **8001** and ngrok:

   ```powershell
   cd backend
   uvicorn app.main:app --reload --port 8001
   ```

   ```powershell
   ngrok http 8001
   ```

2. Copy the **HTTPS** forwarding URL (e.g. `https://abridge-landowner-nutlike.ngrok-free.dev`).

3. In `backend/.env`:

   ```env
   PUBLIC_TUNNEL_URL=https://abridge-landowner-nutlike.ngrok-free.dev
   ```

   Restart the API. This automatically sets:

   - Invite email links → `https://…/connect-mailbox?token=…`
   - OAuth callback → `https://…/api/mailboxes/oauth/callback`
   - CORS → allows the tunnel origin

4. **Entra ID** → your app → **Authentication** → add redirect URI:

   ```
   https://<your-ngrok-host>/api/mailboxes/oauth/callback
   ```

   Must match exactly (no trailing slash).

5. Send or resend an invitation from **Integrations**.

## How it works

| Step | URL |
|------|-----|
| Email link | `https://<ngrok>/connect-mailbox?token=…` |
| Invite page | Served by the API (no separate frontend tunnel needed) |
| Microsoft OAuth return | `https://<ngrok>/api/mailboxes/oauth/callback` |
| Success screen | `https://<ngrok>/connect-mailbox?mailbox_oauth=success` |

You can still use `http://localhost:5173` for admin work (Integrations, Inbox, etc.).

## Notes

- **Free ngrok URLs change** each time you restart ngrok — update `PUBLIC_TUNNEL_URL` and the Entra redirect URI.
- Recipients may see ngrok’s browser warning once; click **Visit Site** to continue.
- Remove or comment `PUBLIC_TUNNEL_URL` when you are done testing locally.

## Related

- [mailbox-oauth-setup.md](./mailbox-oauth-setup.md) — full OAuth + invite flow
