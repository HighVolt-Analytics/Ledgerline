import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type ConnectMailboxDialogProps = {
  open: boolean;
  onClose: () => void;
  onSendInvite: (body: {
    email: string;
    display_name?: string;
    message?: string;
  }) => Promise<void>;
};

export function ConnectMailboxDialog({
  open,
  onClose,
  onSendInvite,
}: ConnectMailboxDialogProps) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setBusy(false);
    setSent(false);
    setEmail("");
    setDisplayName("");
    setMessage("");
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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSendInvite({
        email: email.trim(),
        display_name: displayName.trim() || undefined,
        message: message.trim() || undefined,
      });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send invitation");
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
            Request mailbox connection
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

        {sent ? (
          <div className="space-y-4 py-2 text-sm">
            <p className="text-muted-foreground">
              Invitation sent to <span className="font-medium text-foreground">{email}</span>.
              They will receive an email with a link to connect their mailbox.
            </p>
            <Button type="button" onClick={onClose}>
              Done
            </Button>
          </div>
        ) : (
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Enter the mailbox owner&apos;s email. They will receive a request to authorize
              LedgerLink to read invoice attachments from that mailbox.
            </p>
            <div>
              <label className="text-xs font-medium text-muted-foreground">Mailbox email</label>
              <Input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="finance@company.com"
                className="mt-1"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Display name (optional)
              </label>
              <Input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Finance inbox"
                className="mt-1"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Message to recipient (optional)
              </label>
              <Input
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Please connect our AP mailbox for invoice capture"
                className="mt-1"
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy}>
                {busy ? "Sending…" : "Send invitation"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
