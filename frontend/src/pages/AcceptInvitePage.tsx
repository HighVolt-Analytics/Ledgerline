import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import type { InvitePreview } from "@/api/types";
import { AuthCenteredCard } from "@/components/auth/AuthCenteredCard";
import { formatTenantRole } from "@/lib/tenantRoles";
import { Eye, EyeOff } from "lucide-react";

export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const canShowForm =
    !loading && preview && !done && !fatalError && !preview.expired && !preview.accepted;

  useEffect(() => {
    if (!token) {
      setFatalError("Missing invite token");
      setLoading(false);
      return;
    }
    void api
      .previewTenantInvite(token)
      .then((data) => {
        setPreview(data);
        setFullName(data.full_name);
        if (data.expired) setFatalError("This invitation has expired.");
        if (data.accepted) setFatalError("This invitation has already been accepted.");
      })
      .catch((err) =>
        setFatalError(err instanceof Error ? err.message : "Invitation not found")
      )
      .finally(() => setLoading(false));
  }, [token]);

  const accept = async () => {
    if (password.length < 8) {
      setFormError("Password must be at least 8 characters");
      return;
    }
    if (password !== confirm) {
      setFormError("Passwords do not match");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await api.acceptTenantInvite({
        token,
        password,
        full_name: fullName.trim() || undefined,
      });
      setDone(true);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not accept invitation");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCenteredCard
      title={done ? "Account created" : "Sign up for Ledgerlink"}
      subtitle={
        done
          ? "Your account is ready. Sign in to continue."
          : "Create your account to join your organisation."
      }
    >
      {loading && (
        <div className="auth-form" aria-busy="true" aria-label="Loading">
          <div className="auth-skeleton auth-skeleton-line w-52" />
          <div className="auth-skeleton auth-skeleton-input" />
          <div className="auth-skeleton auth-skeleton-input" />
          <div className="auth-skeleton auth-skeleton-input" />
          <div className="auth-skeleton auth-skeleton-button" />
        </div>
      )}

      {canShowForm && (
        <div className="auth-form">
          <p className="auth-invite-meta">
            Join <strong>{preview.tenant_name}</strong> as{" "}
            <strong>{formatTenantRole(preview.role)}</strong>
            <span>({preview.email})</span>
          </p>

          <input
            className="auth-input"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Full name"
          />

          <div className="auth-input-wrap">
            <input
              type={showPassword ? "text" : "password"}
              className="auth-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              autoComplete="new-password"
            />
            <button
              type="button"
              className="auth-input-toggle"
              aria-label={showPassword ? "Hide password" : "Show password"}
              onClick={() => setShowPassword((v) => !v)}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>

          <div className="auth-input-wrap">
            <input
              type={showConfirm ? "text" : "password"}
              className="auth-input"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Confirm password"
              autoComplete="new-password"
            />
            <button
              type="button"
              className="auth-input-toggle"
              aria-label={showConfirm ? "Hide password" : "Show password"}
              onClick={() => setShowConfirm((v) => !v)}
            >
              {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>

          <button type="button" className="auth-submit" disabled={busy} onClick={() => void accept()}>
            {busy ? "Creating account…" : "Create account"}
          </button>

          <div className="auth-footer">
            <p>
              Already have an account?{" "}
              <Link to="/login" className="auth-link-accent">
                Log in
              </Link>
            </p>
          </div>
        </div>
      )}

      {fatalError ? <p className="auth-error">{fatalError}</p> : null}
      {formError ? <p className="auth-error">{formError}</p> : null}

      {done && (
        <div className="auth-form">
          <button
            type="button"
            className="auth-submit"
            onClick={() => navigate("/login", { state: { fromInvite: true } })}
          >
            Go to sign in
          </button>
        </div>
      )}

      {!loading && !token && (
        <div className="auth-footer">
          <Link to="/login" className="auth-link-accent">
            Back to sign in
          </Link>
        </div>
      )}
    </AuthCenteredCard>
  );
}
