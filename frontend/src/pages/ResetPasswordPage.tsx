import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthCenteredCard } from "@/components/auth/AuthCenteredCard";
import { apiResetPassword } from "@/lib/authApi";
import { Eye, EyeOff } from "lucide-react";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) {
      setError("Missing reset token. Use the link from your email.");
      return;
    }
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
      await apiResetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCenteredCard
      title={done ? "Password updated" : "Reset password"}
      subtitle={
        done
          ? "Your password has been changed. Sign in with your new password."
          : "Choose a new password for your account."
      }
    >
      {done ? (
        <div className="auth-form">
          <button
            type="button"
            className="auth-submit"
            onClick={() => navigate("/login", { state: { signupMessage: "Password updated. Sign in to continue." } })}
          >
            Go to sign in
          </button>
        </div>
      ) : (
        <form onSubmit={(e) => void onSubmit(e)} className="auth-form">
          {!token ? (
            <p className="auth-error" role="alert">
              Missing reset token. Use the link from your email.
            </p>
          ) : null}

          <div className="auth-input-wrap">
            <input
              type={showPassword ? "text" : "password"}
              className="auth-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="New password"
              autoComplete="new-password"
              required
              minLength={8}
              disabled={!token}
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
              required
              minLength={8}
              disabled={!token}
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

          {error ? (
            <p className="auth-error" role="alert">
              {error}
            </p>
          ) : null}

          <button type="submit" className="auth-submit" disabled={busy || !token}>
            {busy ? "Updating…" : "Update password"}
          </button>

          <div className="auth-footer">
            <Link to="/forgot-password" className="auth-link">
              Request a new link
            </Link>
            <p>
              <Link to="/login" className="auth-link-accent">
                Back to sign in
              </Link>
            </p>
          </div>
        </form>
      )}
    </AuthCenteredCard>
  );
}
