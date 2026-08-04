import { describe, expect, it } from "vitest";
import type { InvoiceDetails } from "@/api/types";
import {
  additionalExtractedFieldKeys,
  buildDocumentContentProfile,
  buildPartyBlocks,
  buildPreviewFooter,
  contentHasFinancialBody,
  enrichLineItemsForPreview,
  enrichLineItemsFromDocumentText,
  filterLineItemsForPreview,
  formatPreviewMoney,
  invoiceTaxMeta,
  isCompactReceiptStyle,
  isNoiseLineItemRow,
  isSummaryLineDescription,
  isVisionHeaderPipelineSummary,
  lineItemColumnsForPreview,
  parseDocumentTaxRatePercent,
  previewFilename,
  resolveDocumentTaxRatePercent,
  sanitizeLineItemValues,
  shouldIncludeInSummary,
  shouldShowDocumentTextExcerpt,
  shouldSuppressField,
  taxMetaForCurrency,
  taxMetaForJurisdiction,
} from "@/lib/invoicePreview";
import { money } from "@/lib/format";
import { ROUTE_PURCHASE, ROUTE_SALES } from "@/lib/invoice";

const baseInvoice = {
  id: 42,
  currency: "AUD",
  status: "processed",
  line_items: [],
  journal_entries: [],
  has_stored_file: true,
} as InvoiceDetails;

