/**
 * TEMP dev panel — delete after pipeline development is stable.
 * Shows step-by-step pipeline audit output for one invoice.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "@/api/client";
import type { AuditLogEntry, InvoiceDetails } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

type StepDef = {
  id: string;
  label: string;
  events: string[];
  /** Invoice fields to show as live output when no audit row exists yet. */
  liveFields?: (keyof InvoiceDetails)[];
};

const PIPELINE_STEPS: StepDef[] = [
  {
    id: "document",
    label: "1 · Document (ingest)",
    events: ["email_ingested", "invoice_uploaded", "invoice_file_attached"],
    liveFields: ["document_ref", "email_sender", "created_at"],
  },
  {
    id: "storage",
    label: "2 · Storage verify",
    events: ["storage_verified"],
    liveFields: ["raw_file_path", "file_hash", "has_stored_file"],
  },
  {
    id: "ocr",
    label: "3 · OCR / layout read",
    events: ["ocr_completed", "parsing_failed"],
  },
  {
    id: "quality",
    label: "3b · Image quality gate",
    events: [
      "image_quality_gate_passed",
      "image_quality_gate_failed",
    ],
  },
  {
    id: "classify",
    label: "4 · LLM classify",
    events: ["llm_classified", "vendor_classification_drift", "vendor_classification_baseline"],
    liveFields: ["llm_suggested_dt", "llm_confidence"],
  },
  {
    id: "gate",
    label: "5 · Confidence gate",
    events: [
      "classification_gate_passed",
      "classification_gate_failed",
      "routing_review_required",
    ],
    liveFields: ["evaluation_status", "document_type_code", "document_type_confidence"],
  },
  {
    id: "extract",
    label: "6 · Field extract",
    events: ["parse_completed"],
    liveFields: ["vendor", "invoice_no", "total", "subtotal", "gst", "abn"],
  },
  {
    id: "field_conf",
    label: "6b · Field confidence",
    events: ["field_confidence_evaluated"],
  },
  {
    id: "dt",
    label: "7 · Document type applied",
    events: ["document_classified", "classification_resolved"],
    liveFields: ["document_type_code", "document_type_confidence", "route_target"],
  },
  {
    id: "eval",
    label: "8 · Route / eval",
    events: ["playbook_evaluated"],
    liveFields: ["route_target", "evaluation_status"],
  },
  {
    id: "validate",
    label: "9 · Validation",
    events: ["validation_passed", "validation_failed"],
  },
  {
    id: "map",
    label: "10 · Mapping",
    events: ["mapping_applied", "mapping_review_required"],
    liveFields: ["account_code", "account_name"],
  },
  {
    id: "post",
    label: "11 · Posted / processed",
    events: [
      "invoice_processed",
      "invoice_published_to_ledger",
      "vault_stored",
      "invoice_requeued",
    ],
    liveFields: ["status"],
  },
];

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function stepStatus(
  step: StepDef,
  matched: AuditLogEntry | null,
  inv: InvoiceDetails
): "done" | "fail" | "pending" | "skipped" {
  if (matched) {
    if (
      matched.event === "parsing_failed" ||
      matched.event === "classification_gate_failed" ||
      matched.event === "validation_failed" ||
      (matched.event === "routing_review_required" &&
        (matched.detail?.gate as string | undefined) === "classification")
    ) {
      return "fail";
    }
    return "done";
  }
  const hasLive = step.liveFields?.some((key) => {
    const v = inv[key];
    return v != null && v !== "" && v !== false;
  });
  if (hasLive) return "done";
  return "pending";
}

function statusDot(status: "done" | "fail" | "pending" | "skipped"): string {
  if (status === "done") return "bg-emerald-500";
  if (status === "fail") return "bg-destructive";
  if (status === "skipped") return "bg-muted-foreground/40";
  return "bg-muted-foreground/25";
}

function JsonBlock({ value }: { value: unknown }) {
  if (value == null) {
    return <p className="text-xs text-muted-foreground italic">No output recorded yet.</p>;
  }
  return (
    <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/30 p-2 text-[11px] leading-relaxed font-mono whitespace-pre-wrap break-all">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function liveSnapshot(inv: InvoiceDetails, fields: (keyof InvoiceDetails)[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of fields) {
    out[key] = inv[key] ?? null;
  }
  return out;
}

function summaryLine(step: StepDef, matched: AuditLogEntry | null): string {
  if (!matched) return "Waiting…";
  const d = matched.detail ?? {};
  switch (step.id) {
    case "storage":
      return String(d.path ?? d.document_ai_provider ?? matched.event);
    case "ocr":
      return `source=${d.source ?? d.document_ai_provider ?? "—"} · text=${d.text_length ?? "—"} · sparse=${String(d.sparse ?? "—")}`;
    case "classify":
      return `${d.llm_suggested_dt ?? "—"} @ ${d.llm_confidence != null ? `${Math.round(Number(d.llm_confidence) * 100)}%` : "—"}`;
    case "gate":
      if (matched.event === "routing_review_required") {
        const gate = String(d.gate ?? "");
        if (gate === "playbook") {
          const pb = (d.playbook ?? d) as Record<string, unknown>;
          const reason = String(pb.block_reason ?? "");
          const missing = pb.missing_bundle_mandatory;
          const fields = pb.missing_extraction_fields;
          if (reason === "linkage" || pb.linkage_key_missing) {
            const book = String(pb.linkage_book ?? "");
            return book === "sales"
              ? "playbook · SO reference missing"
              : "playbook · PO reference missing";
          }
          if (Array.isArray(missing) && missing.length) {
            return `playbook · supporting docs missing: ${missing.join(", ")}`;
          }
          if (Array.isArray(fields) && fields.length) {
            return `playbook · fields missing: ${fields.join(", ")}`;
          }
          return "playbook · posting blocked";
        }
        const reasons = d.review_reasons;
        return `blocked · ${Array.isArray(reasons) ? reasons.join(", ") : "review"}`;
      }
      return matched.event === "classification_gate_passed"
        ? `passed · ${d.confirmed_dt ?? d.llm_suggested_dt ?? "—"}`
        : `failed · ${Array.isArray(d.review_reasons) ? d.review_reasons.join(", ") : "low confidence"}`;
    case "extract":
      return `confirmed_dt=${d.confirmed_dt ?? "—"} · confidence=${d.confidence ?? "—"}`;
    default:
      return matched.event;
  }
}

