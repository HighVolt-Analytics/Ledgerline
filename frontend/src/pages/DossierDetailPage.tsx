import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  DossierApprovalPanel,
  DossierLinkedDocumentsPanel,
  DossierPipelinePanel,
} from "@/components/dossiers/DossierDetailSections";
import { DossierOutcomeBadge, DossierTypeBadge } from "@/components/dossiers/DossierOutcomeBadge";
import { DossierStatusHero } from "@/components/dossiers/DossierStatusHero";
import { DossierSummaryStrip } from "@/components/dossiers/DossierSummaryStrip";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { PageEyebrowHeader } from "@/components/PageEyebrowHeader";
import { useAuth } from "@/context/AuthContext";
import { fetchDossierById, addDossierManualLink, removeDossierManualLink } from "@/lib/dossierApi";
import { firstPipelineFailure, isLegacyMockDossierId, type DossierSummary } from "@/lib/dossiers";

function scrollToFailedStage(stageId: string) {
  document.getElementById(`dossier-stage-${stageId}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function captureLabel(channel: string): string {
  const base = channel.replace(/\s+capture$/i, "").trim();
  return `${base.toUpperCase()} capture`;
}

export function DossierDetailPage() {
  const { dossierId } = useParams<{ dossierId: string }>();
  const { user } = useAuth();
  const tenantScope = user?.tenant_id ?? null;
  const loadSeq = useRef(0);
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

  useLayoutEffect(() => {
    setDossier(undefined);
    setError(null);
    setDrawerId(null);
    setDrawerOpen(false);
  }, [dossierId, tenantScope]);

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
    const seq = ++loadSeq.current;
    setDossier(undefined);
    setError(null);
    void fetchDossierById(dossierId)
      .then((row) => {
        if (seq !== loadSeq.current) return;
        setDossier(row);
      })
      .catch((err) => {
        if (seq !== loadSeq.current) return;
        setError(err instanceof Error ? err.message : "Failed to load dossier");
        setDossier(null);
      });
  }, [dossierId, tenantScope]);

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
        description={`${dossier.counterpartyLabel ?? "Counterparty"} · ${dossier.invoiceRef} · ${dossier.invoiceDate} · ${captureLabel(dossier.captureChannel)} · ${dossier.buyer}`}
        actions={
          <>
            <DossierTypeBadge code={dossier.documentTypeCode} title={dossier.documentTypeTitle} />
            <DossierOutcomeBadge outcome={dossier.outcome} />
          </>
        }
      />

      <DossierStatusHero
        dossier={dossier}
        onOpenInvoice={
          dossier.invoiceId
            ? () => {
                setDrawerId(dossier.invoiceId!);
                setDrawerOpen(true);
              }
            : undefined
        }
        onJumpToFailure={() => {
          const fail = firstPipelineFailure(dossier.pipeline);
          if (fail) scrollToFailedStage(fail.stageId);
        }}
      />
      <DossierSummaryStrip dossier={dossier} />

      <div className="dossier-detail-grid">
        <DossierPipelinePanel pipeline={dossier.pipeline} routeTarget={dossier.routeTarget} />
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