describe("buildDocumentContentProfile", () => {
  it("includes line items from the invoice regardless of document type fields", () => {
    const inv = {
      ...baseInvoice,
      vendor: "Harbour View Hotel",
      line_items: [
        {
          id: 1,
          invoice_id: 42,
          description: "Catering package",
          qty: "10",
          unit_price: "50",
          amount: "500",
          tax_amount: null,
        },
      ],
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, { sourceKind: "upload" });
    expect(profile.lineItems).toHaveLength(1);
    expect(profile.lineItems[0]?.description).toBe("Catering package");
    expect(profile.lineItems[0]?.displayQty).toBe("10");
    expect(profile.lineItems[0]?.displayUnitPrice).toBe("50");
    expect(profile.lineItems[0]?.displayAmount).toBe("500");
    expect(profile.lineItemColumns).toEqual({
      showQty: true,
      showUnitPrice: true,
      showAmount: true,
    });
    expect(profile.counterparty).toBe("Harbour View Hotel");
    expect(contentHasFinancialBody(profile)).toBe(true);
    expect(profile.textExcerpt).toBeNull();
  });

  it("uses buyer as header counterparty on sales route", () => {
    const inv = {
      ...baseInvoice,
      route_target: ROUTE_SALES,
      vendor: "Tenant Org",
      extracted_fields: {
        buyer_name: "Harbour View Hotel",
        seller_name: "Tenant Org",
      },
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, { sourceKind: "upload" });
    expect(profile.counterparty).toBe("Harbour View Hotel");
    const buyerDup = profile.referenceDetails.find((r) => r.key === "buyer_name");
    expect(buyerDup).toBeUndefined();
  });

  it("shows seller as header on purchase route with structured party cards", () => {
    const inv = {
      ...baseInvoice,
      route_target: ROUTE_PURCHASE,
      vendor: "Spectra Innovations Pte Ltd",
      extracted_fields: {
        seller_name: "Spectra Innovations Pte Ltd",
        seller_tax_id: "199904042N",
        seller_address: "217 Henderson Road, Singapore",
        buyer_name: "RYANS COMPUTERS LIMITED",
        buyer_address: "Dhaka, Bangladesh",
        perspective: "purchase",
        llm_perspective: "purchase",
      },
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, { sourceKind: "upload" });
    expect(profile.counterparty).toBe("Spectra Innovations Pte Ltd");
    expect(profile.abn).toBeNull();
    expect(profile.referenceDetails.some((r) => r.key === "perspective")).toBe(false);
    expect(profile.parties.some((p) => p.key === "bill_from")).toBe(true);
    expect(profile.parties.some((p) => p.key === "bill_to")).toBe(true);

    const billFrom = profile.parties.find((p) => p.key === "bill_from");
    expect(billFrom?.name).toBeNull();
    expect(billFrom?.taxId).toBe("199904042N");
    expect(billFrom?.address).toContain("Singapore");

    const billTo = profile.parties.find((p) => p.key === "bill_to");
    expect(billTo?.name).toBe("RYANS COMPUTERS LIMITED");
    expect(billTo?.address).toContain("Dhaka");
  });

  it("omits duplicate billing_address when buyer party address matches", () => {
    const inv = {
      ...baseInvoice,
      route_target: ROUTE_PURCHASE,
      vendor: "Spectra Innovations Pte Ltd",
      billing_address: "238/1 Dhaka, Bangladesh",
      extracted_fields: {
        seller_name: "Spectra Innovations Pte Ltd",
        buyer_name: "RYANS COMPUTERS LIMITED",
        buyer_address: "238/1 Dhaka, Bangladesh",
        billing_address: "238/1 Dhaka, Bangladesh",
      },
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, { sourceKind: "upload" });
    expect(profile.parties.some((p) => p.key === "bill_to")).toBe(true);
    expect(
      profile.referenceDetails.some((r) => r.key === "billing_address")
    ).toBe(false);
  });

  it("reads billing_address from extracted_fields when no buyer party address", () => {
    const inv = {
      ...baseInvoice,
      extracted_fields: {
        billing_address: "238/1 Dhaka, Bangladesh",
      },
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, { sourceKind: "upload" });
    const billing = profile.referenceDetails.find((r) => r.key === "billing_address");
    expect(billing?.value).toContain("Dhaka");
  });

  it("buildPartyBlocks dedupes header counterparty name from bill from card", () => {
    const inv = {
      ...baseInvoice,
      route_target: ROUTE_PURCHASE,
      vendor: "Spectra Innovations Pte Ltd",
      extracted_fields: {
        seller_name: "Spectra Innovations Pte Ltd",
        seller_tax_id: "199904042N",
        buyer_name: "RYANS COMPUTERS LIMITED",
      },
    } as InvoiceDetails;

    const blocks = buildPartyBlocks(inv, [], []);
    expect(blocks.some((b) => b.key === "bill_from")).toBe(true);
    expect(blocks.some((b) => b.key === "bill_to")).toBe(true);
    const billFrom = blocks.find((b) => b.key === "bill_from");
    expect(billFrom?.name).toBeNull();
    expect(billFrom?.taxId).toBe("199904042N");
  });

  it("does not reorder party blocks when extractionFieldKeys is configured", () => {
    const inv = {
      ...baseInvoice,
      route_target: ROUTE_PURCHASE,
      vendor: "Spectra Innovations Pte Ltd",
      po_reference: "PO-99",
      extracted_fields: {
        seller_name: "Spectra Innovations Pte Ltd",
        seller_tax_id: "199904042N",
        buyer_name: "RYANS COMPUTERS LIMITED",
        buyer_address: "Dhaka",
      },
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, {
      sourceKind: "upload",
      extractionFieldKeys: ["po_reference", "buyer_name", "seller_name"],
    });
    expect(profile.parties[0]?.key).toBe("bill_from");
    expect(profile.parties[1]?.key).toBe("bill_to");
  });

  it("hides party section on compact receipt when only header vendor matches", () => {
    const inv = {
      ...baseInvoice,
      route_target: ROUTE_PURCHASE,
      vendor: "Cafe Express",
      total: "12.50",
      extracted_fields: { seller_name: "Cafe Express" },
      line_items: [
        {
          id: 1,
          invoice_id: 42,
          description: "Coffee",
          qty: null,
          unit_price: null,
          amount: "12.50",
          tax_amount: null,
        },
      ],
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, { sourceKind: "upload" });
    expect(isCompactReceiptStyle(profile)).toBe(true);
    expect(profile.parties).toHaveLength(0);
  });

  it("suppresses totals listed in absentFields", () => {
    const inv = {
      ...baseInvoice,
      total: "1200.00",
      subtotal: "1000.00",
      gst: "200.00",
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, {
      sourceKind: "upload",
      absentFields: ["total", "subtotal", "gst"],
    });

    expect(profile.totals.total).toBeUndefined();
    expect(profile.totals.subtotal).toBeUndefined();
    expect(profile.totals.tax).toBeUndefined();
    expect(contentHasFinancialBody(profile)).toBe(false);
  });

  it("shows OCR excerpt only when there is no financial body", () => {
    const inv = {
      ...baseInvoice,
      document_text: "Vendor statement for January 2026\nOpening balance $0",
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, { sourceKind: "email" });
    expect(profile.textExcerpt).toContain("Vendor statement");
    expect(contentHasFinancialBody(profile)).toBe(false);
  });

  it("hides OCR excerpt when line items or totals exist", () => {
    const inv = {
      ...baseInvoice,
      document_text: "INVOICE\nLine one",
      total: "99.00",
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, { sourceKind: "upload" });
    expect(profile.textExcerpt).toBeNull();
    expect(profile.totals.total).toBe("99.00");
  });

  it("uses document heading then document type label", () => {
    const withHeading = buildDocumentContentProfile(
      { ...baseInvoice, document_heading: "TAX INVOICE" } as InvoiceDetails,
      { sourceKind: "upload", documentTypeLabel: "PO goods invoice" }
    );
    expect(withHeading.heading).toBe("TAX INVOICE");

    const withLabel = buildDocumentContentProfile(baseInvoice, {
      sourceKind: "upload",
      documentTypeLabel: "Credit note",
    });
    expect(withLabel.heading).toBe("Credit note");
  });

  it("summary for vision header path shows header fields without OCR copy", () => {
    const inv = {
      ...baseInvoice,
      status: "exception",
      evaluation_status: "awaiting_classification",
      document_heading: "PACKING LIST",
      vendor: "Acme Supplies",
      invoice_no: "PL-9",
      invoice_date: "2026-03-15",
      total: "2500.00",
      currency: "AUD",
      document_text: null,
      extracted_fields: {
        canonical_document_type: "Packing List",
        other_reference: "REF-22",
      },
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, {
      sourceKind: "upload",
      summaryMode: true,
    });
    expect(profile.pipelineKind).toBe("vision_header");
    expect(profile.heading).toBe("PACKING LIST");
    expect(profile.counterparty).toBe("Acme Supplies");
    expect(profile.invoiceNo).toBe("PL-9");
    expect(profile.dates.issued).toBeTruthy();
    expect(profile.totals.total).toBe("2500.00");
    expect(profile.currency).toBe("AUD");
    expect(profile.textExcerpt).toBeNull();
    expect(profile.footer).toContain("vision header");
    expect(profile.referenceDetails.some((r) => r.key === "other_reference")).toBe(true);
  });

  it("detects vision header pipeline summary hold", () => {
    expect(
      isVisionHeaderPipelineSummary({
        evaluation_status: "awaiting_classification",
        document_text: null,
      } as InvoiceDetails)
    ).toBe(true);
    expect(
      isVisionHeaderPipelineSummary({
        evaluation_status: "awaiting_classification",
        document_text: "ocr body",
      } as InvoiceDetails)
    ).toBe(false);
  });

  it("keeps OCR pipeline kind when document text exists", () => {
    const inv = {
      ...baseInvoice,
      evaluation_status: "awaiting_classification",
      document_text: "TAX INVOICE\nVendor Acme",
      document_heading: "TAX INVOICE",
    } as InvoiceDetails;
    const profile = buildDocumentContentProfile(inv, { sourceKind: "upload", summaryMode: true });
    expect(profile.pipelineKind).toBe("ocr");
  });

  it("collects PO reference and custom extracted fields", () => {
    const inv = {
      ...baseInvoice,
      po_reference: "PO-7781",
      extracted_fields: { permit_no: "P-42" },
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, {
      sourceKind: "upload",
      extractionFieldKeys: ["po_reference", "permit_no"],
    });
    expect(profile.referenceDetails.map((row) => row.key)).toEqual(
      expect.arrayContaining(["po_reference", "permit_no"])
    );
  });

  it("shows extracted supplementary fields even when not in user extraction list", () => {
    const inv = {
      ...baseInvoice,
      po_reference: "PO-7781",
      cost_centre: "CC-9",
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, {
      sourceKind: "upload",
      extractionFieldKeys: ["vendor", "total"],
    });
    expect(profile.referenceDetails.some((row) => row.key === "po_reference")).toBe(true);
    expect(profile.referenceDetails.some((row) => row.key === "cost_centre")).toBe(true);
  });

  it("shows both structured summary and OCR when document_text is configured", () => {
    const inv = {
      ...baseInvoice,
      vendor: "Harbour View Hotel",
      document_text: "INVOICE\nCatering package x10",
      line_items: [
        {
          id: 1,
          invoice_id: 42,
          description: "Catering package",
          qty: "10",
          unit_price: null,
          amount: null,
          tax_amount: null,
        },
      ],
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, {
      sourceKind: "upload",
      extractionFieldKeys: ["vendor", "line_items", "document_text"],
    });
    expect(profile.lineItems).toHaveLength(1);
    expect(profile.textExcerpt).toContain("Catering package");
  });

  it("never shows empty user-defined fields (not mandatory)", () => {
    const profile = buildDocumentContentProfile(baseInvoice, {
      sourceKind: "upload",
      extractionFieldKeys: ["po_reference", "due_date", "line_items"],
    });
    expect(profile.referenceDetails).toHaveLength(0);
    expect(profile.dates.due).toBeUndefined();
    expect(profile.lineItems).toHaveLength(0);
  });

  it("still shows core extracted content when not in user extraction list", () => {
    const inv = {
      ...baseInvoice,
      vendor: "Harbour View Hotel",
      invoice_no: "INV-9",
      line_items: [
        {
          id: 1,
          invoice_id: 42,
          description: "Catering package",
          qty: "10",
          unit_price: null,
          amount: null,
          tax_amount: null,
        },
      ],
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, {
      sourceKind: "upload",
      extractionFieldKeys: ["vendor", "total"],
    });
    expect(profile.counterparty).toBe("Harbour View Hotel");
    expect(profile.invoiceNo).toBe("INV-9");
    expect(profile.lineItems).toHaveLength(1);
  });
});

