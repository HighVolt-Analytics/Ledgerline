import { useState } from "react";

import { Link } from "react-router-dom";

import {

  ChevronRight,

  FileText,

  Link2,

  Package,

  Plus,

  Receipt,

  ShoppingCart,

  Unlink,

} from "lucide-react";

import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import { money } from "@/lib/format";

import { SectionBlock } from "@/components/SectionBlock";

import { StatusPill, pillTones } from "@/components/StatusPill";

import { Button } from "@/components/ui/button";

import { DossierManualLinkDialog } from "@/components/dossiers/DossierManualLinkDialog";

import type { DossierLinkedDocument, DossierLinkedDocuments } from "@/lib/dossierLinkedDocuments";

import {
  documentSourceLabel,
  isSalesLinkedDocuments,
  linkedDocumentCounts,
  linkageKindLabel,
  requirementLabel,
} from "@/lib/dossierLinkedDocuments";
import { requiredSupportingDocsLabel } from "@/lib/documentBundleConfig";

import type { MatchStatus } from "@/lib/v4MockData";


import { cn } from "@/lib/cn";



const ROLE_ICONS = {

  po: ShoppingCart,

  grn: Package,

  invoice: Receipt,

  so: ShoppingCart,

  dn: Package,

} as const;



function roleIcon(doc: DossierLinkedDocument) {

  const role = doc.salesBundleRole || doc.purchaseBundleRole;

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



function resolveInvoiceId(

  doc: DossierLinkedDocument,

  anchorInvoiceId?: number | null

): number | null {

  if (doc.manualLink?.invoiceId != null) return doc.manualLink.invoiceId;

  if (doc.linkKind === "manual" && doc.invoiceId != null) return doc.invoiceId;

  if (doc.invoiceId != null) return doc.invoiceId;

  if (doc.isAnchor && anchorInvoiceId != null) return anchorInvoiceId;

  return null;

}



function manualLinkIdForDoc(doc: DossierLinkedDocument): number | null {

  if (doc.manualLink?.id != null) return doc.manualLink.id;

  if (doc.linkKind === "manual" && doc.manualLinkId != null) return doc.manualLinkId;

  return null;

}



function documentTypeCodeLabel(code: string): string {

  const token = (code ?? "").trim();

  return token || "Unclassified";

}



function statusPill(doc: DossierLinkedDocument) {

  if (doc.linkKind === "manual") {

    return { tone: pillTones.amber, label: "manual" };

  }

  if (doc.linkKind === "invoice_no") {

    return { tone: pillTones.ok, label: "linked" };

  }

  if (doc.manualLink) {

    return { tone: pillTones.amber, label: "manual" };

  }

  if (doc.present) {

    return { tone: pillTones.ok, label: doc.isAnchor ? "anchor" : "linked" };

  }

  if (doc.requirement === "mandatory") {

    return { tone: pillTones.bad, label: "missing" };

  }

  return { tone: pillTones.muted, label: "missing" };

}



function LinkedDocumentCard({

  doc,

  anchorInvoiceId,

  onOpenDocument,

  onLinkSlot,

  onUnlink,

  unlinkingId,

}: {

  doc: DossierLinkedDocument;

  anchorInvoiceId?: number | null;

  onOpenDocument?: (invoiceId: number) => void;

  onLinkSlot?: (doc: DossierLinkedDocument) => void;

  onUnlink?: (linkId: number) => void;

  unlinkingId?: number | null;

}) {

  const Icon = roleIcon(doc);

  const invoiceId = resolveInvoiceId(doc, anchorInvoiceId);

  const manualLinkId = manualLinkIdForDoc(doc);

  const isManualOnly = doc.linkKind === "manual";

  const hasManualOverlay = Boolean(doc.manualLink);

  const displayRef =

    doc.manualLink?.documentRef ?? (doc.present ? doc.documentRef : null);

  const canOpen =

    invoiceId != null &&

    doc.hasFile !== false &&

    (doc.present || hasManualOverlay || isManualOnly) &&

    (doc.manualLink?.hasFile !== false);



  const pill = statusPill(doc);

  const showLinkSlot =

    !doc.isAnchor &&

    !doc.present &&

    !hasManualOverlay &&

    !isManualOnly &&

    onLinkSlot != null;



  const className = cn(

    "dossier-linked-doc",

    doc.isAnchor && "dossier-linked-doc--anchor",

    !doc.present && !hasManualOverlay && !isManualOnly && "dossier-linked-doc--missing",

    (hasManualOverlay || isManualOnly) && "dossier-linked-doc--manual",

    canOpen && "dossier-linked-doc--clickable hover-elevate"

  );



  const body = (

    <>

      <span className="dossier-linked-doc__icon" aria-hidden>

        <Icon className="h-4 w-4" />

      </span>



      <div className="dossier-linked-doc__body">

        <div className="dossier-linked-doc__head">

          <span

            className={cn(

              "dossier-linked-doc__type tnum",

              !doc.documentTypeCode?.trim() && "dossier-linked-doc__type--pending"

            )}

          >

            {documentTypeCodeLabel(doc.documentTypeCode)}

          </span>

          <StatusPill className={pill.tone}>{pill.label}</StatusPill>

        </div>



        <div className="dossier-linked-doc__label">{doc.label}</div>



        {displayRef ? (

          <div className="dossier-linked-doc__ref tnum">{displayRef}</div>

        ) : (

          <p className="dossier-linked-doc__missing">Not on file</p>

        )}



        {hasManualOverlay && doc.manualLink ? (

          <p className="dossier-linked-doc__manual-note">

            Manual: {doc.manualLink.label} ({doc.manualLink.documentRef ?? doc.manualLink.linkedDossierId})

          </p>

        ) : null}



        <div className="dossier-linked-doc__meta">

          <span>{requirementLabel(doc.requirement)}</span>

          {doc.source ? (

            <>

              <span className="dossier-linked-doc__sep" aria-hidden>

                ·

              </span>

              <span>{documentSourceLabel(doc.source)}</span>

            </>

          ) : null}

        </div>



        {!doc.isAnchor && doc.linkageDetail ? (

          <p className="dossier-linked-doc__detail">{doc.linkageDetail}</p>

        ) : null}



        {(showLinkSlot || manualLinkId != null) && (

          <div className="dossier-linked-doc__actions">

            {showLinkSlot ? (

              <Button

                type="button"

                size="sm"

                variant="outline"

                className="h-7 text-xs"

                onClick={(e) => {

                  e.stopPropagation();

                  onLinkSlot?.(doc);

                }}

              >

                <Link2 className="h-3 w-3 mr-1" />

                Link

              </Button>

            ) : null}

            {manualLinkId != null && onUnlink ? (

              <Button

                type="button"

                size="sm"

                variant="ghost"

                className="h-7 text-xs text-muted-foreground"

                disabled={unlinkingId === manualLinkId}

                onClick={(e) => {

                  e.stopPropagation();

                  onUnlink(manualLinkId);

                }}

              >

                <Unlink className="h-3 w-3 mr-1" />

                Unlink

              </Button>

            ) : null}

          </div>

        )}

      </div>



      {canOpen ? (

        <ChevronRight className="dossier-linked-doc__chevron h-4 w-4 shrink-0" aria-hidden />

      ) : null}

    </>

  );



  if (canOpen) {

    return (

      <button

        type="button"

        className={className}

        data-testid={`linked-doc-${doc.id}`}

        aria-label={`Open ${doc.label}`}

        onClick={() => onOpenDocument?.(invoiceId!)}

      >

        {body}

      </button>

    );

  }



  return (

    <article className={className} data-testid={`linked-doc-${doc.id}`}>

      {body}

    </article>

  );

}



export function DossierLinkedDocumentsPanel({

  linked,

  anchorInvoiceId,

  dossierId,

  onOpenDocument,

  onAddManualLink,

  onRemoveManualLink,

}: {

  linked: DossierLinkedDocuments;

  anchorInvoiceId?: number | null;

  dossierId?: string;

  onOpenDocument?: (invoiceId: number) => void;

  onAddManualLink?: (body: { linkedInvoiceId: number; slotId?: string | null }) => Promise<void>;

  onRemoveManualLink?: (linkId: number) => Promise<void>;

}) {

  const { present, required } = linkedDocumentCounts(linked);
  const salesBook = isSalesLinkedDocuments(linked);
  const refShort = salesBook ? "SO" : "PO";
  const supportingPair = salesBook ? "SO copy and delivery note (DN)" : "PO copy and goods receipt (GRN)";

  const matchBadge = linked.matchSummary

    ? matchStatusForSummary(linked.matchSummary.status)

    : null;



  const [dialogOpen, setDialogOpen] = useState(false);

  const [slotTarget, setSlotTarget] = useState<DossierLinkedDocument | null>(null);

  const [unlinkingId, setUnlinkingId] = useState<number | null>(null);



  const canManageLinks = Boolean(dossierId && onAddManualLink && onRemoveManualLink);



  function openLinkDialog(doc: DossierLinkedDocument | null) {

    setSlotTarget(doc);

    setDialogOpen(true);

  }



  async function handleUnlink(linkId: number) {

    if (!onRemoveManualLink) return;

    setUnlinkingId(linkId);

    try {

      await onRemoveManualLink(linkId);

    } finally {

      setUnlinkingId(null);

    }

  }



  return (

    <SectionBlock

      label="Linked documents"

      description="Required supporting documents on the same PO or SO reference. Manual links are display-only and do not satisfy dossier requirements."

    >

      <div className="dossier-panel">

        <div className="dossier-linked-header">

          <div className="dossier-linked-header__key">

            <Link2 className="h-3.5 w-3.5 text-primary shrink-0" aria-hidden />

            <div className="min-w-0">

              <div className="dossier-linked-header__kind">{linkageKindLabel(linked.linkageKind, salesBook)}</div>

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

                {requiredSupportingDocsLabel(present, required)}

              </StatusPill>

            ) : null}

          </div>

        </div>

        {linked.enforceBundle && !linked.linkageKey ? (
          <p
            className="mb-3 rounded-md border ds-warning-panel-strong px-3 py-2 text-xs ds-warning-text"
            data-testid="bundle-linkage-hint"
          >
            Enter or extract a valid {refShort} reference on this invoice to link required supporting
            documents ({supportingPair}). Manual links do not count toward dossier completeness.
          </p>
        ) : null}

        {linked.enforceBundle && linked.linkageKey && present < required ? (
          <p
            className="mb-3 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-foreground"
            data-testid="bundle-upload-hint"
          >
            Upload missing supporting documents for the required types, all using {refShort}{" "}
            <span className="font-mono font-semibold">{linked.linkageKey}</span>.
          </p>
        ) : null}



        {linked.documents.length === 0 ? (

          <p className="text-xs text-muted-foreground">

            No supporting documents required for this document type.

          </p>

        ) : (

          <div className="dossier-linked-grid">

            {linked.documents.map((doc) => (

              <LinkedDocumentCard

                key={doc.id}

                doc={doc}

                anchorInvoiceId={anchorInvoiceId}

                onOpenDocument={onOpenDocument}

                onLinkSlot={canManageLinks ? openLinkDialog : undefined}

                onUnlink={canManageLinks ? handleUnlink : undefined}

                unlinkingId={unlinkingId}

              />

            ))}

          </div>

        )}



        {canManageLinks ? (

          <div className="dossier-linked-manual-add">

            <Button

              type="button"

              size="sm"

              variant="outline"

              className="h-8 text-xs"

              onClick={() => openLinkDialog(null)}

            >

              <Plus className="h-3.5 w-3.5 mr-1" />

              Add manual link

            </Button>

          </div>

        ) : null}



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
            {linked.matchSummary.totalDeviation !== 0 ? (
              <div className="dossier-linked-match__row dossier-linked-match__row--emph">
                <span>Deviation</span>
                <span className="tnum">
                  {money(linked.matchSummary.totalDeviation, linked.matchSummary.currency)}
                </span>
              </div>
            ) : null}
          </div>
        ) : null}

        {linked.purchaseOrderId != null ? (

          <Link to="/purchases" className="dossier-linked-purchases-link">

            Open in Purchase Management →

          </Link>

        ) : null}

      </div>



      {canManageLinks && dossierId && onAddManualLink ? (

        <DossierManualLinkDialog

          open={dialogOpen}

          slotLabel={slotTarget?.label ?? null}

          anchorDossierId={dossierId}

          anchorInvoiceId={anchorInvoiceId ?? 0}

          onClose={() => {

            setDialogOpen(false);

            setSlotTarget(null);

          }}

          onSelect={async (linkedInvoiceId) => {

            await onAddManualLink({

              linkedInvoiceId,

              slotId: slotTarget?.id ?? null,

            });

            setSlotTarget(null);

          }}

        />

      ) : null}

    </SectionBlock>

  );

}


