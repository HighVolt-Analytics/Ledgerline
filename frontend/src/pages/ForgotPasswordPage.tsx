import { useState } from "react";
import { Link } from "react-router-dom";
import { AuthCenteredCard } from "@/components/auth/AuthCenteredCard";
import { apiForgotPassword } from "@/lib/authApi";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await apiForgotPassword(email.trim());
      setMessage(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send reset email");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCenteredCard
      title="Forgot password"
      subtitle="Enter your email and we will send a reset link if an account exists."
    >
      {message ? (
        <div className="auth-form">
          <p className="auth-success" role="status">
            {message}
          </p>
          <div className="auth-footer">
            <Link to="/login" className="auth-link-accent">
              Back to sign in
            </Link>
          </div>
        </div>
      ) : (
        <form onSubmit={(e) => void onSubmit(e)} className="auth-form">
          <input
            type="email"
            className="auth-input"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
          {error ? (
            <p className="auth-error" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" className="auth-submit" disabled={busy}>
            {busy ? "Sending…" : "Send reset link"}
          </button>
          <div className="auth-footer">
            <Link to="/login" className="auth-link">
              Back to sign in
            </Link>
          </div>
        </form>
      )}
    </AuthCenteredCard>
  );
}