describe("enrichLineItemsForPreview", () => {
  it("derives amount from qty × unit price", () => {
    const enriched = enrichLineItemsForPreview([
      {
        id: 1,
        invoice_id: 42,
        description: "Widget",
        qty: "10",
        unit_price: "50",
        amount: null,
        tax_amount: null,
      },
    ]);
    expect(enriched[0]?.displayAmount).toBe("500");
  });

  it("derives unit price from amount ÷ qty", () => {
    const enriched = enrichLineItemsForPreview([
      {
        id: 1,
        invoice_id: 42,
        description: "Widget",
        qty: "4",
        unit_price: null,
        amount: "100",
        tax_amount: null,
      },
    ]);
    expect(enriched[0]?.displayUnitPrice).toBe("25");
  });
});

describe("lineItemColumnsForPreview", () => {
  it("shows qty, unit price, and amount when present", () => {
    const items = enrichLineItemsForPreview([
      {
        id: 1,
        invoice_id: 42,
        description: "A",
        qty: "2",
        unit_price: "10",
        amount: "20",
        tax_amount: null,
      },
    ]);
    expect(lineItemColumnsForPreview(items)).toEqual({
      showQty: true,
      showUnitPrice: true,
      showAmount: true,
    });
  });
});

describe("isCompactReceiptStyle", () => {
  it("is true for a single simple line without qty or unit price", () => {
    const profile = buildDocumentContentProfile(
      {
        ...baseInvoice,
        line_items: [
          {
            id: 1,
            invoice_id: 42,
            description: "Lunch",
            qty: null,
            unit_price: null,
            amount: "12",
            tax_amount: null,
          },
        ],
      } as InvoiceDetails,
      { sourceKind: "upload" }
    );
    expect(isCompactReceiptStyle(profile)).toBe(true);
  });

  it("is false when lines have qty but no invoice total", () => {
    const profile = buildDocumentContentProfile(
      {
        ...baseInvoice,
        line_items: [
          {
            id: 1,
            invoice_id: 42,
            description: "Catering package",
            qty: "10",
            unit_price: null,
            amount: null,
            tax_amount: null,
          },
        ],
      } as InvoiceDetails,
      { sourceKind: "upload" }
    );
    expect(isCompactReceiptStyle(profile)).toBe(false);
  });

  it("is false when a total is present", () => {
    const profile = buildDocumentContentProfile(
      {
        ...baseInvoice,
        line_items: [
          {
            id: 1,
            invoice_id: 42,
            description: "Lunch",
            qty: "1",
            unit_price: "12",
            amount: "12",
            tax_amount: null,
          },
        ],
        total: "12.00",
      } as InvoiceDetails,
      { sourceKind: "upload" }
    );
    expect(isCompactReceiptStyle(profile)).toBe(false);
  });
});

