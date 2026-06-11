import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Mail } from "lucide-react";
import { api } from "@/api/client";
import type { MailboxInvitePreview } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export function ConnectMailboxPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const oauth = searchParams.get("mailbox_oauth");
  const oauthEmail = searchParams.get("email");
  const oauthMessage = searchParams.get("message");

  const [preview, setPreview] = useState<MailboxInvitePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token || oauth) return;
    setError(null);
    api
      .previewMailboxInvite(token)
      .then(setPreview)
      .catch((e) => setError(e instanceof Error ? e.message : "Invitation not found"));
  }, [token, oauth]);

  async function connectWithMicrosoft() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const { authorize_url } = await api.startMailboxInviteOAuth(token);
      window.location.assign(authorize_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start Microsoft sign-in");
      setBusy(false);
    }
  }

  if (oauth === "success") {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-background">
        <Card className="max-w-md w-full p-8 text-center space-y-4">
          <Mail className="h-10 w-10 text-primary mx-auto" />
          <h1 className="text-lg font-semibold">Mailbox connected</h1>
          <p className="text-sm text-muted-foreground">
            {oauthEmail
              ? `${oauthEmail} is authorized for invoice capture.`
              : "Your mailbox is connected."}
          </p>
          <p className="text-xs text-muted-foreground">
            You can close this window. Your organisation admin will see the mailbox
            as connected in LedgerLink.
          </p>
        </Card>
      </div>
    );
  }

  if (oauth === "error") {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-background">
        <Card className="max-w-md w-full p-8 text-center space-y-4">
          <h1 className="text-lg font-semibold text-destructive">Connection failed</h1>
          <p className="text-sm text-muted-foreground">
            {oauthMessage || "Microsoft sign-in was cancelled or failed."}
          </p>
          {token && (
            <Button onClick={() => void connectWithMicrosoft()} disabled={busy}>
              Try again
            </Button>
          )}
        </Card>
      </div>
    );
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-background">
        <Card className="max-w-md w-full p-8 text-center">
          <p className="text-sm text-muted-foreground">Missing invitation link.</p>
        </Card>
      </div>
    );
  }

  if (error && !preview) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-background">
        <Card className="max-w-md w-full p-8 text-center space-y-3">
          <p className="text-sm text-destructive">{error}</p>
        </Card>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-background">
        <p className="text-sm text-muted-foreground">Loading invitation…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <Card className="max-w-md w-full p-8 space-y-5">
        <div className="text-center space-y-2">
          <Mail className="h-10 w-10 text-primary mx-auto" />
          <h1 className="text-lg font-semibold">Connect your mailbox</h1>
          <p className="text-sm text-muted-foreground">
            <strong>{preview.org_name}</strong> has requested access to read invoice
            attachments from:
          </p>
          <p className="text-sm font-medium">{preview.requested_email}</p>
        </div>

        {preview.message && (
          <p className="text-sm text-muted-foreground border-l-2 border-border pl-3 italic">
            {preview.message}
          </p>
        )}

        <p className="text-xs text-muted-foreground">
          You will sign in with Microsoft and grant LedgerLink permission to read mail
          for automated invoice processing.
        </p>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <Button className="w-full" onClick={() => void connectWithMicrosoft()} disabled={busy}>
          {busy ? "Redirecting…" : "Connect with Microsoft"}
        </Button>
      </Card>
    </div>
  );
}
