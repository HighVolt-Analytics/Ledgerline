import ledgerlinkLogo from "@/assets/ledgerlink-logo.png";

/** Bundled logo asset (also mirrored in `public/` for favicon). */
export const LEDGERLINK_LOGO_SRC = ledgerlinkLogo;

export function Logo({
  size = 28,
  className = "",
}: {
  /** Height in px; width stays proportional. */
  size?: number;
  className?: string;
}) {
  return (
    <img
      src={LEDGERLINK_LOGO_SRC}
      alt="Ledgerlink"
      height={size}
      style={{ height: size, width: "auto", display: "block" }}
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
          <span className="font-semibold text-[15px] tracking-tight truncate">Ledgerlink</span>
          <span className="text-[10px] text-muted-foreground tracking-wide uppercase">
            Invoice to Ledger
          </span>
        </div>
      )}
    </div>
  );
}