describe("enrichLineItemsFromDocumentText", () => {
  it("fills missing unit price and amount from OCR row text", () => {
    const items = enrichLineItemsFromDocumentText(
      [
        {
          id: 1,
          invoice_id: 42,
          description: "Catering package",
          qty: "10",
          unit_price: null,
          amount: null,
          tax_amount: null,
        },
      ],
      "Description Qty Unit Amount\nCatering package 10 50.00 500.00"
    );
    expect(items[0]?.unit_price).toBe("50.00");
    expect(items[0]?.amount).toBe("500.00");
  });

  it("parses columnar OCR rows separated by wide spaces", () => {
    const items = enrichLineItemsFromDocumentText(
      [
        {
          id: 1,
          invoice_id: 42,
          description: "Western Digital 4TB HDD",
          qty: "80",
          unit_price: null,
          amount: null,
          tax_amount: null,
        },
      ],
      "Western Digital 4TB HDD    80    145.00    11600.00"
    );
    expect(items[0]?.unit_price).toBe("145.00");
    expect(items[0]?.amount).toBe("11600.00");
  });

  it("parses month-year descriptions without treating the year as qty", () => {
    const items = enrichLineItemsFromDocumentText(
      [
        {
          id: 1,
          invoice_id: 42,
          description: "EC2 Compute - May 2026",
          qty: "1",
          unit_price: null,
          amount: null,
          tax_amount: null,
        },
      ],
      "EC2 Compute - May 2026 1 $2,450.00 $245.00 $2,695.00"
    );
    expect(items[0]?.unit_price).toBe("2450.00");
    expect(items[0]?.amount).toBe("2695.00");
    expect(items[0]?.qty).toBe("1");
  });
});

