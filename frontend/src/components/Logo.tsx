export const LEDGERLINK_LOGO_SRC = "/ledgerlinklogo-Photoroom.png";

export function Logo({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <img
      src={LEDGERLINK_LOGO_SRC}
      width={size}
      height={size}
      alt=""
      className={["shrink-0 object-contain", className].filter(Boolean).join(" ")}
      decoding="async"
    />
  );
}

export function LogoBlock({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 min-w-0">
      <Logo size={26} />
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
