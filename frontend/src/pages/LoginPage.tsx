import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { LogoBlock } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";

type SetupState = {
  mode?: "register";
  org_name?: string;
  org_slug?: string;
  email?: string;
};

export function LoginPage() {
  const { user, loading, login, register } = useAuth();
  const location = useLocation();
  const setup = (location.state as SetupState | null) ?? {};
  const [mode, setMode] = useState<"login" | "register">(
    setup.mode === "register" ? "register" : "login"
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [email, setEmail] = useState(setup.email ?? "");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState(setup.org_name ?? "");
  const [orgSlug, setOrgSlug] = useState(setup.org_slug ?? "");

  if (!loading && user && user.id > 0) {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register({
          org_name: orgName,
          org_slug: orgSlug.toLowerCase().replace(/[^a-z0-9-]/g, "-"),
          email,
          password,
          full_name: fullName,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
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
            {mode === "login" ? "Sign in" : "Create your organisation"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {mode === "login"
              ? "Access your invoice pipeline dashboard"
              : "First-time setup — register your company and admin account"}
          </p>
        </div>

        <form onSubmit={onSubmit} className="space-y-3">
          {mode === "register" && (
            <>
              <Input
                placeholder="Organisation name"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                required
              />
              <Input
                placeholder="Organisation slug (e.g. acme-corp)"
                value={orgSlug}
                onChange={(e) => setOrgSlug(e.target.value)}
                required
                pattern="[a-z0-9-]+"
              />
              <Input
                placeholder="Your full name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
              />
            </>
          )}
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
            placeholder="Password (min 8 characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          {mode === "login" ? (
            <>
              First time here?{" "}
              <button
                type="button"
                className="text-primary underline-offset-2 hover:underline"
                onClick={() => setMode("register")}
              >
                Register organisation
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button
                type="button"
                className="text-primary underline-offset-2 hover:underline"
                onClick={() => setMode("login")}
              >
                Sign in
              </button>
            </>
          )}
        </p>
      </Card>
    </div>
  );
}
