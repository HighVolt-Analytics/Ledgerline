import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";
import {
  COUNTERPARTY_HEADER_HOVER_HINT,
  creationsVendorsHref,
} from "@/lib/counterpartyCreationsLink";

export function CounterpartyColumnHeaderLink({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <span className={cn("group/cp relative inline-block", className)}>
      <Link
        to={creationsVendorsHref()}
        title={COUNTERPARTY_HEADER_HOVER_HINT}
        className="counterparty-creations-link font-medium"
        data-testid="matrix-counterparty-header-link"
      >
        {label}
      </Link>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-0 z-30 mb-1.5 hidden w-max max-w-[min(280px,70vw)] rounded-md border border-border bg-popover px-2.5 py-2 text-left text-[11px] font-normal leading-snug text-popover-foreground shadow-md group-hover/cp:block"
      >
        {COUNTERPARTY_HEADER_HOVER_HINT}
      </span>
    </span>
  );
}
