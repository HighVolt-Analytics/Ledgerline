import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import {
  COUNTERPARTY_HEADER_HOVER_HINT,
  creationsVendorsHref,
} from "@/lib/counterpartyCreationsLink";

export function UploadColumnHeaderLink({
  label,
  to,
  hint,
  testId,
  className,
}: {
  label: string;
  to: string;
  hint: string;
  testId: string;
  className?: string;
}) {
  return (
    <span className={cn("group/cp relative inline-block", className)}>
      <Link
        to={to}
        title={hint}
        className="counterparty-creations-link font-medium"
        data-testid={testId}
        onClick={(event) => event.stopPropagation()}
      >
        {label}
      </Link>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-0 z-30 mb-1.5 hidden w-max max-w-[min(280px,70vw)] rounded-md border border-border bg-popover px-2.5 py-2 text-left text-[11px] font-normal leading-snug text-popover-foreground shadow-md group-hover/cp:block"
      >
        {hint}
      </span>
    </span>
  );
}

export function UploadColumnCellLink({
  to,
  hint,
  testId,
  children,
}: {
  to: string;
  hint: string;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      title={hint}
      data-testid={testId}
      className="block min-w-0 max-w-full"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      {children}
    </Link>
  );
}

export function CounterpartyColumnHeaderLink({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <UploadColumnHeaderLink
      label={label}
      to={creationsVendorsHref()}
      hint={COUNTERPARTY_HEADER_HOVER_HINT}
      testId="matrix-counterparty-header-link"
      className={className}
    />
  );
}
