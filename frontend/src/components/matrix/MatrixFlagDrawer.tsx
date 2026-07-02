import { AlertTriangle, Ban, Check, Shield } from "lucide-react";
import { DetailDrawer } from "@/components/DetailDrawer";
import { MatrixFlagBadge } from "@/components/matrix/MatrixFlagBadge";
import { MatrixPipelineBreakdown } from "@/components/matrix/MatrixPipelineBreakdown";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { documentDisplayRef, money } from "@/lib/format";
import type { Invoice } from "@/api/types";
import type { MatrixCell, MatrixStage } from "@/lib/matrix";
import { failedValidationResults } from "@/lib/matrixIssue";
import type { MatrixConflictRow, MatrixFlagType } from "@/lib/v4MatrixMockData";
import { cn } from "@/lib/cn";

export type MatrixFlagRow = {
  inv: Invoice;
  flag: MatrixFlagType;
  reason?: string;
  conflictWith?: string;
  conflictDetail?: MatrixConflictRow[];
  cells?: Record<MatrixStage, MatrixCell>;
};

type MatrixFlagDrawerProps = {
  row: MatrixFlagRow | null;
  open: boolean;
  onClose: () => void;
  busy?: boolean;
  onResolve: (docId: string, action: "unique" | "duplicate" | "approval") => void;
};

export function MatrixFlagDrawer({ row, open, onClose, busy = false, onResolve }: MatrixFlagDrawerProps) {
  if (!open || !row) return null;

  const docId = documentDisplayRef(row.inv);
  const total = money(row.inv.total, row.inv.currency);
  const validationFailures = failedValidationResults(row.inv);

  return (
    <DetailDrawer
      open={open}
      onClose={onClose}
      size="md"
      title={
        <span className="flex items-center gap-2 flex-wrap">
          Review: {docId}
          <MatrixFlagBadge flag={row.flag} />
        </span>
      }
      subtitle={[row.inv.vendor, total, row.inv.invoice_date].filter(Boolean).join(" · ")}
    >
      <div className="space-y-4 -mt-1">
        {row.reason && (
          <Card className="p-3 bg-[hsl(43_74%_49%/0.08)] border-[hsl(43_74%_49%/0.3)]">
            <div className="flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-[hsl(36_80%_40%)] dark:text-[hsl(43_74%_62%)] mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
                  Primary issue
                </p>
                <p className="text-sm">{row.reason}</p>
              </div>
            </div>
          </Card>
        )}

        {validationFailures.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              Failed validation checks
            </p>
            <ul className="space-y-1.5">
              {validationFailures.map((rule) => (
                <li
                  key={rule.rule}
                  className="rounded-md border border-destructive/25 bg-destructive/5 px-2.5 py-2 text-xs"
                >
                  <span className="font-medium tnum">{rule.rule}</span>
                  <p className="mt-0.5 text-[11px] text-destructive">{rule.message}</p>
                </li>
              ))}
            </ul>
          </div>
        )}

        {row.cells ? <MatrixPipelineBreakdown cells={row.cells} /> : null}

        {row.conflictDetail && row.conflictWith && (
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              Side-by-side conflict
            </p>
            <div className="overflow-hidden rounded-md border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground bg-muted/50 text-left">
                    <th className="px-3 py-1.5 font-medium">Field</th>
                    <th className="px-3 py-1.5 font-medium">{docId}</th>
                    <th className="px-3 py-1.5 font-medium">{row.conflictWith}</th>
                  </tr>
                </thead>
                <tbody>
                  {row.conflictDetail.map((line, i) => {
                    const match = line.thisDoc === line.otherDoc;
                    return (
                      <tr key={i} className="border-t border-border/60">
                        <td className="px-3 py-1.5 text-muted-foreground">{line.field}</td>
                        <td
                          className={cn(
                            "px-3 py-1.5 tnum",
                            match && "text-destructive font-medium"
                          )}
                        >
                          {line.thisDoc}
                        </td>
                        <td
                          className={cn(
                            "px-3 py-1.5 tnum",
                            match && "text-destructive font-medium"
                          )}
                        >
                          {line.otherDoc}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-muted-foreground mt-1.5">
              Matching fields shown in pink contribute to the duplicate score.
            </p>
          </div>
        )}

        <Card className="p-3 bg-muted/30">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Shield className="h-3.5 w-3.5 text-primary shrink-0" />
            This document is BLOCKED from reaching Approved / Posted and cannot enter the
            Payments queue until cleared.
          </div>
        </Card>

        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Resolution</p>
          <div className="grid grid-cols-1 gap-2">
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => onResolve(docId, "unique")}
              data-testid="button-confirm-unique"
            >
              <Check className="h-4 w-4 mr-1" />
              {busy ? "…" : "Confirmed unique"}
            </Button>
            <Button
              variant="outline"
              className="border-destructive/40 text-destructive"
              disabled={busy}
              onClick={() => onResolve(docId, "duplicate")}
              data-testid="button-confirm-duplicate"
            >
              <Ban className="h-4 w-4 mr-1" />
              {busy ? "…" : "Confirmed duplicate (archive)"}
            </Button>
            <Button
              disabled={busy}
              onClick={() => onResolve(docId, "approval")}
              data-testid="button-send-approval"
            >
              {busy ? "…" : "Send for approval"}
            </Button>
          </div>
        </div>
      </div>
    </DetailDrawer>
  );
}
