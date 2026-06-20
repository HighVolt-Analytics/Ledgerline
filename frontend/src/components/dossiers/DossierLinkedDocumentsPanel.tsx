import { Link } from "react-router-dom";
import {
  FileText,
  Link2,
  Package,
  Receipt,
  ShoppingCart,
} from "lucide-react";
import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import { SectionBlock } from "@/components/SectionBlock";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type { DossierLinkedDocument, DossierLinkedDocuments } from "@/lib/dossierLinkedDocuments";
import {
  documentSourceLabel,
  linkedDocumentCounts,
  linkageKindLabel,
  requirementLabel,
} from "@/lib/dossierLinkedDocuments";
import type { MatchStatus } from "@/lib/v4MockData";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";

const ROLE_ICONS = {
  po: ShoppingCart,
  grn: Package,
  invoice: Receipt,
} as const;

function roleIcon(doc: DossierLinkedDocument) {
  const role = doc.purchaseBundleRole;
  if (role && role in ROLE_ICONS) {
    return ROLE_ICONS[role as keyof typeof ROLE_ICONS];
  }
  return FileText;
}

function matchStatusForSummary(status: string): MatchStatus | null {
  if (status === "3-Way Match") return "3-Way Match";
  if (status === "Price Variance") return "Price Variance";
  if (status === "Qty Variance") return "Qty Variance";
  if (status === "No GRN") return "No GRN";
  if (status === "Routed for Approval") return "Routed for Approval";
  return null;
}

function LinkedDocumentCard({
  doc,
  dossierId,
}: {
  doc: DossierLinkedDocument;
  dossierId: string;
}) {
  const Icon = roleIcon(doc);
  const canOpen =
    doc.present &&
    doc.linkedDossierId &&
    doc.linkedDossierId !== dossierId &&
    doc.hasFile !== false;

  return (
    <article
      className={cn(
        "dossier-linked-doc",
        doc.isAnchor && "dossier-linked-doc--anchor",
        !doc.present && "dossier-linked-doc--missing"
      )}
      data-testid={`linked-doc-${doc.id}`}
    >
      <div className="dossier-linked-doc__head">
        <span className="dossier-linked-doc__type">
          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="tnum">{doc.documentTypeCode}</span>
        </span>
        <StatusPill
          className={
            doc.present
              ? doc.isAnchor
                ? pillTones.ok
                : pillTones.ok
              : doc.requirement === "mandatory"
                ? pillTones.bad
                : pillTones.muted
          }
        >
          {doc.present ? (doc.isAnchor ? "anchor" : "linked") : "missing"}
        </StatusPill>
      </div>

      <div className="dossier-linked-doc__label">{doc.label}</div>

      {doc.present && doc.documentRef ? (
        <div className="dossier-linked-doc__ref tnum">{doc.documentRef}</div>
      ) : (
        <p className="dossier-linked-doc__missing">Not on file</p>
      )}

      <div className="dossier-linked-doc__meta">
        <span>{requirementLabel(doc.requirement)}</span>
        {doc.source ? (
          <>
            <span className="dossier-linked-doc__sep">·</span>
            <span>{documentSourceLabel(doc.source)}</span>
          </>
        ) : null}
      </div>

      {doc.linkageDetail ? (
        <p className="dossier-linked-doc__detail">{doc.linkageDetail}</p>
      ) : null}

      {canOpen ? (
        <Link
          to={`/dossiers/${encodeURIComponent(doc.linkedDossierId!)}`}
          className="dossier-linked-doc__open"
        >
          Open dossier
        </Link>
      ) : null}
    </article>
  );
}

export function DossierLinkedDocumentsPanel({
  dossierId,
  linked,
}: {
  dossierId: string;
  linked: DossierLinkedDocuments;
}) {
  const { present, required } = linkedDocumentCounts(linked);
  const matchBadge = linked.matchSummary
    ? matchStatusForSummary(linked.matchSummary.status)
    : null;

  return (
    <SectionBlock
      label="Linked documents"
      description="Playbook bundle members assembled on linkage key — same model as invoice PO Match tab."
    >
      <div className="dossier-panel">
        <div className="dossier-linked-header">
          <div className="dossier-linked-header__key">
            <Link2 className="h-3.5 w-3.5 text-primary shrink-0" aria-hidden />
            <div className="min-w-0">
              <div className="dossier-linked-header__kind">{linkageKindLabel(linked.linkageKind)}</div>
              {linked.linkageKey ? (
                <div className="dossier-linked-header__value tnum">{linked.linkageKey}</div>
              ) : (
                <div className="dossier-linked-header__value text-muted-foreground">
                  {linked.linkageLabel}
                </div>
              )}
            </div>
          </div>
          <div className="dossier-linked-header__badges">
            {matchBadge ? <MatchStatusBadge status={matchBadge} /> : null}
            {linked.enforceBundle ? (
              <StatusPill className={present >= required ? pillTones.ok : pillTones.amber}>
                {present}/{required} mandatory
              </StatusPill>
            ) : null}
          </div>
        </div>

        {linked.documents.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No supporting documents required for this document type.
          </p>
        ) : (
          <div className="dossier-linked-grid">
            {linked.documents.map((doc) => (
              <LinkedDocumentCard key={doc.id} doc={doc} dossierId={dossierId} />
            ))}
          </div>
        )}

        {linked.matchSummary ? (
          <div className="dossier-linked-match">
            <div className="dossier-linked-match__row">
              <span>PO value</span>
              <span className="tnum">
                {money(linked.matchSummary.poValue, linked.matchSummary.currency)}
              </span>
            </div>
            <div className="dossier-linked-match__row">
              <span>Invoice total</span>
              <span className="tnum">
                {money(linked.matchSummary.invoiceTotal, linked.matchSummary.currency)}
              </span>
            </div>
            {linked.matchSummary.deviation !== 0 ? (
              <div className="dossier-linked-match__row dossier-linked-match__row--emph">
                <span>Deviation</span>
                <span className="tnum">
                  {money(linked.matchSummary.deviation, linked.matchSummary.currency)}
                </span>
              </div>
            ) : null}
          </div>
        ) : null}

        {linked.conditionalAdvisories.length > 0 ? (
          <div className="dossier-linked-advisories">
            <p className="dossier-linked-advisories__label">Conditional advisories</p>
            <ul className="dossier-linked-advisories__list">
              {linked.conditionalAdvisories.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {linked.purchaseOrderId != null ? (
          <Link to="/purchases" className="dossier-linked-purchases-link">
            Open in Purchase Management →
          </Link>
        ) : null}
      </div>
    </SectionBlock>
  );
}
