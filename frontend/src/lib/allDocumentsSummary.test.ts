import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import {
  allDocumentsActionIssues,
  approvalStatusLabel,
  documentNature,
  formatDocDate,
  formatUploadedAt,
  parseUploadChannelTab,
  paymentStatusForNature,
  postingStatusLabel,
  toMatrixFlagType,
  vaultCellValue,
} from "@/lib/allDocumentsSummary";
import type { MatrixCell, MatrixStage } from "@/lib/matrix";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { KLASS_NON_TRANSACTIONAL, KLASS_TRANSACTIONAL } from "@/lib/documentTypeKlass";

function baseInvoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: 1,
    tenant_id: 1,
    status: "processed",
    vendor: "Acme",
    invoice_no: "INV-1",
    document_ref: "DOC-1",
    invoice_date: "2026-03-15",
    due_date: null,
    currency: "USD",
    subtotal: "100",
    gst: "0",
    total: "100",
    account_code: "600",
    account_name: "Office Supplies",
    email_sender: null,
    email_subject: null,
    raw_file_path: null,
    created_at: "2026-03-15T10:00:00Z",
    updated_at: "2026-03-15T10:00:00Z",
    document_type_code: "DT-02",
    route_target: "Purchase Management",
    evaluation_status: "auto_coded",
    gl_posting_applicable: true,
    published_to_ledger: false,
    capture_source: "upload",
    po_reference: null,
    so_reference: null,
    ...overrides,
  } as Invoice;
}

function cells(
  overrides: Partial<Record<MatrixStage, MatrixCell>> = {}
): Record<MatrixStage, MatrixCell> {
  const pending: MatrixCell = { state: "pending", ts: "—", detail: "—" };
  const done: MatrixCell = { state: "done", ts: "—", detail: "—" };
  return {
    Received: done,
    Parsed: done,
    Validated: done,
    Approved: done,
    Mapped: done,
    Posted: pending,
    ...overrides,
  };
}

const documentTypes: DocumentTypeDefinition[] = [
  {
    code: "DT-02",
    name: "Commercial invoice",
    enabled: true,
    klass: KLASS_TRANSACTIONAL,
    posting: "Yes",
    route_target: "Purchase Management",
    extraction_fields: [],
    bundle_mandatory: [],
    purchase_bundle_role: "",
    sales_bundle_role: "",
  } as DocumentTypeDefinition,
  {
    code: "DT-17",
    name: "Packing list",
    enabled: true,
    klass: KLASS_NON_TRANSACTIONAL,
    posting: "No",
    route_target: "Vault",
    extraction_fields: [],
    bundle_mandatory: [],
    purchase_bundle_role: "",
    sales_bundle_role: "",
  } as DocumentTypeDefinition,
];

describe("parseUploadChannelTab", () => {
  it("defaults missing/invalid to all", () => {
    expect(parseUploadChannelTab(null)).toBe("all");
    expect(parseUploadChannelTab("")).toBe("all");
    expect(parseUploadChannelTab("bogus")).toBe("all");
  });

  it("accepts known channel values", () => {
    expect(parseUploadChannelTab("all")).toBe("all");
    expect(parseUploadChannelTab("upload")).toBe("upload");
    expect(parseUploadChannelTab("email")).toBe("email");
    expect(parseUploadChannelTab("whatsapp")).toBe("whatsapp");
    expect(parseUploadChannelTab("viber")).toBe("viber");
    expect(parseUploadChannelTab("bank-feeds")).toBe("bank-feeds");
  });
});

describe("documentNature", () => {
  it("resolves klass from document type code", () => {
    expect(documentNature(baseInvoice({ document_type_code: "DT-02" }), documentTypes)).toBe(
      "Transactional"
    );
    expect(documentNature(baseInvoice({ document_type_code: "DT-17" }), documentTypes)).toBe(
      "Non-transactional"
    );
  });

  it("returns null when DT is missing", () => {
    expect(documentNature(baseInvoice({ document_type_code: null }), documentTypes)).toBeNull();
    expect(documentNature(baseInvoice({ document_type_code: "DT-99" }), documentTypes)).toBeNull();
  });
});

describe("formatDocDate", () => {
  it("formats ISO dates as DD MMM YY without timezone shift", () => {
    expect(formatDocDate("2026-03-15")).toBe("15 Mar 26");
    expect(formatDocDate("2026-03-15T12:00:00Z")).toBe("15 Mar 26");
    expect(formatDocDate("2026-09-11")).toBe("11 Sep 26");
    expect(formatDocDate("2026-08-27")).toBe("27 Aug 26");
    expect(formatDocDate("2026-09-05")).toBe("05 Sep 26");
    expect(formatDocDate(null)).toBe("—");
    expect(formatDocDate("")).toBe("—");
  });
});

