import type { ReactNode } from "react";
import { Logo } from "@/components/Logo";

export function AuthCenteredCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="auth-page">
      <div className="auth-shell">
        <div className="auth-brand">
          <span className="auth-brand-mark">
            <Logo size={26} />
          </span>
          <div className="auth-brand-text">
            <span className="auth-brand-name">Ledgerlink</span>
            <span className="auth-brand-tag">Invoice to Ledger</span>
          </div>
        </div>

        <div className="auth-heading">
          <h1>{title}</h1>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>

        {children}
      </div>
    </div>
  );
}