describe("sanitizeLineItemValues", () => {
  it("clears invoice total incorrectly stored on a line row", () => {
    const items = sanitizeLineItemValues(
      [
        {
          id: 1,
          invoice_id: 42,
          description: "Sandisk 4TB SSD",
          qty: "15",
          unit_price: "1195.00",
          amount: "34410.95",
          tax_amount: null,
        },
      ],
      "34410.95"
    );
    expect(items[0]?.amount).toBeNull();
  });

  it("keeps amount for single product line equal to invoice total", () => {
    const items = sanitizeLineItemValues(
      [
        {
          id: 1,
          invoice_id: 712,
          description: "Sale of VER's",
          qty: "100000",
          unit_price: "0.70",
          amount: "70000.00",
          tax_amount: null,
        },
      ],
      "70000.00"
    );
    expect(items[0]?.amount).toBe("70000");
  });
});

describe("isNoiseLineItemRow", () => {
  it("keeps short high-qty product lines like Sale of VERs", () => {
    expect(isNoiseLineItemRow("Sale of VER's", "100000")).toBe(false);
  });

  it("still drops address bleed with high qty", () => {
    expect(isNoiseLineItemRow("Site Office Plot No.4", "51810")).toBe(true);
    expect(isNoiseLineItemRow("PH: 0432 423", "431")).toBe(true);
  });
});

