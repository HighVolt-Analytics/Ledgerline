import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, Clock, FileWarning, Loader2, TrendingDown, X } from "lucide-react";
import { StatusPill, pillTones } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cfoN0, cfoN1 } from "@/lib/cfoFormat";
import { formatMoneyByCurrencyMap } from "@/lib/format";
import { fetchUploadAnalysis } from "@/lib/uploadAnalysisApi";
import {
  mergeCurrencyTotals,
  type ApprovalBoardWipRow,
  type ExceptionMixRow,
  type UploadAnalysisDataset,
} from "@/lib/uploadAnalysisData";
import {
  uploadAnalysisScopeSubtitle,
  uploadAnalysisSections,
  uploadChannelLabel,
  type UploadAnalysisScope,
} from "@/lib/uploadAnalysisScope";
import {
  API_PORT_HINT,
  captureTenantFetchScope,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

type AnalysisTab = "overview" | "approvals" | "pipeline" | "issues";

function severityTone(severity: ExceptionMixRow["severity"]) {
  if (severity === "High") return pillTones.bad;
  if (severity === "Medium") return pillTones.amber;
  return pillTones.muted;
}

function summarizeAnalysis(data: UploadAnalysisDataset) {
  const queue = data.approvalBoard.filter((row) => row.key === "review" || row.key === "processing");
  const wipItems = queue.reduce((sum, row) => sum + row.items, 0);
  const wipValueByCurrency = mergeCurrencyTotals(...queue.map((row) => row.valueByCurrency));
  const flagged = data.summary.flagged;
  const funnel = data.processingFunnel;
  const ingested = funnel[0]?.count ?? data.summary.documentCount;
  const posted = funnel.find((row) => row.stage === "Posted")?.count ?? 0;
  const postedPct = funnel.find((row) => row.stage === "Posted")?.pct ?? 0;
  const dropOff = ingested > 0 ? ((ingested - posted) / ingested) * 100 : 0;
  const issueItems = data.exceptionMix.reduce((sum, row) => sum + row.items, 0);
  const atRiskByCurrency = mergeCurrencyTotals(...data.exceptionMix.map((row) => row.atRiskByCurrency));
  const busiestColumn =
    [...data.approvalBoard].sort((a, b) => b.flagged - a.flagged || b.items - a.items)[0] ?? null;

  return {
    wipItems,
    wipValueByCurrency,
    flagged,
    ingested,
    posted,
    postedPct,
    dropOff,
    atRiskByCurrency,
    issueItems,
    busiestColumn,
  };
}

function ScopeNotice({ title, body }: { title: string; body: string }) {
  return (
    <Card className="upload-analysis-notice">
      <p className="upload-analysis-notice__title">{title}</p>
      <p className="upload-analysis-notice__body">{body}</p>
    </Card>
  );
}

function KpiStrip({ data }: { data: UploadAnalysisDataset }) {
  const summary = useMemo(() => summarizeAnalysis(data), [data]);

  const tiles = [
    {
      label: "In queue",
      value: cfoN0(summary.wipItems),
      hint: `To Review + Processing · ${formatMoneyByCurrencyMap(summary.wipValueByCurrency)}`,
      tone: "neutral" as const,
    },
    {
      label: "Flagged",
      value: cfoN0(summary.flagged),
      hint: summary.flagged > 0 ? "Anomalies or holds" : "No flags",
      tone: summary.flagged > 0 ? ("warn" as const) : ("good" as const),
    },
    {
      label: "Posted",
      value: `${cfoN1(summary.postedPct)}%`,
      hint: `${cfoN0(summary.posted)} of ${cfoN0(summary.ingested)} received`,
      tone: summary.postedPct >= 90 ? ("good" as const) : ("neutral" as const),
    },
    {
      label: "Issues",
      value: cfoN0(summary.issueItems),
      hint: `${formatMoneyByCurrencyMap(summary.atRiskByCurrency)} value`,
      tone: summary.issueItems > 0 ? ("warn" as const) : ("good" as const),
    },
  ];

  return (
    <div className="upload-analysis-kpis">
      {tiles.map((tile) => (
        <div key={tile.label} className="upload-analysis-kpi" data-tone={tile.tone}>
          <span className="upload-analysis-kpi__label">{tile.label}</span>
          <span className="upload-analysis-kpi__value tnum">{tile.value}</span>
          <span className="upload-analysis-kpi__hint">{tile.hint}</span>
        </div>
      ))}
    </div>
  );
}

function TabBar({
  active,
  onChange,
}: {
  active: AnalysisTab;
  onChange: (tab: AnalysisTab) => void;
}) {
  const tabs: { id: AnalysisTab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "approvals", label: "Approvals" },
    { id: "pipeline", label: "Pipeline" },
    { id: "issues", label: "Issues" },
  ];

  return (
    <div className="upload-analysis-tabs" role="tablist" aria-label="Analysis sections">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          className="upload-analysis-tabs__btn"
          data-active={active === tab.id}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function QueueDepthBar({ row, maxItems }: { row: ApprovalBoardWipRow; maxItems: number }) {
  const pct = maxItems > 0 ? Math.min(100, (row.items / maxItems) * 100) : 0;
  const flaggedPct = row.items > 0 ? Math.min(100, (row.flagged / row.items) * 100) : 0;

  return (
    <div className="upload-analysis-queue">
      <div className="upload-analysis-queue__track">
        <div className="upload-analysis-queue__fill" style={{ width: `${pct}%` }} />
        {row.flagged > 0 ? (
          <div
            className="upload-analysis-queue__flagged"
            style={{ width: `${(pct * flaggedPct) / 100}%` }}
          />
        ) : null}
      </div>
      <div className="upload-analysis-queue__labels">
        <span className="tnum">Avg wait {cfoN1(row.avgWaitDays)} d</span>
        {row.flagged > 0 ? (
          <span className="tnum upload-analysis-queue__flagged-label">
            {row.flagged} flagged
          </span>
        ) : (
          <span className="tnum">No flags</span>
        )}
      </div>
    </div>
  );
}

function OverviewTab({ data }: { data: UploadAnalysisDataset }) {
  const summary = useMemo(() => summarizeAnalysis(data), [data]);
  const funnelTail = data.processingFunnel.slice(-4);
  const topIssues = [...data.exceptionMix]
    .sort((a, b) => {
      const aTotal = Object.values(a.atRiskByCurrency).reduce((sum, n) => sum + n, 0);
      const bTotal = Object.values(b.atRiskByCurrency).reduce((sum, n) => sum + n, 0);
      return bTotal - aTotal || b.items - a.items;
    })
    .slice(0, 3);
  const activeColumns = data.approvalBoard
    .filter((row) => row.key === "review" || row.key === "processing")
    .filter((row) => row.items > 0)
    .sort((a, b) => b.flagged - a.flagged);

  return (
    <div className="upload-analysis-overview">
      <section className="upload-analysis-overview__col">
        <h3 className="upload-analysis-section-title">
          <TrendingDown className="upload-analysis-section-title__icon" aria-hidden />
          Matrix pipeline
        </h3>
        <p className="upload-analysis-section-lead">{data.periodLabel}</p>
        <div className="upload-analysis-mini-funnel">
          {funnelTail.map((row) => (
            <div key={row.stage} className="upload-analysis-mini-funnel__row">
              <span className="upload-analysis-mini-funnel__label">{row.stage}</span>
              <div className="upload-analysis-mini-funnel__track" aria-hidden>
                <div
                  className="upload-analysis-mini-funnel__fill"
                  style={{ width: `${row.pct}%` }}
                />
              </div>
              <span className="upload-analysis-mini-funnel__pct tnum">{cfoN0(row.count)}</span>
            </div>
          ))}
        </div>
        <p className="upload-analysis-footnote">
          {cfoN1(summary.dropOff)}% do not reach Posted in this scope.
        </p>
      </section>

      <section className="upload-analysis-overview__col">
        <h3 className="upload-analysis-section-title">
          <AlertTriangle className="upload-analysis-section-title__icon" aria-hidden />
          Needs attention
        </h3>
        <div className="upload-analysis-attention">
          {summary.busiestColumn && summary.busiestColumn.flagged > 0 ? (
            <div className="upload-analysis-attention__item" data-kind="breach">
              <Clock className="upload-analysis-attention__icon" aria-hidden />
              <div>
                <p className="upload-analysis-attention__title">{summary.busiestColumn.column}</p>
                <p className="upload-analysis-attention__meta">
                  {summary.busiestColumn.flagged} flagged · {cfoN0(summary.busiestColumn.items)} documents
                </p>
              </div>
            </div>
          ) : null}

          {activeColumns
            .filter((row) => row.column !== summary.busiestColumn?.column)
            .map((row) => (
              <div key={row.key} className="upload-analysis-attention__item" data-kind="stage">
                <Clock className="upload-analysis-attention__icon" aria-hidden />
                <div>
                  <p className="upload-analysis-attention__title">{row.column}</p>
                  <p className="upload-analysis-attention__meta">
                    {cfoN0(row.items)} in queue · avg {cfoN1(row.avgWaitDays)} d
                  </p>
                </div>
              </div>
            ))}

          {topIssues.map((row) => (
            <div key={row.type} className="upload-analysis-attention__item" data-kind="exception">
              <FileWarning className="upload-analysis-attention__icon" aria-hidden />
              <div className="upload-analysis-attention__content">
                <p className="upload-analysis-attention__title">{row.type}</p>
                <p className="upload-analysis-attention__meta">
                  {cfoN0(row.items)} documents · {formatMoneyByCurrencyMap(row.atRiskByCurrency)}
                </p>
              </div>
              <StatusPill className={severityTone(row.severity)}>{row.severity}</StatusPill>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function ApprovalsTab({ data }: { data: UploadAnalysisDataset }) {
  const maxItems = Math.max(...data.approvalBoard.map((row) => row.items), 1);

  return (
    <div className="upload-analysis-workflow">
      <p className="upload-analysis-section-lead">
        Approval board columns — same as the Upload status filter (To Review, Processing, Approved, Rejected).
      </p>
      <div className="upload-analysis-stage-list">
        {data.approvalBoard.map((row) => (
          <article
            key={row.key}
            className="upload-analysis-stage-card"
            data-column={row.key}
          >
            <div className="upload-analysis-stage-card__head">
              <h4 className="upload-analysis-stage-card__title">{row.column}</h4>
              <div className="upload-analysis-stage-card__stats">
                <span className="tnum">{cfoN0(row.items)} docs</span>
                <span className="upload-analysis-stage-card__dot" aria-hidden />
                <span className="tnum">{formatMoneyByCurrencyMap(row.valueByCurrency)}</span>
                {row.flagged > 0 ? (
                  <>
                    <span className="upload-analysis-stage-card__dot" aria-hidden />
                    <span className="upload-analysis-stage-card__breach tnum">
                      {row.flagged} flagged
                    </span>
                  </>
                ) : null}
              </div>
            </div>
            <QueueDepthBar row={row} maxItems={maxItems} />
          </article>
        ))}
      </div>
    </div>
  );
}

function PipelineTab({ data }: { data: UploadAnalysisDataset }) {
  const first = data.processingFunnel[0];
  const posted = data.processingFunnel.find((row) => row.stage === "Posted");

  return (
    <div className="upload-analysis-funnel-panel">
      <p className="upload-analysis-section-lead">
        {first ? cfoN0(first.count) : "0"} received ·{" "}
        {posted ? `${cfoN1(posted.pct)}% posted to ledger` : "—"}
      </p>
      <div className="upload-analysis-funnel">
        {data.processingFunnel.map((row) => (
          <div key={row.stage} className="upload-analysis-funnel__row">
            <span className="upload-analysis-funnel__label">{row.stage}</span>
            <div className="upload-analysis-funnel__track" aria-hidden>
              <div className="upload-analysis-funnel__fill" style={{ width: `${row.pct}%` }} />
            </div>
            <div className="upload-analysis-funnel__stats">
              <span className="upload-analysis-funnel__count tnum">{cfoN0(row.count)}</span>
              <span className="upload-analysis-funnel__delta tnum">
                {row.delta == null ? "Start" : `${row.delta > 0 ? "+" : ""}${cfoN0(row.delta)}`}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function IssuesTab({ data }: { data: UploadAnalysisDataset }) {
  const sorted = [...data.exceptionMix].sort((a, b) => {
    const aTotal = Object.values(a.atRiskByCurrency).reduce((sum, n) => sum + n, 0);
    const bTotal = Object.values(b.atRiskByCurrency).reduce((sum, n) => sum + n, 0);
    return bTotal - aTotal || b.items - a.items;
  });
  const totalRiskByCurrency = mergeCurrencyTotals(...sorted.map((row) => row.atRiskByCurrency));
  const totalIssueItems = sorted.reduce((sum, row) => sum + row.items, 0);

  return (
    <div className="upload-analysis-exceptions">
      <p className="upload-analysis-section-lead">
        Matrix flags and validation issues · {formatMoneyByCurrencyMap(totalRiskByCurrency)} total value
      </p>
      <div className="upload-analysis-exception-list">
        {sorted.map((row) => {
          const share = totalIssueItems > 0 ? (row.items / totalIssueItems) * 100 : 0;
          return (
            <article
              key={row.type}
              className="upload-analysis-exception-card"
              data-highlight={row.highlight ?? false}
            >
              <div className="upload-analysis-exception-card__head">
                <h4 className="upload-analysis-exception-card__title">{row.type}</h4>
                <StatusPill className={severityTone(row.severity)}>{row.severity}</StatusPill>
              </div>
              <div className="upload-analysis-exception-card__metrics">
                <span className="tnum">{cfoN0(row.items)} docs</span>
                <span className="upload-analysis-exception-card__risk tnum">
                  {formatMoneyByCurrencyMap(row.atRiskByCurrency)}
                </span>
              </div>
              <div className="upload-analysis-exception-card__bar" aria-hidden>
                <div
                  className="upload-analysis-exception-card__bar-fill"
                  style={{ width: `${share}%` }}
                />
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

export function UploadAnalysisOverlay({
  open,
  onClose,
  scope,
}: {
  open: boolean;
  onClose: () => void;
  scope: UploadAnalysisScope;
}) {
  const [mounted, setMounted] = useState(false);
  const [state, setState] = useState<"open" | "closed">("closed");
  const [activeTab, setActiveTab] = useState<AnalysisTab>("overview");
  const [data, setData] = useState<UploadAnalysisDataset | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadSeq = useRef(0);
  const sections = uploadAnalysisSections(scope);

  useEffect(() => {
    if (open) {
      setMounted(true);
      setState("closed");
      setActiveTab("overview");
      const timer = window.setTimeout(() => setState("open"), 16);
      return () => window.clearTimeout(timer);
    }
    setState("closed");
    const timer = window.setTimeout(() => setMounted(false), 280);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open || !mounted) return;
    if (sections.showSetupNotice || sections.showBankFeedsNotice) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }

    const scopeToken = captureTenantFetchScope();
    const seq = ++loadSeq.current;
    setLoading(true);
    setError(null);

    void fetchUploadAnalysis(scope, true)
      .then((result) => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scopeToken)) return;
        setData(result);
      })
      .catch((err) => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scopeToken)) return;
        if (
          handleTenantScopedLoadFailure(err, {
            retry: () => {
              void fetchUploadAnalysis(scope, true).then(setData).catch(() => undefined);
            },
          })
        ) {
          return;
        }
        setData(null);
        setError(err instanceof Error ? err.message : "Failed to load analysis");
      })
      .finally(() => {
        if (seq === loadSeq.current && isTenantFetchScopeCurrent(scopeToken)) {
          setLoading(false);
        }
      });
  }, [open, mounted, scope, sections.showSetupNotice, sections.showBankFeedsNotice]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mounted, onClose]);

  if (!mounted) return null;

  const showData = data && !loading;

  return createPortal(
    <div data-testid="upload-analysis-overlay">
      <button
        type="button"
        className="upload-analysis-backdrop pointer-events-auto"
        data-state={state}
        aria-label="Close analysis"
        onClick={onClose}
      />
      <div className="upload-analysis-shell">
        <div className="upload-analysis-card" data-state={state} role="dialog" aria-modal="true">
          <header className="upload-analysis-card__head">
            <div className="upload-analysis-card__intro">
              <p className="upload-analysis-card__eyebrow">Document analysis</p>
              <h2 className="upload-analysis-card__title">
                {data?.scopeLabel ?? uploadChannelLabel(scope.channel)}
              </h2>
              <p className="upload-analysis-card__subtitle">{uploadAnalysisScopeSubtitle(scope)}</p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onClose}
              data-testid="button-upload-analysis-close"
            >
              <X className="h-4 w-4" aria-hidden />
              Close
            </Button>
          </header>

          {showData ? <KpiStrip data={data} /> : null}

          {showData ? <TabBar active={activeTab} onChange={setActiveTab} /> : null}

          <div className="upload-analysis-card__body">
            {loading ? (
              <div className="upload-analysis-loading">
                <Loader2 className="upload-analysis-loading__icon" aria-hidden />
                <p>Loading analysis for this section…</p>
              </div>
            ) : null}

            {error ? (
              <Card className="upload-analysis-notice upload-analysis-notice--error">
                <p className="upload-analysis-notice__title">Could not load analysis</p>
                <p className="upload-analysis-notice__body">
                  {formatTenantLoadError(error, API_PORT_HINT)}
                </p>
              </Card>
            ) : null}

            {sections.showSetupNotice ? (
              <ScopeNotice
                title={`${uploadChannelLabel(scope.channel)} setup`}
                body="Switch to the Summary tab to see approval board, matrix pipeline, and issue analysis for captured documents in this channel."
              />
            ) : null}

            {sections.showBankFeedsNotice ? (
              <ScopeNotice
                title="Bank feeds"
                body="Reconciliation analysis for bank feeds is separate from document intake. Open All Documents, Upload, Email, WhatsApp, or Viber on Summary to analyse captured documents."
              />
            ) : null}

            {showData ? (
              <div className="upload-analysis-tab-panel" role="tabpanel">
                {data.summary.truncated ? (
                  <p className="upload-analysis-footnote upload-analysis-footnote--banner">
                    Showing analysis for the most recent {cfoN0(data.summary.analyzedCount)} of{" "}
                    {cfoN0(data.summary.documentCount)} documents in this section.
                  </p>
                ) : null}
                {activeTab === "overview" ? <OverviewTab data={data} /> : null}
                {activeTab === "approvals" ? <ApprovalsTab data={data} /> : null}
                {activeTab === "pipeline" ? <PipelineTab data={data} /> : null}
                {activeTab === "issues" ? <IssuesTab data={data} /> : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
