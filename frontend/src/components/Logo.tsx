export function Logo({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      aria-label="Ledgerline"
      role="img"
    >
      <path d="M3 23 H11" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <path
        d="M11 23 V18 H16 V13 H21 V8 H27"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x="14.6" y="18" width="2.8" height="8" rx="0.6" fill="currentColor" opacity="0.35" />
      <rect x="19.6" y="13" width="2.8" height="13" rx="0.6" fill="currentColor" opacity="0.55" />
      <rect x="24.6" y="8" width="2.8" height="18" rx="0.6" fill="currentColor" opacity="0.85" />
    </svg>
  );
}

export function LogoBlock({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 min-w-0">
      <span className="text-primary shrink-0">
        <Logo size={26} />
      </span>
      {!collapsed && (
        <div className="flex flex-col min-w-0 leading-none">
          <span className="font-semibold text-[15px] tracking-tight truncate">Ledgerline</span>
          <span className="text-[10px] text-muted-foreground tracking-wide uppercase">
            Invoice to Ledger
          </span>
        </div>
      )}
    </div>
  );
}
