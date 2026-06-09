import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const PROVIDERS = ["Gmail", "Outlook", "IMAP", "Exchange"] as const;

type ConnectMailboxDialogProps = {
  open: boolean;
  onClose: () => void;
  onConnect: (data: { email: string; nickname: string; provider: string }) => Promise<void>;
};

export function ConnectMailboxDialog({ open, onClose, onConnect }: ConnectMailboxDialogProps) {
  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
  const [provider, setProvider] = useState<string>("Gmail");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setBusy(false);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function handleConnect() {
    const trimmed = email.trim().toLowerCase();
    if (!trimmed) {
      setError("Email address is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onConnect({
        email: trimmed,
        nickname: nickname.trim() || "Primary AP",
        provider,
      });
      setEmail("");
      setNickname("");
      setProvider("Gmail");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect mailbox");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/80"
        aria-label="Close dialog"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-mailbox-title"
        className="relative z-10 w-full max-w-md rounded-lg border border-border bg-background p-6 shadow-lg"
        data-testid="dialog-connect-mailbox"
      >
        <div className="flex items-start justify-between gap-4 mb-4">
          <h2 id="connect-mailbox-title" className="text-lg font-semibold leading-none">
            Connect a mailbox
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-sm opacity-70 hover:opacity-100 transition-opacity"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="mailbox-email">
              Email address
            </label>
            <Input
              id="mailbox-email"
              type="email"
              data-testid="input-mailbox-email"
              placeholder="ap@yourcompany.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="mailbox-nickname">
              Nickname
            </label>
            <Input
              id="mailbox-nickname"
              data-testid="input-mailbox-nickname"
              placeholder="Primary AP"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="mailbox-provider">
              Provider
            </label>
            <Select
              id="mailbox-provider"
              data-testid="select-mailbox-provider"
              value={provider}
              onValueChange={setProvider}
              size="md"
              options={PROVIDERS.map((p) => ({ value: p, label: p }))}
              className="w-full"
            />
          </div>

          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
        </div>

        <div className="flex justify-end mt-2">
          <Button
            data-testid="button-confirm-mailbox"
            onClick={handleConnect}
            disabled={busy || !email.trim()}
          >
            {busy ? "Connecting…" : "Connect mailbox"}
          </Button>
        </div>
      </div>
    </div>
  );
}
