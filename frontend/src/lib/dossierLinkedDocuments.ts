/**
 * Dossier linked documents — mirrors playbook bundle_mandatory / purchase_dossier API.
 * UI model until GET /api/dossiers/{id} ships.
 */

export type DossierLinkageKind = "po_reference" | "shipment_ref" | "contract_ref" | "standalone";

export type DossierDocumentSource = "erp_register" | "upload" | "email_capture" | "edi";

export type DossierBundleRequirement = "mandatory" | "conditional" | "advisory";

export type DossierPurchaseBundleRole = "" | "po" | "grn" | "invoice";

export type DossierLinkedDocument = {
  id: string;
  documentTypeCode: string;
  label: string;
  documentRef: string | null;
  present: boolean;
  requirement: DossierBundleRequirement;
  purchaseBundleRole?: DossierPurchaseBundleRole;
  source?: DossierDocumentSource;
  /** Sibling dossier when the doc is on file (mock id until API). */
  linkedDossierId?: string | null;
  isAnchor?: boolean;
  hasFile?: boolean;
  linkageDetail?: string;
};

export type DossierMatchSummary = {
  status: string;
  poValue: number;
  invoiceTotal: number;
  deviation: number;
  currency: string;
};

export type DossierLinkedDocuments = {
  linkageKind: DossierLinkageKind;
  linkageKey: string | null;
  linkageLabel: string;
  enforceBundle: boolean;
  conditionalAdvisories: string[];
  documents: DossierLinkedDocument[];
  matchSummary?: DossierMatchSummary;
  purchaseOrderId?: number | null;
};

export function linkageKindLabel(kind: DossierLinkageKind): string {
  if (kind === "po_reference") return "PO linkage key";
  if (kind === "shipment_ref") return "Shipment linkage key";
  if (kind === "contract_ref") return "Contract linkage key";
  return "Standalone document";
}

export function documentSourceLabel(source: DossierDocumentSource): string {
  if (source === "erp_register") return "ERP register";
  if (source === "upload") return "Upload";
  if (source === "email_capture") return "Email capture";
  return "EDI";
}

export function requirementLabel(req: DossierBundleRequirement): string {
  if (req === "mandatory") return "Mandatory";
  if (req === "conditional") return "Conditional";
  return "Advisory";
}

export function linkedDocumentCounts(linked: DossierLinkedDocuments): {
  present: number;
  required: number;
} {
  const mandatory = linked.documents.filter((doc) => doc.requirement === "mandatory");
  return {
    required: mandatory.length,
    present: mandatory.filter((doc) => doc.present).length,
  };
}

function doc(
  partial: Omit<DossierLinkedDocument, "id"> & { id?: string }
): DossierLinkedDocument {
  return {
    id: partial.id ?? `${partial.documentTypeCode}-${partial.purchaseBundleRole || "doc"}`,
    hasFile: partial.present,
    ...partial,
  };
}

/** DT-01 PO goods — PO + GRN + commercial invoice on shared po_reference. */
export function poGoodsLinkedDocuments(opts: {
  poReference: string;
  anchorDossierId: string;
  anchorRef: string;
  po: { present: boolean; ref?: string | null; dossierId?: string | null; source?: DossierDocumentSource };
  grn: { present: boolean; ref?: string | null; dossierId?: string | null; source?: DossierDocumentSource };
  match?: DossierMatchSummary;
  purchaseOrderId?: number | null;
}): DossierLinkedDocuments {
  return {
    linkageKind: "po_reference",
    linkageKey: opts.poReference,
    linkageLabel: `Linked on ${opts.poReference}`,
    enforceBundle: true,
    conditionalAdvisories: [],
    purchaseOrderId: opts.purchaseOrderId ?? null,
    matchSummary: opts.match,
    documents: [
      doc({
        documentTypeCode: "DT-14",
        label: "Purchase order",
        documentRef: opts.po.present ? (opts.po.ref ?? opts.poReference) : null,
        present: opts.po.present,
        requirement: "mandatory",
        purchaseBundleRole: "po",
        source: opts.po.source ?? "erp_register",
        linkedDossierId: opts.po.dossierId ?? null,
        linkageDetail: opts.po.present ? `PO register · ${opts.poReference}` : "VR-PB01 required",
      }),
      doc({
        documentTypeCode: "DT-15",
        label: "Goods receipt",
        documentRef: opts.grn.present ? (opts.grn.ref ?? null) : null,
        present: opts.grn.present,
        requirement: "mandatory",
        purchaseBundleRole: "grn",
        source: opts.grn.source ?? "erp_register",
        linkedDossierId: opts.grn.dossierId ?? null,
        linkageDetail: opts.grn.present ? `GRN tied to ${opts.poReference}` : "VR-PB01 required",
      }),
      doc({
        id: "anchor-invoice",
        documentTypeCode: "DT-01",
        label: "Commercial invoice",
        documentRef: opts.anchorRef,
        present: true,
        requirement: "mandatory",
        purchaseBundleRole: "invoice",
        source: "edi",
        linkedDossierId: opts.anchorDossierId,
        isAnchor: true,
        hasFile: true,
        linkageDetail: "This dossier",
      }),
    ],
  };
}

