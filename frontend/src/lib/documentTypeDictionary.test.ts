import { describe, expect, it } from "vitest";
import {
  DICTIONARY_ENTRIES,
  DICTIONARY_VERSION,
  DOCUMENT_TYPE_TEMPLATES,
  getDictionaryValidationIssues,
} from "@/lib/documentTypeDictionary";

describe("document_type_dictionary.json", () => {
  it("loads 90 entries at version 1", () => {
    expect(DICTIONARY_VERSION).toBe(1);
    expect(DICTIONARY_ENTRIES).toHaveLength(90);
    expect(getDictionaryValidationIssues()).toEqual([]);
  });

  it("exposes one template per dictionary code plus custom", () => {
    const dictionaryTemplates = DOCUMENT_TYPE_TEMPLATES.filter((row) => row.id !== "custom");
    expect(dictionaryTemplates).toHaveLength(90);
    expect(new Set(dictionaryTemplates.map((row) => row.dictionaryCode)).size).toBe(90);
  });

  it("resolves canonical playbook/match/approval slugs on templates", () => {
    const sample = DOCUMENT_TYPE_TEMPLATES.find((row) => row.dictionaryCode === "LIB-001");
    expect(sample?.playbookProfile).toBe("standard_transactional");
    expect(sample?.matchMode).toBe("three_way_po_grn");
    expect(sample?.approvalMode).toBe("full_doa");
  });
});
