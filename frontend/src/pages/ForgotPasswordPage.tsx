import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthCenteredCard } from "@/components/auth/AuthCenteredCard";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { apiForgotPassword, apiResetPassword } from "@/lib/authApi";
import { Eye, EyeOff } from "lucide-react";

type Step = "email" | "otp" | "done";

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [challengeToken, setChallengeToken] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  // Public auth flow: wipe OTP/password draft if tenant scope changes mid-reset.
  useResetOnTenantChange(() => {
    setStep("email");
    setChallengeToken("");
    setOtp("");
    setPassword("");
    setConfirm("");
    setError(null);
    setBusy(false);
    setShowPassword(false);
    setShowConfirm(false);
  });

  const onRequestCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await apiForgotPassword(email.trim());
      setChallengeToken(result.challenge_token);
      setStep("otp");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start password reset");
    } finally {
      setBusy(false);
    }
  };

  const onReset = async (e: React.FormEvent) => {
    e.preventDefault();
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
      await apiResetPassword({
        challengeToken,
        otp: otp.trim(),
        password,
      });
      setStep("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset password");
    } finally {
      setBusy(false);
    }
  };

  const onResend = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await apiForgotPassword(email.trim());
      setChallengeToken(result.challenge_token);
      setOtp("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resend code");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCenteredCard
      title={step === "done" ? "Password updated" : "Forgot password"}
      subtitle={
        step === "email"
          ? "Enter your email and we will send a verification code."
          : step === "otp"
            ? "Enter the verification code sent to your email (dev: 123456), then choose a new password."
            : "Your password has been changed. Sign in with your new password."
      }
    >
      {step === "email" && (
        <form onSubmit={(e) => void onRequestCode(e)} className="auth-form">
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
            {busy ? "Sending…" : "Send verification code"}
          </button>
          <div className="auth-footer">
            <Link to="/login" className="auth-link">
              Back to sign in
            </Link>
          </div>
        </form>
      )}

      {step === "otp" && (
        <form onSubmit={(e) => void onReset(e)} className="auth-form">
          <input
            className="auth-input"
            placeholder="6-digit code"
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            required
            inputMode="numeric"
            autoComplete="one-time-code"
          />
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
          <button type="submit" className="auth-submit" disabled={busy}>
            {busy ? "Updating…" : "Update password"}
          </button>
          <div className="auth-footer">
            <button
              type="button"
              className="auth-link"
              disabled={busy}
              onClick={() => void onResend()}
            >
              Resend code
            </button>
            <p>
              <Link to="/login" className="auth-link-accent">
                Back to sign in
              </Link>
            </p>
          </div>
        </form>
      )}

      {step === "done" && (
        <div className="auth-form">
          <button
            type="button"
            className="auth-submit"
            onClick={() =>
              navigate("/login", {
                state: { signupMessage: "Password updated. Sign in to continue." },
              })
            }
          >
            Go to sign in
          </button>
        </div>
      )}
    </AuthCenteredCard>
  );
}
