import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Mail } from "lucide-react";
import { api } from "@/api/client";
import type { MailboxInvitePreview, MailProvider } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

function providerLabel(provider: MailProvider): string {
  return provider === "google" ? "Google" : "Microsoft";
}

export function ConnectMailboxPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const oauth = searchParams.get("mailbox_oauth");
  const oauthEmail = searchParams.get("email");
  const oauthMessage = searchParams.get("message");

  const [preview, setPreview] = useState<MailboxInvitePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyProvider, setBusyProvider] = useState<MailProvider | null>(null);

  const providers = useMemo<MailProvider[]>(() => {
    if (!preview) return [];
    if (preview.available_providers?.length) {
      return preview.available_providers as MailProvider[];
    }
    if (preview.mail_provider === "google" || preview.mail_provider === "microsoft") {
      return [preview.mail_provider];
    }
    return ["google", "microsoft"];
  }, [preview]);

  useEffect(() => {
    if (!token || oauth) return;
    setError(null);
    api
      .previewMailboxInvite(token)
      .then(setPreview)
      .catch((e) => setError(e instanceof Error ? e.message : "Invitation not found"));
  }, [token, oauth]);

  async function connectWithProvider(provider: MailProvider) {
    if (!token) return;
    setBusyProvider(provider);
    setError(null);
    try {
      const { authorize_url } = await api.startMailboxInviteOAuth(token, provider);
      window.location.assign(authorize_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to start ${providerLabel(provider)} sign-in`);
      setBusyProvider(null);
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
            {oauthMessage || "Sign-in was cancelled or failed."}
          </p>
          {token && providers.length > 0 && (
            <div className="flex flex-col gap-2">
              {providers.map((provider) => (
                <Button
                  key={provider}
                  onClick={() => void connectWithProvider(provider)}
                  disabled={busyProvider != null}
                >
                  Try {providerLabel(provider)} again
                </Button>
              ))}
            </div>
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

  const singleProvider = providers.length === 1 ? providers[0] : null;

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <Card className="max-w-md w-full p-8 space-y-5">
        <div className="text-center space-y-2">
          <Mail className="h-10 w-10 text-primary mx-auto" />
          <h1 className="text-lg font-semibold">Connect your mailbox</h1>
          <p className="text-sm text-muted-foreground">
            <strong>{preview.tenant_name}</strong> has requested access to read invoice
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
          {singleProvider
            ? `Sign in with ${providerLabel(singleProvider)} using the invited email address.`
            : "Choose the provider that hosts this mailbox, then sign in with the invited email address."}
        </p>

        {providers.includes("microsoft") && (
          <p className="text-xs text-muted-foreground rounded-md border border-amber-500/40 bg-amber-500/5 p-2">
            If Microsoft shows &quot;Need admin approval&quot;, a Microsoft 365 Global
            Administrator must grant org-wide consent once from LedgerLink →
            Integrations → Open Microsoft admin consent. Then retry this link.
          </p>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex flex-col gap-2">
          {providers.includes("google") && (
            <Button
              className="w-full"
              variant={singleProvider === "google" ? "default" : "outline"}
              onClick={() => void connectWithProvider("google")}
              disabled={busyProvider != null || preview.google_oauth_configured === false}
            >
              {busyProvider === "google" ? "Redirecting…" : "Connect with Google"}
            </Button>
          )}
          {providers.includes("microsoft") && (
            <Button
              className="w-full"
              variant={singleProvider === "microsoft" ? "default" : "outline"}
              onClick={() => void connectWithProvider("microsoft")}
              disabled={busyProvider != null || preview.microsoft_oauth_configured === false}
            >
              {busyProvider === "microsoft" ? "Redirecting…" : "Connect with Microsoft"}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