describe("isSummaryLineDescription", () => {
  it("detects pallet total rows", () => {
    expect(isSummaryLineDescription("TOTAL NO. OF PALLET :")).toBe(true);
    expect(isSummaryLineDescription("Sandisk 4TB SSD")).toBe(false);
  });

  it("detects delivery note metadata labels", () => {
    expect(isSummaryLineDescription("Customer:")).toBe(true);
    expect(isSummaryLineDescription("Shipped Qty:")).toBe(true);
    expect(isSummaryLineDescription("Ship Date:")).toBe(true);
    expect(isSummaryLineDescription("Widget assembly kit")).toBe(false);
  });
});

describe("filterLineItemsForPreview", () => {
  it("drops vendor name duplicated as a line row", () => {
    const headerValues = new Set(["high volt analytics pty ltd"]);
    const filtered = filterLineItemsForPreview(
      [
        {
          id: 1,
          invoice_id: 42,
          description: "High Volt Analytics Pty Ltd",
          qty: "1",
          unit_price: "100",
          amount: "100",
          tax_amount: null,
        },
        {
          id: 2,
          invoice_id: 42,
          description: "SEO Services",
          qty: "1",
          unit_price: "35000",
          amount: "35000",
          tax_amount: null,
        },
      ],
      headerValues
    );
    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.description).toBe("SEO Services");
  });
});

describe("buildDocumentContentProfile summary line filtering", () => {
  it("excludes pallet total rows from preview line items", () => {
    const profile = buildDocumentContentProfile(
      {
        ...baseInvoice,
        line_items: [
          {
            id: 1,
            invoice_id: 42,
            description: "Sandisk 4TB SSD",
            qty: "15",
            unit_price: "1195",
            amount: "17925",
            tax_amount: null,
          },
          {
            id: 2,
            invoice_id: 42,
            description: "TOTAL NO. OF PALLET :",
            qty: "1",
            unit_price: "1195",
            amount: "34410.95",
            tax_amount: null,
          },
        ],
      } as InvoiceDetails,
      { sourceKind: "upload" }
    );
    expect(profile.lineItems).toHaveLength(1);
    expect(profile.lineItems[0]?.description).toBe("Sandisk 4TB SSD");
  });
});

describe("summaryMode", () => {
  it("shows all extracted values regardless of absentFields and extractionFieldKeys", () => {
    const inv = {
      ...baseInvoice,
      total: "1200.00",
      subtotal: "1000.00",
      gst: "200.00",
      po_reference: "PO-99",
    } as InvoiceDetails;

    const profile = buildDocumentContentProfile(inv, {
      sourceKind: "upload",
      summaryMode: true,
      absentFields: ["total", "subtotal", "gst", "po_reference"],
      extractionFieldKeys: ["vendor"],
    });

    expect(profile.totals.total).toBe("1200.00");
    expect(profile.totals.subtotal).toBe("1000.00");
    expect(profile.totals.tax).toBe("200.00");
    expect(profile.referenceDetails.some((row) => row.key === "po_reference")).toBe(true);
  });

  it("does not derive totals from line items in summaryMode", () => {
    const profile = buildDocumentContentProfile(
      {
        ...baseInvoice,
        line_items: [
          {
            id: 1,
            invoice_id: 42,
            description: "Item A",
            qty: "2",
            unit_price: "50",
            amount: "100",
            tax_amount: null,
          },
        ],
      } as InvoiceDetails,
      { sourceKind: "upload", summaryMode: true }
    );
    expect(profile.totals.subtotal).toBeUndefined();
    expect(profile.totals.total).toBeUndefined();
  });

  it("shows OCR excerpt for non-financial documents in summaryMode", () => {
    const profile = buildDocumentContentProfile(
      {
        ...baseInvoice,
        document_text: "Permit application\nPermit No: P-100",
        extracted_fields: { permit_no: "P-100" },
      } as InvoiceDetails,
      { sourceKind: "upload", summaryMode: true }
    );
    expect(profile.referenceDetails.some((row) => row.key === "permit_no")).toBe(true);
    expect(profile.textExcerpt).toContain("Permit application");
  });
});

