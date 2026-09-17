import { useState, type ReactNode } from "react";
import type { InvoiceClassificationAudit } from "@/api/types";
import {
  classificationReviewReasons,
  classificationStatusMessage,
  formatClassificationConfidence,
  formatDtCodeWithName,
  reviewReasonLabel,
} from "@/lib/classificationAuditDisplay";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { cn } from "@/lib/cn";

type InvoiceClassificationPanelProps = {
  audit: InvoiceClassificationAudit | null;
  loading?: boolean;
  requiresConfirm?: boolean;
  onConfirmDt?: (code: string) => void;
  onChangeDt?: (code: string) => void;
  catalogueCodes?: string[];
  documentTypes?: DocumentTypeDefinition[];
  currencyControl?: ReactNode;
};

function SourceColumn({
  label,
  name,
  confidence,
  emphasize,
}: {
  label: string;
  name: string;
  confidence: string;
  emphasize?: boolean;
}) {
  return (
    <div className={cn("ai-class-source", emphasize && "ai-class-source--confirmed")}>
      <div className="ai-class-source__label">{label}</div>
      <div className="ai-class-source__name">{name}</div>
      <div className="ai-class-source__conf tnum">{confidence}</div>
    </div>
  );
}

function RoutingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="ai-class-routing-row">
      <span className="ai-class-routing-row__label">{label}</span>
      <span className="ai-class-routing-row__value tnum">{value}</span>
    </div>
  );
}

function compactClassificationStatus(
  statusMessage: string | null,
  chips: string[],
  requiresConfirm: boolean
): string | null {
  if (statusMessage) return statusMessage;
  const visible = chips.filter((chip) => chip !== "DT_NOT_IN_CATALOGUE");
  if (!visible.length) return null;
  if (requiresConfirm) return "Confirm or change document type to continue processing.";
  return reviewReasonLabel(visible[0]);
}

function dtControlTone({
  confirmed,
  catalogueCodes,
  requiresConfirm,
  chips,
}: {
  confirmed: string;
  catalogueCodes: string[];
  requiresConfirm: boolean;
  chips: string[];
}): "ok" | "error" {
  const inCatalogue = catalogueCodes.some(
    (code) => code.trim().toUpperCase() === confirmed.trim().toUpperCase()
  );
  if (
    requiresConfirm ||
    !confirmed.trim() ||
    !inCatalogue ||
    chips.includes("DT_NOT_IN_CATALOGUE")
  ) {
    return "error";
  }
  return "ok";
}

function SelectGlow({
  tone,
  children,
}: {
  tone?: "ok" | "error";
  children: ReactNode;
}) {
  return (
    <span className={cn("ai-class-select-glow", tone && `ai-class-select-glow--${tone}`)}>
      {children}
    </span>
  );
}

function ChangeDtSelect({
  catalogueCodes,
  documentTypes,
  onChangeDt,
  tone,
}: {
  catalogueCodes: string[];
  documentTypes: DocumentTypeDefinition[];
  onChangeDt: (code: string) => void;
  tone: "ok" | "error";
}) {
  return (
    <SelectGlow tone={tone}>
      <select
        className="ai-class-select ai-class-select--compact"
        defaultValue=""
        aria-label="Change document type"
        onChange={(e) => {
          const code = e.target.value;
          if (code) onChangeDt(code);
        }}
      >
        <option value="" disabled>
          Change DT
        </option>
        {catalogueCodes.map((code) => (
          <option key={code} value={code}>
            {formatDtCodeWithName(documentTypes, code)}
          </option>
        ))}
      </select>
    </SelectGlow>
  );
}

function ClassificationHead({
  title,
  quiet,
  changeDt,
  currencyControl,
}: {
  title: string;
  quiet?: boolean;
  changeDt?: ReactNode;
  currencyControl?: ReactNode;
}) {
  return (
    <div className="ai-class-panel__head">
      <h3 className={cn("ai-class-panel__title", quiet && "ai-class-panel__title--quiet")}>
        {title}
      </h3>
      {changeDt || currencyControl ? (
        <div className="ai-class-panel__head-controls">
          {changeDt}
          {currencyControl}
        </div>
      ) : null}
    </div>
  );
}

