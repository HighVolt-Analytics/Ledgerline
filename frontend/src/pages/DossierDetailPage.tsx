import { Link, useParams } from "react-router-dom";

import { ArrowLeft } from "lucide-react";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {

  DossierApprovalPanel,

  DossierLinkedDocumentsPanel,

  DossierPipelinePanel,

} from "@/components/dossiers/DossierDetailSections";

import { DossierOutcomeBadge, DossierTypeBadge } from "@/components/dossiers/DossierOutcomeBadge";

import { DossierSummaryStrip } from "@/components/dossiers/DossierSummaryStrip";

import { LazyInvoiceDetailDrawer } from "@/components/LazyInvoiceDetailDrawer";

import { DossierDetailPageSkeleton } from "@/components/skeleton/PageSkeletons";

import { PageEyebrowHeader } from "@/components/PageEyebrowHeader";

import { useAuth } from "@/context/AuthContext";

import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";

import { fetchDossierById, addDossierManualLink, removeDossierManualLink } from "@/lib/dossierApi";

import {

  canRenderTenantOwnedUi,

  captureTenantFetchScope,

  handleTenantScopedLoadFailure,

  isTenantFetchScopeCurrent,

} from "@/lib/tenantSession";

import { firstPipelineFailure, isLegacyMockDossierId, type DossierSummary } from "@/lib/dossiers";

import { DOSSIER_PIPELINE_FOCUS_STAGE_EVENT } from "@/components/dossiers/DossierPipelineTimeline";



function scrollToFailedStage(stageId: string) {

  window.dispatchEvent(

    new CustomEvent(DOSSIER_PIPELINE_FOCUS_STAGE_EVENT, { detail: { stageId } })

  );

}



function captureLabel(channel: string): string {

  const base = channel.replace(/\s+capture$/i, "").trim();

  return `${base.toUpperCase()} capture`;

}



function dossierDescription(dossier: DossierSummary): string {

  const ref = dossier.invoiceRef?.trim();

  const parts = [dossier.counterpartyLabel ?? "Counterparty", dossier.id];

  if (ref && ref !== dossier.id) parts.push(ref);

  parts.push(dossier.invoiceDate, captureLabel(dossier.captureChannel), dossier.buyer);

  return parts.filter((part) => part && part !== "—").join(" · ");

}



function DossierBackButton({ testId = "link-back" }: { testId?: string }) {

  return (

    <Link

      to="/dossiers"

      className="dossier-detail-back"

      aria-label="Back"

      data-testid={testId}

    >

      <ArrowLeft className="h-4 w-4" />

    </Link>

  );

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



  const openInvoiceDrawer = () => {

    if (!dossier?.invoiceId) return;

    setDrawerId(dossier.invoiceId);

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



  useResetOnTenantChange(() => {

    setDossier(undefined);

    setError(null);

    setDrawerId(null);

    setDrawerOpen(false);

  });



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

    if (!canRenderTenantOwnedUi(tenantScope)) return;

    if (isLegacyMockDossierId(dossierId)) {

      setDossier(null);

      setError(null);

      return;

    }

    const scope = captureTenantFetchScope();

    const seq = ++loadSeq.current;

    setDossier(undefined);

    setError(null);

    void fetchDossierById(dossierId)

      .then((row) => {

        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;

        setDossier(row);

      })

      .catch((err) => {

        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;

        if (handleTenantScopedLoadFailure(err, { retry: () => undefined })) return;

        setError(err instanceof Error ? err.message : "Failed to load dossier");

        setDossier(null);

      });

  }, [dossierId, tenantScope]);



  useLayoutEffect(() => {

    if (!dossier) return;



    const scrollRoot = document.querySelector<HTMLElement>(".app-workspace__scroll");

    const pageHeader = document.querySelector<HTMLElement>(".page-top-sticky");

    if (!scrollRoot) return;



    const syncRailBounds = () => {

      const rootTop = scrollRoot.getBoundingClientRect().top;

      const headerBottom = pageHeader?.getBoundingClientRect().bottom ?? rootTop + 96;

      const top = Math.max(0, Math.round(headerBottom - rootTop + 8));

      const bottomPad = 16;

      scrollRoot.style.setProperty("--dossier-detail-rail-top", `${top}px`);

      scrollRoot.style.setProperty(

        "--dossier-detail-rail-max-height",

        `calc(100dvh - ${top + bottomPad}px)`

      );

    };



    syncRailBounds();

    const raf = requestAnimationFrame(syncRailBounds);

    scrollRoot.addEventListener("scroll", syncRailBounds, { passive: true });

    window.addEventListener("resize", syncRailBounds);



    return () => {

      cancelAnimationFrame(raf);

      scrollRoot.removeEventListener("scroll", syncRailBounds);

      window.removeEventListener("resize", syncRailBounds);

      scrollRoot.style.removeProperty("--dossier-detail-rail-top");

      scrollRoot.style.removeProperty("--dossier-detail-rail-max-height");

    };

  }, [dossier?.id]);



  if (!canRenderTenantOwnedUi(tenantScope) && dossier === undefined) {

    return <DossierDetailPageSkeleton />;

  }



  if (dossier === undefined) {

    return <DossierDetailPageSkeleton />;

  }



  if (!dossier || error) {

    const legacyMock = dossierId && isLegacyMockDossierId(dossierId);

    return (

      <div className="space-y-4" data-testid="page-dossier-detail-missing">

        <DossierBackButton testId="link-back-dossiers" />

        <p className="text-sm text-muted-foreground">

          {legacyMock

            ? `${dossierId} was a UI demo dossier. Open a live dossier from the list — IDs look like DOC-1, DOC-2, etc.`

            : (error ?? "Dossier not found.")}

        </p>

      </div>

    );

  }



  return (

    <div className="dossier-detail-page" data-testid={`page-dossier-detail-${dossier.id}`}>

      <PageEyebrowHeader

        leading={<DossierBackButton />}

        title={dossier.vendor}

        description={dossierDescription(dossier)}

        actions={

          <>

            <DossierOutcomeBadge outcome={dossier.outcome} />

            <DossierTypeBadge
              code={dossier.documentTypeCode ?? ""}
              title={
                (dossier.documentTypeTitle || "").trim() ||
                (dossier.classificationLabel || "").trim() ||
                undefined
              }
            />

          </>

        }

      />



      <DossierSummaryStrip

        dossier={dossier}

        onOpenInvoice={dossier.invoiceId ? openInvoiceDrawer : undefined}

        onJumpToFailure={() => {

          const fail = firstPipelineFailure(dossier.pipeline);

          if (fail) scrollToFailedStage(fail.stageId);

        }}

      />



      <div className="dossier-detail-grid">

        <DossierPipelinePanel
          pipeline={dossier.pipeline}
          routeTarget={dossier.routeTarget}
          pipelinePath={dossier.pipelinePath}
        />

        <div className="dossier-detail-rail-col">

          <div className="dossier-detail-rail">

            <DossierLinkedDocumentsPanel

              linked={dossier.linkedDocuments}

              anchorInvoiceId={dossier.invoiceId}

              dossierId={dossier.id}

              onOpenDocument={openLinkedDocument}

              onAddManualLink={handleAddManualLink}

              onRemoveManualLink={handleRemoveManualLink}

            />

            <DossierApprovalPanel
              chain={dossier.approvalChain}
              pipelinePath={dossier.pipelinePath}
            />

          </div>

        </div>

      </div>

      <LazyInvoiceDetailDrawer

        invoiceId={drawerId}

        open={drawerOpen}

        onClose={() => setDrawerOpen(false)}

      />

    </div>

  );

}

