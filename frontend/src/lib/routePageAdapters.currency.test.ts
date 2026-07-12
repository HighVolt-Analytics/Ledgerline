import { describe, expect, it } from "vitest";
import { collectionsKpis, paymentsKpis } from "@/lib/routePageAdapters";
import type { CollectionRecord, PaymentRecord } from "@/lib/v4MockData";

const TZ = "Asia/Singapore";

describe("paymentsKpis totalByCurrency", () => {
  it("groups open queue amounts by payment currency", () => {
    const rows = [
      {
        id: "1",
        invoiceId: "10",
        vendor: "A",
        amount: 100,
        currency: "SGD",
        dueDate: "2099-01-01",
        tab: "queue",
        invoiceApprovedBy: "",
        invoiceApprovedByName: "",
        approvers: [],
      },
      {
        id: "2",
        invoiceId: "11",
        vendor: "B",
        amount: 50,
        currency: "USD",
        dueDate: "2099-01-01",
        tab: "awaiting",
        invoiceApprovedBy: "",
        invoiceApprovedByName: "",
        approvers: [],
      },
      {
        id: "3",
        invoiceId: "12",
        vendor: "C",
        amount: 999,
        currency: "AUD",
        dueDate: "2099-01-01",
        tab: "paid",
        invoiceApprovedBy: "",
        invoiceApprovedByName: "",
        approvers: [],
      },
    ] as PaymentRecord[];

    const kpis = paymentsKpis(rows, TZ);
    expect(kpis.totalByCurrency).toEqual({ SGD: 100, USD: 50 });
    expect(kpis.total).toBe(150);
  });
});

describe("collectionsKpis totalByCurrency", () => {
  it("groups open receivables by collection currency", () => {
    const rows = [
      {
        id: "1",
        invoiceId: "10",
        customer: "Acme",
        amount: 200,
        currency: "AUD",
        dueDate: "2099-01-01",
        tab: "queue",
      },
      {
        id: "2",
        invoiceId: "11",
        customer: "Beta",
        amount: 25,
        currency: "aud",
        dueDate: "2099-01-01",
        tab: "awaiting",
      },
      {
        id: "3",
        invoiceId: "12",
        customer: "Done",
        amount: 1,
        currency: "SGD",
        dueDate: "2099-01-01",
        tab: "received",
      },
    ] as CollectionRecord[];

    const kpis = collectionsKpis(rows, TZ);
    expect(kpis.totalByCurrency).toEqual({ AUD: 225 });
  });
});