describe("formatUploadedAt", () => {
  it("returns em dash for blank values", () => {
    expect(formatUploadedAt(null)).toBe("—");
    expect(formatUploadedAt("")).toBe("—");
  });

  it("returns the raw string when it is not a date", () => {
    expect(formatUploadedAt("not-a-date")).toBe("not-a-date");
  });

  it("formats an ISO instant as DD MMM YY, HH:MM in local time", () => {
    const iso = "2026-08-26T11:49:00.000Z";
    const dt = new Date(iso);
    const expected = `${String(dt.getDate()).padStart(2, "0")} ${
      ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][
        dt.getMonth()
      ]
    } ${String(dt.getFullYear()).slice(-2)}, ${String(dt.getHours()).padStart(2, "0")}:${String(
      dt.getMinutes()
    ).padStart(2, "0")}`;
    expect(formatUploadedAt(iso)).toBe(expected);
  });
});

describe("approvalStatusLabel / postingStatusLabel", () => {
  it("marks non-transactional as not required / N/A", () => {
    const inv = baseInvoice({
      document_type_code: "DT-17",
      gl_posting_applicable: false,
      route_target: "Vault",
    });
    expect(approvalStatusLabel(inv, cells(), documentTypes, "Non-transactional")).toBe(
      "Not required"
    );
    expect(postingStatusLabel(inv, cells(), documentTypes, "Non-transactional")).toBe("N/A");
  });

  it("uses pending_approval and published_to_ledger", () => {
    const pending = baseInvoice({ evaluation_status: "pending_approval" });
    expect(approvalStatusLabel(pending, cells(), documentTypes, "Transactional")).toBe("Pending");

    const posted = baseInvoice({ published_to_ledger: true });
    expect(postingStatusLabel(posted, cells(), documentTypes, "Transactional")).toBe("Posted");
  });
});

describe("paymentStatusForNature", () => {
  it("hides payment for non-transactional docs", () => {
    expect(paymentStatusForNature("Awaiting Payment", "Non-transactional")).toBe("—");
    expect(paymentStatusForNature("Paid", "Transactional")).toBe("Paid");
  });
});

describe("vaultCellValue", () => {
  it("prefers Filed over PO/SO refs", () => {
    expect(
      vaultCellValue({
        evaluation_status: "vision_vaulted",
        route_target: "Purchase Management",
        po_reference: "PO-1",
        so_reference: null,
      })
    ).toEqual({ kind: "vaulted", label: "Filed" });

    expect(
      vaultCellValue({
        evaluation_status: "auto_coded",
        route_target: "Vault",
        po_reference: null,
        so_reference: null,
      })
    ).toEqual({ kind: "vaulted", label: "Filed" });
  });

  it("falls back to PO then SO then empty", () => {
    expect(
      vaultCellValue({
        evaluation_status: "auto_coded",
        route_target: "Purchase Management",
        po_reference: "PO-9",
        so_reference: "SO-1",
      })
    ).toEqual({ kind: "po", label: "PO-9" });

    expect(
      vaultCellValue({
        evaluation_status: "auto_coded",
        route_target: "Sales Management",
        po_reference: null,
        so_reference: "SO-2",
      })
    ).toEqual({ kind: "so", label: "SO-2" });

    expect(
      vaultCellValue({
        evaluation_status: "auto_coded",
        route_target: "Purchase Management",
        po_reference: null,
        so_reference: null,
      })
    ).toEqual({ kind: "empty", label: "—" });
  });
});

describe("allDocumentsActionIssues", () => {
  it("uses matrix flag as primary when not Clean", () => {
    const result = allDocumentsActionIssues({
      inv: baseInvoice({ document_heading: "TAX INVOICE" }),
      flag: toMatrixFlagType("Anomaly Detected"),
      flagReason: "GL mapping unresolved — routed to suspense",
      cells: cells(),
      payment: "—",
      nature: "Transactional",
      documentTypes,
    });
    expect(result.primary?.label).toBe("Anomaly Detected");
    expect(result.primary?.detail).toContain("suspense");
  });

  it("flags missing type after parse settled", () => {
    const result = allDocumentsActionIssues({
      inv: baseInvoice({ document_heading: null, document_type_code: "DT-02" }),
      flag: "Clean",
      cells: cells(),
      payment: "—",
      nature: "Transactional",
      documentTypes,
    });
    expect(result.primary?.label).toBe("Type missing");
  });

  it("flags payment on hold when applicable", () => {
    const result = allDocumentsActionIssues({
      inv: baseInvoice({ document_heading: "INVOICE" }),
      flag: "Clean",
      cells: cells(),
      payment: "On Hold",
      nature: "Transactional",
      documentTypes,
    });
    expect(result.all.some((i) => i.label === "Payment on hold")).toBe(true);
  });

  it("surfaces duplicate conflict as primary notification", () => {
    const result = allDocumentsActionIssues({
      inv: baseInvoice({ document_heading: "INVOICE" }),
      flag: "Duplicate Suspected",
      cells: cells(),
      payment: "—",
      nature: "Transactional",
      documentTypes,
      conflictWith: "INV-100",
    });
    expect(result.primary?.label).toBe("Duplicate conflict");
    expect(result.primary?.detail).toContain("INV-100");
  });
});
