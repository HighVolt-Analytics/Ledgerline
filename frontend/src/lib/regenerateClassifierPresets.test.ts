/**
 * Regenerate shipped classifier JSON when templates change:
 *   REGEN_CLASSIFIERS=1 npx vitest run src/lib/regenerateClassifierPresets.test.ts
 */

import { writeFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import classifierPresets from "@/lib/documentTypeClassifierPresets.json";
import { shippedClassifierPresets } from "@/lib/documentTypeTemplates";

describe("shipped classifier presets", () => {
  it("match template-derived simple match/exclude rules", () => {
    const expected = shippedClassifierPresets();
    if (process.env.REGEN_CLASSIFIERS === "1") {
      const target = path.resolve("src/lib/documentTypeClassifierPresets.json");
      writeFileSync(target, `${JSON.stringify(expected, null, 2)}\n`, "utf-8");
      const backend = path.resolve(
        "../backend/data/document_type_classifiers.json"
      );
      writeFileSync(backend, `${JSON.stringify(expected, null, 2)}\n`, "utf-8");
    }
    expect(classifierPresets).toEqual(expected);
  });
});
