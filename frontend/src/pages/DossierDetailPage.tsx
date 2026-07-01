import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import {
  DossierApprovalPanel,
  DossierLinkedDocumentsPanel,
  DossierPipelinePanel,
} from "@/components/dossiers/DossierDetailSections";
import { DossierOutcomeBadge, DossierTypeBadge } from "@/components/dossiers/DossierOutcomeBadge";
import {
  DossierOutcomeBanner,
  DossierSummaryStrip,
} from "@/components/dossiers/DossierSummaryStrip";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { PageEyebrowHeader } from "@/components/PageEyebrowHeader";
import { fetchDossierById, addDossierManualLink, removeDossierManualLink } from "@/lib/dossierApi";
import { firstPipelineFailure, isLegacyMockDossierId, type DossierSummary } from "@/lib/dossiers";

function DossierPlaybookRemedy({
  dossier,
  onOpenInvoice,
}: {
  dossier: DossierSummary;
  onOpenInvoice: () => void;
}) {
  const fail = firstPipelineFailure(dossier.pipeline);
  if (!fail || fail.stageId !== "bundle" || fail.state !== "fail") return null;

  const isLinkage = fail.exceptionCode === "LINKAGE_KEY_MISSING" || !dossier.poReference;
  const isBundle = fail.exceptionCode === "BUNDLE_INCOMPLETE";

  if (!isLinkage && !isBundle) return null;

  return (
    <div
      className="mb-4 rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm"
      data-testid="dossier-playbook-remedy"
    >
      <p className="font-medium text-foreground">Next step</p>
      {isLinkage ? (
        <p className="mt-1 text-muted-foreground">
          This dossier needs a PO linkage key for 3-way match. Capture the PO number, or{" "}
          {dossier.invoiceId ? (
            <button
              type="button"
              className="text-primary underline underline-offset-2"
              onClick={onOpenInvoice}
            >
              reclassify as Direct expense
            </button>
          ) : (
            "reclassify as Direct expense"
          )}{" "}
          if this is not a PO-backed invoice.
        </p>
      ) : (
        <p className="mt-1 text-muted-foreground">
          Upload PO and GRN supporting documents on the same PO number below, or open the
          invoice to complete the dossier.
        </p>
      )}
    </div>
  );
}

function captureLabel(channel: string): string {
  const base = channel.replace(/\s+capture$/i, "").trim();
  return `${base.toUpperCase()} capture`;
}

export function DossierDetailPage() {
  const { dossierId } = useParams<{ dossierId: string }>();
  const [dossier, setDossier] = useState<DossierSummary | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [drawerId, setDrawerId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const openLinkedDocument = (invoiceId: number) => {
    setDrawerId(invoiceId);
    setDrawerOpen(true);
  };

  const handleAddManualLink = async (body: {
    linkedInvoiceId: number;
    slotId?: string | null;
  }) => {
    if (!dossierId) return;
    const row = await addDossierManualLink(dossierId, body);
    setDossier(row);
  };

  const handleRemoveManualLink = async (linkId: number) => {
    if (!dossierId) return;
    const row = await removeDossierManualLink(dossierId, linkId);
    setDossier(row);
  };

  useEffect(() => {
    if (!dossierId) {
      setDossier(null);
      return;
    }
    if (isLegacyMockDossierId(dossierId)) {
      setDossier(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setDossier(undefined);
    setError(null);
    fetchDossierById(dossierId)
      .then((row) => {
        if (!cancelled) setDossier(row);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load dossier");
          setDossier(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [dossierId]);

  if (dossier === undefined) {
    return (
      <div className="space-y-4" data-testid="page-dossier-detail-loading">
        <Link to="/dossiers" className="dossier-back-link" data-testid="link-back-dossiers">
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to dossiers
        </Link>
        <p className="text-sm text-muted-foreground">Loading dossier…</p>
      </div>
    );
  }

  if (!dossier || error) {
    const legacyMock = dossierId && isLegacyMockDossierId(dossierId);
    return (
      <div className="space-y-4" data-testid="page-dossier-detail-missing">
        <Link to="/dossiers" className="dossier-back-link" data-testid="link-back-dossiers">
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to dossiers
        </Link>
        <p className="text-sm text-muted-foreground">
          {legacyMock
            ? `${dossierId} was a UI demo dossier. Open a live dossier from the list — IDs look like DOC-1, DOC-2, etc.`
            : (error ?? "Dossier not found.")}
        </p>
      </div>
    );
  }

  return (
    <div data-testid={`page-dossier-detail-${dossier.id}`}>
      <Link to="/dossiers" className="dossier-back-link" data-testid="link-back">
        <ArrowLeft className="h-3.5 w-3.5" />
        Dossiers
      </Link>

      <PageEyebrowHeader
        eyebrow={`${dossier.id} · ${dossier.documentTypeTitle}`}
        title={dossier.vendor}
        description={`${dossier.invoiceRef} · ${dossier.invoiceDate} · ${captureLabel(dossier.captureChannel)} · ${dossier.buyer}`}
        actions={
          <>
            <DossierTypeBadge code={dossier.documentTypeCode} title={dossier.documentTypeTitle} />
            <DossierOutcomeBadge outcome={dossier.outcome} />
          </>
        }
      />

      <DossierSummaryStrip dossier={dossier} />
      <DossierOutcomeBanner message={dossier.outcomeBanner} />
      <DossierPlaybookRemedy dossier={dossier} onOpenInvoice={() => {
        if (dossier.invoiceId) {
          setDrawerId(dossier.invoiceId);
          setDrawerOpen(true);
        }
      }} />

      <div className="dossier-detail-grid">
        <DossierPipelinePanel pipeline={dossier.pipeline} />
        <div className="dossier-detail-rail">
          <DossierLinkedDocumentsPanel
            linked={dossier.linkedDocuments}
            anchorInvoiceId={dossier.invoiceId}
            dossierId={dossier.id}
            onOpenDocument={openLinkedDocument}
            onAddManualLink={handleAddManualLink}
            onRemoveManualLink={handleRemoveManualLink}
          />
          <DossierApprovalPanel chain={dossier.approvalChain} />
        </div>
      </div>

      <InvoiceDetailDrawer
        invoiceId={drawerId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        initialTab="fields"
      />
    </div>
  );
}
