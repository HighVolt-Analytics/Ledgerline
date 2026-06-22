import { useState } from "react";
import { Navigate } from "react-router-dom";
import { LogoBlock } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";

type Step = "credentials" | "otp" | "pick-tenant";

export function LoginPage() {
  const {
    user,
    loading,
    login,
    verifyOtp,
    selectTenant,
    resendOtp,
    tenantPicker,
  } = useAuth();

  const [step, setStep] = useState<Step>("credentials");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");

  if (!loading && user && user.id > 0) {
    return <Navigate to="/" replace />;
  }

  async function onCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      setStep("otp");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function onOtp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await verifyOtp(otp);
      if (result === "pick-tenant") setStep("pick-tenant");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function onPickTenant(tenantId: number) {
    setError(null);
    setBusy(true);
    try {
      await selectTenant(tenantId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not select tenant");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-background px-4">
      <Card className="w-full max-w-md p-6 space-y-6">
        <div className="flex justify-center">
          <LogoBlock />
        </div>
        <div className="text-center space-y-1">
          <h1 className="text-xl font-semibold">
            {step === "credentials"
              ? "Sign in"
              : step === "otp"
                ? "Verify your email"
                : "Choose organisation"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {step === "credentials"
              ? "Access your invoice pipeline dashboard"
              : step === "otp"
                ? "Enter the verification code sent to your email (dev: 123456)"
                : "Select which organisation to open"}
          </p>
        </div>

        {step === "credentials" && (
          <form onSubmit={onCredentials} className="space-y-3">
            <Input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
            <Input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "Please wait…" : "Continue"}
            </Button>
          </form>
        )}

        {step === "otp" && (
          <form onSubmit={onOtp} className="space-y-3">
            <Input
              placeholder="6-digit code"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              required
              inputMode="numeric"
              autoComplete="one-time-code"
            />
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "Verifying…" : "Verify"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              disabled={busy}
              onClick={() => void resendOtp().catch((e) => setError(String(e)))}
            >
              Resend code
            </Button>
          </form>
        )}

        {step === "pick-tenant" && (
          <div className="space-y-2">
            {tenantPicker.map((t) => (
              <Button
                key={t.tenant_id}
                type="button"
                variant="outline"
                className="w-full justify-start"
                disabled={busy}
                onClick={() => void onPickTenant(t.tenant_id)}
              >
                {t.tenant_name}
              </Button>
            ))}
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
