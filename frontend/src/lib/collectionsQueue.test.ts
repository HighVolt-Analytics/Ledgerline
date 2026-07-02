import { describe, expect, it } from "vitest";
import type { CollectionApi } from "@/api/types";
import {
  apiCollectionToRecord,
  collectionsByTab,
  collectionsOpenCount,
} from "@/lib/collectionsQueue";

const row = (overrides: Partial<CollectionApi> = {}): CollectionApi => ({
  id: 1,
  invoice_id: 10,
  customer: "Acme Pty Ltd",
  amount: 500,
  currency: "AUD",
  status: "queue",
  tab: "queue",
  due_date: "2026-02-01",
  received_date: null,
  failure_reason: null,
  ...overrides,
});

describe("collectionsQueue", () => {
  it("maps API rows to collection records", () => {
    const record = apiCollectionToRecord(row());
    expect(record.id).toBe("1");
    expect(record.customer).toBe("Acme Pty Ltd");
    expect(record.tab).toBe("queue");
  });

  it("counts open collections", () => {
    const count = collectionsOpenCount([
      row({ tab: "queue" }),
      row({ id: 2, tab: "awaiting" }),
      row({ id: 3, tab: "received" }),
    ]);
    expect(count).toBe(2);
  });

  it("filters by tab", () => {
    const records = [
      apiCollectionToRecord(row({ tab: "queue" })),
      apiCollectionToRecord(row({ id: 2, tab: "received" })),
    ];
    expect(collectionsByTab(records, "queue")).toHaveLength(1);
  });
});