export function InvoiceClassificationPanel({
  audit,
  loading,
  requiresConfirm = false,
  onConfirmDt,
  onChangeDt,
  catalogueCodes = [],
  documentTypes = [],
  currencyControl,
}: InvoiceClassificationPanelProps) {
  const [detailsOpen, setDetailsOpen] = useState(requiresConfirm);
  const [explanationOpen, setExplanationOpen] = useState(false);

  if (loading) {
    return (
      <div className="ai-class-panel ai-class-panel--loading" aria-busy>
        Loading classification…
      </div>
    );
  }

  const showDtPicker = Boolean(onChangeDt) && catalogueCodes.length > 0;
  const dtTone = dtControlTone({
    confirmed: (audit?.confirmed_dt ?? audit?.document_type_code ?? "").trim(),
    catalogueCodes,
    requiresConfirm,
    chips: audit ? classificationReviewReasons(audit) : ["DT_NOT_IN_CATALOGUE"],
  });
  const changeDtControl =
    showDtPicker && onChangeDt ? (
      <ChangeDtSelect
        catalogueCodes={catalogueCodes}
        documentTypes={documentTypes}
        onChangeDt={onChangeDt}
        tone={dtTone}
      />
    ) : null;

  // Vision understood hold (no OCR classify audit): still show DT picker / currency.
  if (!audit) {
    if (!showDtPicker && !currencyControl) return null;
    return (
      <section className="ai-class-panel" aria-label="Document type">
        <ClassificationHead
          title="Document type"
          quiet
          changeDt={changeDtControl}
          currencyControl={currencyControl}
        />
      </section>
    );
  }

  const llmDt = audit.llm_suggested_dt ?? "";
  const policyDt = audit.policy_winner_dt ?? "";
  const confirmed = audit.confirmed_dt ?? audit.document_type_code ?? "";
  const confirmedName = formatDtCodeWithName(documentTypes, confirmed);
  const confirmedConf = formatClassificationConfidence(
    audit.confirmed_confidence ?? audit.document_type_confidence
  );
  const chips = classificationReviewReasons(audit);
  const statusMessage = classificationStatusMessage(audit);
  const showConfirm = requiresConfirm && Boolean(onConfirmDt) && Boolean(llmDt);
  const explanation = (audit.llm_reasoning || audit.reason || "").trim();
  const explanationLong = explanation.length > 220;

  const effectiveRoute = audit.min_route_confidence;
  const orgRoute =
    audit.org_auto_route_min_confidence ?? audit.auto_route_min_confidence ?? null;
  const dtRoute = audit.dt_min_route_confidence ?? null;
  const hasRouting =
    (effectiveRoute != null && !Number.isNaN(effectiveRoute)) ||
    (orgRoute != null && !Number.isNaN(orgRoute)) ||
    (dtRoute != null && !Number.isNaN(dtRoute));

  const compactStatus = compactClassificationStatus(statusMessage, chips, requiresConfirm);
  const reviewNotes = chips.filter((chip) => chip !== "DT_NOT_IN_CATALOGUE");

  return (
    <section className="ai-class-panel" aria-label="AI classification">
      <ClassificationHead
        title="AI classification"
        changeDt={changeDtControl}
        currencyControl={currencyControl}
      />

      {compactStatus ? (
        <div className="ai-class-summary__status">{compactStatus}</div>
      ) : null}

      {showConfirm && onConfirmDt ? (
        <div className="ai-class-panel__actions">
          <button
            type="button"
            className="ai-class-btn"
            onClick={() => onConfirmDt(llmDt)}
          >
            Confirm {formatDtCodeWithName(documentTypes, llmDt)}
          </button>
        </div>
      ) : null}

      <div className="ai-class-toolbar">
        <button
          type="button"
          className="ai-class-toggle"
          aria-expanded={detailsOpen}
          onClick={() => setDetailsOpen((open) => !open)}
        >
          {detailsOpen ? "Hide details" : "View details"}
        </button>
        <div className="ai-class-summary__conf tnum">{confirmedConf}</div>
      </div>

      {detailsOpen ? (
        <div className="ai-class-details">
          <div className="ai-class-block">
            <div className="ai-class-block__label">Confirmed</div>
            <div className="ai-class-confirmed">
              <span className="ai-class-confirmed__name">{confirmedName}</span>
              <span className="ai-class-confirmed__conf tnum">{confirmedConf}</span>
            </div>
          </div>

          <div className="ai-class-block">
            <div className="ai-class-block__label">Classification sources</div>
            <div className="ai-class-sources">
              <SourceColumn
                label="LLM suggested"
                name={formatDtCodeWithName(documentTypes, llmDt)}
                confidence={formatClassificationConfidence(audit.llm_confidence)}
              />
              <SourceColumn
                label="Policy winner"
                name={formatDtCodeWithName(documentTypes, policyDt)}
                confidence={formatClassificationConfidence(audit.policy_winner_confidence)}
              />
              <SourceColumn
                label="Confirmed"
                name={confirmedName}
                confidence={confirmedConf}
                emphasize
              />
            </div>
          </div>

          {hasRouting ? (
            <div className="ai-class-block">
              <div className="ai-class-block__label">Routing</div>
              <div className="ai-class-routing">
                {effectiveRoute != null && !Number.isNaN(effectiveRoute) ? (
                  <RoutingRow
                    label="Auto-route threshold"
                    value={formatClassificationConfidence(effectiveRoute)}
                  />
                ) : null}
                {orgRoute != null && !Number.isNaN(orgRoute) ? (
                  <RoutingRow
                    label="Org-wide threshold"
                    value={formatClassificationConfidence(orgRoute)}
                  />
                ) : null}
                {dtRoute != null && !Number.isNaN(dtRoute) ? (
                  <RoutingRow
                    label="Document-type threshold"
                    value={formatClassificationConfidence(dtRoute)}
                  />
                ) : null}
              </div>
            </div>
          ) : null}

          {explanation ? (
            <div className="ai-class-block">
              <div className="ai-class-block__label">Explanation</div>
              {explanationLong && !explanationOpen ? (
                <>
                  <p className="ai-class-explanation ai-class-explanation--clamp">{explanation}</p>
                  <button
                    type="button"
                    className="ai-class-toggle ai-class-toggle--inline"
                    onClick={() => setExplanationOpen(true)}
                  >
                    Show explanation
                  </button>
                </>
              ) : (
                <p className="ai-class-explanation">{explanation}</p>
              )}
              {explanationLong && explanationOpen ? (
                <button
                  type="button"
                  className="ai-class-toggle ai-class-toggle--inline"
                  onClick={() => setExplanationOpen(false)}
                >
                  Hide explanation
                </button>
              ) : null}
            </div>
          ) : null}

          {reviewNotes.length ? (
            <div className="ai-class-block">
              <div className="ai-class-block__label">Review notes</div>
              <p className="ai-class-panel__note ai-class-panel__note--warn">
                {requiresConfirm
                  ? "Confirm or change document type to continue processing."
                  : "Classification review notes:"}
              </p>
              <ul className="ai-class-notes">
                {reviewNotes.map((chip) => (
                  <li key={chip} title={chip}>
                    {reviewReasonLabel(chip)}
                  </li>
                ))}
              </ul>
            </div>
          ) : statusMessage ? (
            <div className="ai-class-block">
              <p className="ai-class-panel__note ai-class-panel__note--ok">{statusMessage}</p>
            </div>
          ) : null}

          {audit.citation_failed && audit.citation_failed.length > 0 ? (
            <div className="ai-class-block ai-class-block--alert">
              <div className="ai-class-block__label">Citation grounding failed</div>
              <p className="ai-class-explanation">
                Fields without valid OCR citations: {audit.citation_failed.join(", ")}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
