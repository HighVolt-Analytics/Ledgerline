import type { DossierLinkedDocument, DossierLinkedDocuments } from "@/lib/dossierLinkedDocuments";
import { isSalesLinkedDocuments } from "@/lib/dossierLinkedDocuments";
import { DOSSIER_PIPELINE_PHASES, type DossierPipelinePhaseId } from "@/lib/dossiers";

export type DossierPhaseDocumentBinding = {
  phaseId: DossierPipelinePhaseId;
  phaseLabel: string;
  documents: DossierLinkedDocument[];
  headline: string;
  detail: string;
};

function findAnchor(docs: DossierLinkedDocument[]): DossierLinkedDocument | undefined {
  return (
    docs.find((doc) => doc.isAnchor) ??
    docs.find(
      (doc) =>
        (doc.purchaseBundleRole || "").toLowerCase() === "invoice" ||
        (doc.salesBundleRole || "").toLowerCase() === "invoice"
    )
  );
}

function docByRole(
  docs: DossierLinkedDocument[],
  role: string
): DossierLinkedDocument | undefined {
  const token = role.toLowerCase();
  return docs.find(
    (doc) =>
      (doc.purchaseBundleRole || "").toLowerCase() === token ||
      (doc.salesBundleRole || "").toLowerCase() === token
  );
}

function refList(docs: DossierLinkedDocument[]): string {
  const refs = docs.map((doc) => doc.documentRef?.trim()).filter(Boolean) as string[];
  if (refs.length === 0) return "Not linked";
  return refs.join(" · ");
}

function bindingForPhase(
  phaseId: DossierPipelinePhaseId,
  phaseLabel: string,
  documents: DossierLinkedDocument[],
  headline: string,
  detail: string
): DossierPhaseDocumentBinding {
  return { phaseId, phaseLabel, documents, headline, detail };
}

/** Map Capture → Process → Approve → Ledger → Finish to dossier linked documents. */
export function dossierPhaseDocumentBindings(
  linked: DossierLinkedDocuments
): DossierPhaseDocumentBinding[] {
  const docs = linked.documents;
  const anchor = findAnchor(docs);
  const salesBook = isSalesLinkedDocuments(linked);

  if (salesBook) {
    const so = docByRole(docs, "so");
    const dn = docByRole(docs, "dn");
    const processDocs = [so, dn].filter(Boolean) as DossierLinkedDocument[];
    const anchorDocs = anchor ? [anchor] : [];

    return DOSSIER_PIPELINE_PHASES.map((phase) => {
      if (phase.id === "capture") {
        return bindingForPhase(
          phase.id,
          phase.label,
          anchorDocs,
          anchor?.label ?? "Captured document",
          anchor?.documentRef?.trim() || "This dossier"
        );
      }
      if (phase.id === "process") {
        return bindingForPhase(
          phase.id,
          phase.label,
          processDocs,
          "SO · DN",
          refList(processDocs)
        );
      }
      return bindingForPhase(
        phase.id,
        phase.label,
        anchorDocs,
        anchor?.label ?? "Commercial invoice",
        anchor?.documentRef?.trim() || "Approval pipeline document"
      );
    });
  }

  const po = docByRole(docs, "po");
  const grn = docByRole(docs, "grn");
  const processDocs = [po, grn].filter(Boolean) as DossierLinkedDocument[];
  const anchorDocs = anchor ? [anchor] : [];

  return DOSSIER_PIPELINE_PHASES.map((phase) => {
    if (phase.id === "capture") {
      return bindingForPhase(
        phase.id,
        phase.label,
        anchorDocs,
        anchor?.label ?? "Captured document",
        anchor?.documentRef?.trim() || "This dossier"
      );
    }
    if (phase.id === "process") {
      return bindingForPhase(
        phase.id,
        phase.label,
        processDocs,
        "PO · GRN",
        refList(processDocs)
      );
    }
    return bindingForPhase(
      phase.id,
      phase.label,
      anchorDocs,
      anchor?.label ?? "Commercial invoice",
      anchor?.documentRef?.trim() || "Approval pipeline document"
    );
  });
}

export function dossierPhaseBinding(
  linked: DossierLinkedDocuments,
  phaseId: DossierPipelinePhaseId
): DossierPhaseDocumentBinding | undefined {
  return dossierPhaseDocumentBindings(linked).find((row) => row.phaseId === phaseId);
}

/** Invoice row to open in the approval-style drawer for this phase. */
export function invoiceIdForPhaseBinding(
  binding: DossierPhaseDocumentBinding | undefined,
  anchorInvoiceId?: number | null
): number | null {
  if (!binding) return null;
  for (const doc of binding.documents) {
    const id = invoiceIdForLinkedDocument(doc, anchorInvoiceId);
    if (id) return id;
  }
  return null;
}

export function invoiceIdForLinkedDocument(
  doc: DossierLinkedDocument,
  anchorInvoiceId?: number | null
): number | null {
  if (doc.invoiceId) return doc.invoiceId;
  if (doc.manualLink?.invoiceId) return doc.manualLink.invoiceId;
  if (doc.isAnchor && anchorInvoiceId) return anchorInvoiceId;
  return null;
}

export function phaseDocumentCardHeadline(doc: DossierLinkedDocument): string {
  const code = doc.documentTypeCode?.trim();
  if (code) return code.toUpperCase();
  return doc.label.toUpperCase();
}

export function phaseDocumentCardRef(doc: DossierLinkedDocument): string {
  if (doc.present || doc.manualLink) {
    return doc.manualLink?.documentRef?.trim() || doc.documentRef?.trim() || "—";
  }
  return "Not linked";
}

export function isDossierPipelinePhaseId(value: string): value is DossierPipelinePhaseId {
  return DOSSIER_PIPELINE_PHASES.some((phase) => phase.id === value);
}