export interface PipelineDebugPanelProps {
  invoice: InvoiceDetails;
}

export function PipelineDebugPanel({ invoice }: PipelineDebugPanelProps) {
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.listAuditLog(
        { invoice_id: String(invoice.id), page_size: "200" },
        { fresh: true }
      );
      setLogs([...rows].sort((a, b) => a.created_at.localeCompare(b.created_at)));
    } catch {
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }, [invoice.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const stepRows = useMemo(() => {
    return PIPELINE_STEPS.map((step) => {
      const matches = logs.filter((row) => step.events.includes(row.event));
      const matched = matches.length ? matches[matches.length - 1] : null;
      const status = stepStatus(step, matched, invoice);
      return { step, matched, allMatches: matches, status };
    });
  }, [logs, invoice]);

  const chronology = logs;

  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-100">
        <strong>Dev only.</strong> Temporary pipeline inspector — delete this tab when development
        is done.
      </div>

      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-muted-foreground">
          Invoice #{invoice.id} · status <span className="font-mono">{invoice.status}</span>
          {invoice.evaluation_status ? (
            <>
              {" "}
              · eval <span className="font-mono">{invoice.evaluation_status}</span>
            </>
          ) : null}
        </div>
        <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => void load()}>
          <RefreshCw className={cn("h-3.5 w-3.5 mr-1", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <div className="rounded-md border border-border bg-muted/20 p-2">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
          Live invoice snapshot
        </div>
        <JsonBlock
          value={{
            llm_suggested_dt: invoice.llm_suggested_dt,
            llm_confidence: invoice.llm_confidence,
            document_type_code: invoice.document_type_code,
            document_type_confidence: invoice.document_type_confidence,
            evaluation_status: invoice.evaluation_status,
            vendor: invoice.vendor,
            total: invoice.total,
            route_target: invoice.route_target,
            status: invoice.status,
          }}
        />
      </div>

      {loading && logs.length === 0 ? (
        <p className="text-sm text-muted-foreground">Loading pipeline trace…</p>
      ) : (
        <ol className="space-y-2">
          {stepRows.map(({ step, matched, allMatches, status }) => {
            const open = expanded === step.id;
            return (
              <li
                key={step.id}
                className={cn(
                  "rounded-md border border-border overflow-hidden",
                  status === "fail" && "border-destructive/40",
                  status === "done" && "border-emerald-500/20"
                )}
              >
                <button
                  type="button"
                  className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-muted/40"
                  onClick={() => setExpanded(open ? null : step.id)}
                >
                  <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", statusDot(status))} />
                  <span className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{step.label}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {summaryLine(step, matched)}
                      {matched ? ` · ${fmtTime(matched.created_at)}` : ""}
                    </div>
                  </span>
                  <span className="text-xs text-muted-foreground shrink-0">{open ? "▾" : "▸"}</span>
                </button>
                {open && (
                  <div className="border-t border-border px-3 py-2 space-y-2 bg-background/80">
                    {step.liveFields?.length ? (
                      <div>
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                          Live fields
                        </div>
                        <JsonBlock value={liveSnapshot(invoice, step.liveFields)} />
                      </div>
                    ) : null}
                    <div>
                      <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                        Latest audit output
                      </div>
                      <JsonBlock
                        value={
                          matched
                            ? {
                                event: matched.event,
                                at: matched.created_at,
                                detail: matched.detail,
                              }
                            : null
                        }
                      />
                    </div>
                    {allMatches.length > 1 ? (
                      <div>
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                          All runs ({allMatches.length})
                        </div>
                        <JsonBlock
                          value={allMatches.map((row) => ({
                            event: row.event,
                            at: row.created_at,
                            detail: row.detail,
                          }))}
                        />
                      </div>
                    ) : null}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}

      <div>
        <div className="text-xs font-semibold mb-2">Full audit chronology ({chronology.length})</div>
        <div className="max-h-72 overflow-auto rounded-md border border-border">
          <table className="w-full text-left text-[11px]">
            <thead className="sticky top-0 bg-muted/80 text-muted-foreground">
              <tr>
                <th className="px-2 py-1 font-medium">Time</th>
                <th className="px-2 py-1 font-medium">Event</th>
                <th className="px-2 py-1 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {chronology.map((row) => (
                <tr key={row.id} className="border-t border-border align-top">
                  <td className="px-2 py-1 whitespace-nowrap text-muted-foreground">
                    {fmtTime(row.created_at)}
                  </td>
                  <td className="px-2 py-1 font-mono">{row.event}</td>
                  <td className="px-2 py-1 font-mono text-muted-foreground break-all">
                    {row.detail ? JSON.stringify(row.detail) : "—"}
                  </td>
                </tr>
              ))}
              {!chronology.length && !loading ? (
                <tr>
                  <td colSpan={3} className="px-2 py-3 text-muted-foreground">
                    No audit rows for this invoice yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
