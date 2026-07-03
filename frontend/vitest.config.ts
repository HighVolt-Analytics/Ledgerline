import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "node",
    include: [
      "src/lib/documentTypeTemplates.test.ts",
      "src/lib/documentCompulsoryFields.test.ts",
      "src/lib/documentBundleConfig.test.ts",
      "src/lib/invoice.test.ts",
      "src/lib/matrixIssue.test.ts",
      "src/lib/processingOverrides.test.ts",
      "src/lib/salesRegister.test.ts",
      "src/lib/salesRegisterQueue.test.ts",
      "src/lib/collectionsQueue.test.ts",
      "src/lib/authSync.test.ts",
      "src/lib/tenantSession.test.ts",
    ],
  },
});
