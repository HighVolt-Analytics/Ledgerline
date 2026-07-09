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
      "src/lib/approvalsBoard.test.ts",
      "src/lib/documentTypeTemplates.test.ts",
      "src/lib/documentTypeTemplateMeta.test.ts",
      "src/lib/regenerateClassifierPresets.test.ts",
      "src/lib/documentCompulsoryFields.test.ts",
      "src/lib/documentExtractionFields.test.ts",
      "src/lib/ruleBookSave.test.ts",
      "src/lib/documentBundleConfig.test.ts",
      "src/lib/documentPlaybookConfig.test.ts",
      "src/lib/documentTypeBundleValidation.test.ts",
      "src/lib/documentMatchRules.test.ts",
      "src/lib/documentTypePostTo.test.ts",
      "src/lib/invoice.test.ts",
      "src/lib/invoiceActions.test.ts",
      "src/lib/lineGlAccount.test.ts",
      "src/lib/classificationAuditDisplay.test.ts",
      "src/lib/invoicePreview.test.ts",
      "src/lib/matrixIssue.test.ts",
      "src/lib/processingOverrides.test.ts",
      "src/lib/salesRegister.test.ts",
      "src/lib/salesRegisterQueue.test.ts",
      "src/lib/collectionsQueue.test.ts",
      "src/lib/authSync.test.ts",
      "src/lib/authToken.test.ts",
      "src/lib/authReturnTo.test.ts",
      "src/lib/authSession.test.ts",
      "src/lib/tenantSession.test.ts",
      "src/lib/uploadColumnState.test.ts",
      "src/lib/pageTenantIsolation.test.ts",
      "src/lib/publicSignupRoutes.test.ts",
      "src/lib/signupForm.test.ts",
      "src/pages/SetupPage.test.tsx",
      "src/api/client.test.ts",
      "src/api/clientInvitePaths.test.ts",
    ],
  },
});
