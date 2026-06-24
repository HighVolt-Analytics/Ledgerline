import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import type { InvitePreview } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { formatTenantRole } from "@/lib/tenantRoles";

export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("Missing invite token");
      setLoading(false);
      return;
    }
    void api
      .previewTenantInvite(token)
      .then((data) => {
        setPreview(data);
        setFullName(data.full_name);
        if (data.expired) setError("This invitation has expired.");
        if (data.accepted) setError("This invitation has already been accepted.");
      })
      .catch(() => setError("Invitation not found"))
      .finally(() => setLoading(false));
  }, [token]);

  const accept = async () => {
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.acceptTenantInvite({
        token,
        password,
        full_name: fullName.trim() || undefined,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not accept invitation");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-[100dvh] flex items-center justify-center p-4 bg-background">
      <Card className="w-full max-w-md p-6">
        <h1 className="text-lg font-semibold mb-1">Accept invitation</h1>
        {loading && <p className="text-sm text-muted-foreground">Loading invitation…</p>}

        {!loading && preview && !done && !error && (
          <>
            <p className="text-sm text-muted-foreground mb-4">
              Join <strong>{preview.tenant_name}</strong> as{" "}
              <strong>{formatTenantRole(preview.role)}</strong> ({preview.email})
            </p>
            <div className="space-y-3">
              <Input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Full name"
              />
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                autoComplete="new-password"
              />
              <Input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="Confirm password"
                autoComplete="new-password"
              />
            </div>
            <Button className="w-full mt-4" disabled={busy} onClick={() => void accept()}>
              {busy ? "Creating account…" : "Accept & create account"}
            </Button>
          </>
        )}

        {error && <p className="text-sm text-destructive mt-2">{error}</p>}

        {done && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Your account is ready. Sign in to complete organisation setup.
            </p>
            <Button
              className="w-full"
              onClick={() => navigate("/login", { state: { fromInvite: true } })}
            >
              Go to sign in
            </Button>
          </div>
        )}

        {!loading && !token && (
          <p className="text-sm text-muted-foreground">
            <Link to="/login" className="text-primary underline">
              Back to sign in
            </Link>
          </p>
        )}
      </Card>
    </div>
  );
}