describe("filterLineItemsForPreview", () => {
  it("keeps product lines that mention gst in the description", () => {
    const items = filterLineItemsForPreview([
      {
        id: 1,
        invoice_id: 42,
        description: "GST consulting services",
        qty: "1",
        unit_price: "350",
        amount: "350",
        tax_amount: null,
      },
    ]);
    expect(items).toHaveLength(1);
    expect(items[0]?.description).toBe("GST consulting services");
  });

  it("filters subtotal and metadata rows", () => {
    const items = filterLineItemsForPreview([
      {
        id: 1,
        invoice_id: 42,
        description: "Sub Total",
        qty: null,
        unit_price: null,
        amount: "500",
        tax_amount: null,
      },
      {
        id: 2,
        invoice_id: 42,
        description: "SEO Services",
        qty: "1",
        unit_price: "35000",
        amount: "35000",
        tax_amount: null,
      },
    ]);
    expect(items).toHaveLength(1);
    expect(items[0]?.description).toBe("SEO Services");
  });
});

describe("derived totals from line items", () => {
  it("sets subtotal and total when all line amounts are present", () => {
    const profile = buildDocumentContentProfile(
      {
        ...baseInvoice,
        line_items: [
          {
            id: 1,
            invoice_id: 42,
            description: "Item A",
            qty: "2",
            unit_price: "50",
            amount: "100",
            tax_amount: null,
          },
          {
            id: 2,
            invoice_id: 42,
            description: "Item B",
            qty: "1",
            unit_price: "25",
            amount: "25",
            tax_amount: null,
          },
        ],
      } as InvoiceDetails,
      { sourceKind: "upload" }
    );
    expect(profile.totals.subtotal).toBe("125");
    expect(profile.totals.total).toBe("125");
  });
});

describe("shouldIncludeInSummary", () => {
  it("shows fields with extracted values", () => {
    expect(shouldIncludeInSummary("po_reference", ["vendor"], [], true)).toBe(true);
    expect(shouldIncludeInSummary("po_reference", ["vendor"], [], false)).toBe(false);
  });

  it("respects absentFields even when a value exists", () => {
    expect(shouldIncludeInSummary("total", ["total"], ["total"], true)).toBe(false);
    expect(shouldIncludeInSummary("total", ["total"], ["total"], true, true)).toBe(true);
  });
});

describe("shouldShowDocumentTextExcerpt", () => {
  it("shows excerpt when there is no financial body", () => {
    expect(shouldShowDocumentTextExcerpt([], [], false, true)).toBe(true);
  });

  it("shows excerpt with financial body when document_text is configured", () => {
    expect(shouldShowDocumentTextExcerpt(["document_text"], [], true, true)).toBe(true);
    expect(shouldShowDocumentTextExcerpt(["vendor", "total"], [], true, true)).toBe(false);
  });
});

describe("shouldSuppressField", () => {
  it("returns true when key is in absentFields", () => {
    expect(shouldSuppressField("total", ["total", "gst"])).toBe(true);
    expect(shouldSuppressField("vendor", ["total"])).toBe(false);
  });
});

describe("buildPreviewFooter", () => {
  it("uses email attachment name and capture source", () => {
    const inv = {
      ...baseInvoice,
      email_attachment_name: "hotel-invoice.pdf",
      capture_source: "whatsapp",
    } as InvoiceDetails;
    expect(buildPreviewFooter(inv, "upload")).toBe(
      "hotel-invoice.pdf · captured via whatsapp"
    );
  });

  it("falls back to raw file path basename", () => {
    const inv = {
      ...baseInvoice,
      raw_file_path: "tenant/invoices/scan-001.pdf",
    } as InvoiceDetails;
    expect(previewFilename(inv)).toBe("scan-001.pdf");
    expect(buildPreviewFooter(inv, "email")).toBe("scan-001.pdf · captured via email");
  });
});

