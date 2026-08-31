import { useRef, useState, type ReactNode } from "react";
import { Ban, ChevronDown } from "lucide-react";
import type { BankTransaction } from "@/api/types";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";

function formatStatementDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
}

function plainAmount(amount: number): string {
  return amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function statementHeading(description: string): { title: string; subtitle: string | null } {
  const text = description.trim();
  if (!text) return { title: "—", subtitle: null };
  const words = text.split(/\s+/);
  if (words.length >= 2 && words[0].length <= 24) {
    return { title: words[0], subtitle: text };
  }
  return { title: text.length > 36 ? `${text.slice(0, 36)}…` : text, subtitle: null };
}

export function BankFeedStatementCard({
  txn,
  canPost,
  busy,
  onExclude,
  className,
}: {
  txn: BankTransaction;
  canPost?: boolean;
  busy?: boolean;
  onExclude?: () => void;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const optionsRef = useRef<HTMLDivElement>(null);
  const inflow = txn.money_flow === "in";
  const spent = !inflow ? plainAmount(txn.amount) : "—";
  const received = inflow ? plainAmount(txn.amount) : "—";
  const { title, subtitle } = statementHeading(txn.description);

  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 flex-col rounded-sm border border-[#d8dee4] bg-card shadow-sm dark:border-border",
        className
      )}
      data-testid={`bf-statement-${txn.id}`}
    >
      <div className="grid min-h-[7.5rem] flex-1 grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0 p-3">
          <div className="flex items-start justify-between gap-2">
            <span className="text-sm text-muted-foreground">{formatStatementDate(txn.txn_date)}</span>
            {onExclude && canPost ? (
              <div className="relative" ref={optionsRef}>
                <button
                  type="button"
                  className="inline-flex items-center gap-0.5 text-sm text-[#008abf] hover:underline"
                  onClick={() => setOptionsOpen((v) => !v)}
                  data-testid={`bf-options-${txn.id}`}
                >
                  Options
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
                {optionsOpen ? (
                  <>
                    <button
                      type="button"
                      className="fixed inset-0 z-10 cursor-default"
                      aria-label="Close options"
                      onClick={() => setOptionsOpen(false)}
                    />
                    <div className="absolute right-0 top-full z-20 mt-1 min-w-[8rem] rounded-sm border border-border bg-card py-1 shadow-md">
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted/60"
                        disabled={busy}
                        onClick={() => {
                          setOptionsOpen(false);
                          onExclude();
                        }}
                        data-testid={`bf-exclude-${txn.id}`}
                      >
                        <Ban className="h-3.5 w-3.5 text-muted-foreground" />
                        Exclude
                      </button>
                    </div>
                  </>
                ) : null}
              </div>
            ) : null}
          </div>

          <p className="mt-2 text-base font-bold leading-tight text-foreground">{title}</p>
          {subtitle ? (
            <p className="mt-0.5 text-sm leading-snug text-muted-foreground line-clamp-2">{subtitle}</p>
          ) : txn.reference ? (
            <p className="mt-0.5 text-sm text-muted-foreground">Ref {txn.reference}</p>
          ) : null}

          <button
            type="button"
            className="mt-2 inline-flex items-center gap-0.5 text-sm text-[#008abf] hover:underline"
            onClick={() => setExpanded((v) => !v)}
            data-testid={`bf-more-details-${txn.id}`}
          >
            {expanded ? "Less details" : "More details"}
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} />
          </button>

          {expanded ? (
            <dl className="mt-2 space-y-1 text-xs text-muted-foreground">
              <div>
                <dt className="inline font-medium text-foreground/80">Description </dt>
                <dd className="inline">{txn.description}</dd>
              </div>
              {txn.reference ? (
                <div>
                  <dt className="inline font-medium text-foreground/80">Reference </dt>
                  <dd className="inline">{txn.reference}</dd>
                </div>
              ) : null}
              {txn.import_id != null ? (
                <div>
                  <dt className="inline font-medium text-foreground/80">Import </dt>
                  <dd className="inline tnum">#{txn.import_id}</dd>
                </div>
              ) : null}
              {txn.category_rule_name ? (
                <div>
                  <dt className="inline font-medium text-foreground/80">Rule </dt>
                  <dd className="inline">{txn.category_rule_name}</dd>
                </div>
              ) : null}
            </dl>
          ) : null}
        </div>

        <div className="grid shrink-0 grid-cols-2 gap-x-6 self-stretch border-l border-[#d8dee4] px-4 py-3 dark:border-border min-w-[10.5rem]">
          <div className="flex flex-col items-end text-right">
            <span className="text-xs leading-none text-muted-foreground whitespace-nowrap">Spent</span>
            <span
              className={cn(
                "tnum mt-1.5 text-sm font-semibold leading-none whitespace-nowrap",
                !inflow && "text-foreground"
              )}
            >
              {spent}
            </span>
          </div>
          <div className="flex flex-col items-end text-right">
            <span className="text-xs leading-none text-muted-foreground whitespace-nowrap">Received</span>
            <span
              className={cn(
                "tnum mt-1.5 text-sm font-semibold leading-none whitespace-nowrap",
                inflow && "text-emerald-700 dark:text-emerald-400"
              )}
            >
              {received}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function BankFeedArchiveStatementCard({
  txn,
  summary,
  actions,
}: {
  txn: BankTransaction;
  summary?: ReactNode;
  actions?: ReactNode;
}) {
  const inflow = txn.money_flow === "in";
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-sm border border-border bg-card px-3 py-2 shadow-sm"
      data-testid={`bf-archive-row-${txn.id}`}
    >
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="tnum shrink-0 text-[11px] text-muted-foreground">{txn.txn_date}</span>
        <span className="min-w-[8rem] flex-1 truncate text-sm font-medium">{txn.description}</span>
        <span className="tnum shrink-0 text-xs">
          <span className="text-muted-foreground">Spent </span>
          <span className="font-semibold">
            {!inflow ? money(txn.amount, txn.currency) : "—"}
          </span>
          <span className="mx-1.5 text-muted-foreground">·</span>
          <span className="text-muted-foreground">Received </span>
          <span className={cn("font-semibold", inflow && "text-emerald-600 dark:text-emerald-400")}>
            {inflow ? money(txn.amount, txn.currency) : "—"}
          </span>
        </span>
        {summary ? <span className="w-full text-xs text-muted-foreground">{summary}</span> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