/** DT-10 import dossier — shipment ref + multi-DT mandatory bundle. */
export function importLinkedDocuments(opts: {
  shipmentRef: string;
  anchorDossierId: string;
  anchorRef: string;
  members: Array<{
    code: string;
    label: string;
    ref?: string | null;
    present: boolean;
    requirement?: DossierBundleRequirement;
    source?: DossierDocumentSource;
    dossierId?: string | null;
  }>;
  advisories?: string[];
}): DossierLinkedDocuments {
  return {
    linkageKind: "shipment_ref",
    linkageKey: opts.shipmentRef,
    linkageLabel: `Import dossier · ${opts.shipmentRef}`,
    enforceBundle: true,
    conditionalAdvisories: opts.advisories ?? [],
    documents: opts.members.map((member) =>
      doc({
        documentTypeCode: member.code,
        label: member.label,
        documentRef: member.present ? (member.ref ?? null) : null,
        present: member.present,
        requirement: member.requirement ?? "mandatory",
        source: member.source,
        linkedDossierId:
          member.dossierId ?? (member.code === "DT-10" ? opts.anchorDossierId : null),
        isAnchor: member.code === "DT-10",
        linkageDetail: member.present ? `Shipment ${opts.shipmentRef}` : "VR-PB02 mandatory",
      })
    ),
  };
}

/** Non-PO or single-doc dossiers. */
export function standaloneLinkedDocuments(opts: {
  anchorDossierId: string;
  code: string;
  label: string;
  ref: string;
  source?: DossierDocumentSource;
  supporting?: Array<{
    code: string;
    label: string;
    ref: string;
    present: boolean;
    requirement?: DossierBundleRequirement;
  }>;
  contractRef?: string | null;
}): DossierLinkedDocuments {
  const supporting = opts.supporting ?? [];
  return {
    linkageKind: opts.contractRef ? "contract_ref" : "standalone",
    linkageKey: opts.contractRef ?? null,
    linkageLabel: opts.contractRef
      ? `Contract ${opts.contractRef}`
      : "No external linkage key",
    enforceBundle: supporting.some((s) => s.requirement === "mandatory"),
    conditionalAdvisories: [],
    documents: [
      ...supporting.map((member) =>
        doc({
          documentTypeCode: member.code,
          label: member.label,
          documentRef: member.present ? member.ref : null,
          present: member.present,
          requirement: member.requirement ?? "mandatory",
          linkedDossierId: null,
        })
      ),
      doc({
        id: "anchor",
        documentTypeCode: opts.code,
        label: opts.label,
        documentRef: opts.ref,
        present: true,
        requirement: "mandatory",
        source: opts.source ?? "upload",
        linkedDossierId: opts.anchorDossierId,
        isAnchor: true,
        hasFile: true,
        linkageDetail: "This dossier",
      }),
    ],
  };
}

/** Pipeline halted before bundle assembly (e.g. duplicate file). */
export function haltedLinkedDocuments(opts: {
  poReference?: string | null;
  anchorDossierId: string;
  anchorRef: string;
  reason: string;
}): DossierLinkedDocuments {
  const poRef = opts.poReference?.trim() || null;
  if (poRef) {
    return {
      linkageKind: "po_reference",
      linkageKey: poRef,
      linkageLabel: `Linked on ${poRef} (not assembled)`,
      enforceBundle: true,
      conditionalAdvisories: [],
      documents: [
        doc({
          documentTypeCode: "DT-14",
          label: "Purchase order",
          documentRef: null,
          present: false,
          requirement: "mandatory",
          purchaseBundleRole: "po",
          linkageDetail: opts.reason,
        }),
        doc({
          documentTypeCode: "DT-15",
          label: "Goods receipt",
          documentRef: null,
          present: false,
          requirement: "mandatory",
          purchaseBundleRole: "grn",
          linkageDetail: opts.reason,
        }),
        doc({
          id: "anchor-invoice",
          documentTypeCode: "DT-01",
          label: "Commercial invoice",
          documentRef: opts.anchorRef,
          present: true,
          requirement: "mandatory",
          purchaseBundleRole: "invoice",
          isAnchor: true,
          hasFile: true,
          linkageDetail: opts.reason,
          linkedDossierId: opts.anchorDossierId,
        }),
      ],
    };
  }
  return {
    linkageKind: "standalone",
    linkageKey: null,
    linkageLabel: "Bundle not assembled",
    enforceBundle: false,
    conditionalAdvisories: [],
    documents: [
      doc({
        id: "anchor",
        documentTypeCode: "DT-01",
        label: "Commercial invoice",
        documentRef: opts.anchorRef,
        present: true,
        requirement: "mandatory",
        isAnchor: true,
        hasFile: true,
        linkageDetail: opts.reason,
        linkedDossierId: opts.anchorDossierId,
      }),
    ],
  };
}