describe("formatPreviewMoney", () => {
  it("matches money() disambiguating symbols for drawer totals", () => {
    expect(formatPreviewMoney("99.00", "AUD", "en-SG")).toBe(money(99, "AUD", "en-SG"));
    expect(formatPreviewMoney("99.00", "SGD", "en-SG")).toBe(money(99, "SGD", "en-SG"));
    expect(formatPreviewMoney("99.00", "USD", "en-SG")).toBe(money(99, "USD", "en-SG"));
    expect(formatPreviewMoney("99.00", "AUD", "en-SG")).toContain("A$");
    expect(formatPreviewMoney("99.00", "USD", "en-SG")).toContain("US$");
  });

  it("matches money() for blank currency without inventing S$", () => {
    const preview = formatPreviewMoney("299.00", "", "en-SG");
    expect(preview).toBe(money(299, "", "en-SG"));
    expect(preview).toMatch(/299\.00/);
    expect(preview).not.toContain("S$");
  });
});

describe("invoiceTaxMeta / resolveDocumentTaxRatePercent", () => {
  it("uses extracted gst_rate, not country default", () => {
    expect(
      invoiceTaxMeta({
        currency: "INR",
        country: "IN",
        gst_rate: "12",
        subtotal: "100",
        gst: "18",
      })
    ).toEqual({ label: "GST", rate: 12 });
  });

  it("calculates rate from amounts when gst_rate missing", () => {
    expect(
      resolveDocumentTaxRatePercent({
        currency: "INR",
        gst_rate: null,
        subtotal: "1000",
        gst: "180",
      })
    ).toBe(18);
  });

  it("does not invent a rate from jurisdiction when amounts are missing", () => {
    expect(invoiceTaxMeta({ currency: "INR", country: "IN" })).toEqual({ label: "GST", rate: null });
    expect(taxMetaForCurrency("INR")).toEqual({ label: "Tax", rate: null });
    expect(taxMetaForJurisdiction({ country: "IN", statutory_tax_rate: 18 })).toEqual({
      label: "GST",
      rate: null,
    });
  });

  it("keeps tax label from country even when books currency differs", () => {
    expect(invoiceTaxMeta({ currency: "USD", country: "IN", gst_rate: "18" })).toEqual({
      label: "GST",
      rate: 18,
    });
  });

  it("parses percent strings and fraction rates", () => {
    expect(parseDocumentTaxRatePercent("10%")).toBe(10);
    expect(parseDocumentTaxRatePercent("0.1")).toBe(10);
  });
});

describe("additionalExtractedFieldKeys", () => {
  it("returns vision extras not in the DT extraction field list", () => {
    const inv = {
      ...baseInvoice,
      extracted_fields: {
        seller_abn: "29AAACC1206D1ZM",
        gst_rate: "18",
        canonical_document_type: "Tax Invoice",
        perspective: "purchase",
        vision_header_confidence: "0.95",
        vendor: "Acme",
      },
    } as InvoiceDetails;

    expect(additionalExtractedFieldKeys(inv, ["vendor", "invoice_no", "total"])).toEqual([
      "gst_rate",
      "seller_abn",
    ]);
  });

  it("hides type-suggest summary/hints from additional fields", () => {
    const inv = {
      ...baseInvoice,
      extracted_fields: {
        vendor: "Everest",
        document_summary: "Supplier tax invoice against PO-TEST-001.",
        document_role_hints: '{"has_po_reference":"true"}',
        vision_type_suggest_confidence: "0.99",
        seller_name: "Everest Furnishings Pty Ltd",
      },
    } as InvoiceDetails;

    expect(additionalExtractedFieldKeys(inv, ["vendor", "invoice_no", "total"])).toEqual([
      "seller_name",
    ]);
  });

  it("returns empty when all extracted keys are configured or internal", () => {
    const inv = {
      ...baseInvoice,
      extracted_fields: {
        vendor: "Acme",
        total: "100",
        canonical_document_type: "Invoice",
      },
    } as InvoiceDetails;

    expect(additionalExtractedFieldKeys(inv, ["vendor", "total"])).toEqual([]);
  });
});
