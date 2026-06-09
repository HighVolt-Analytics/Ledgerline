import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { PageLoader } from "@/components/PageLoader";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { SetupPage } from "@/pages/SetupPage";

const ApprovalsPage = lazy(() =>
  import("@/pages/ApprovalsPage").then((m) => ({ default: m.ApprovalsPage }))
);
const BillingPage = lazy(() =>
  import("@/pages/BillingPage").then((m) => ({ default: m.BillingPage }))
);
const InboxPage = lazy(() =>
  import("@/pages/InboxPage").then((m) => ({ default: m.InboxPage }))
);
const IntegrationsPage = lazy(() =>
  import("@/pages/IntegrationsPage").then((m) => ({ default: m.IntegrationsPage }))
);
const InvoiceDetailPage = lazy(() =>
  import("@/pages/InvoiceDetailPage").then((m) => ({ default: m.InvoiceDetailPage }))
);
const AllInvoicesPage = lazy(() =>
  import("@/pages/AllInvoicesPage").then((m) => ({ default: m.AllInvoicesPage }))
);
const MatrixPage = lazy(() =>
  import("@/pages/MatrixPage").then((m) => ({ default: m.MatrixPage }))
);
const ReconciliationPage = lazy(() =>
  import("@/pages/ReconciliationPage").then((m) => ({ default: m.ReconciliationPage }))
);
const ReportsPage = lazy(() =>
  import("@/pages/ReportsPage").then((m) => ({ default: m.ReportsPage }))
);
const RulesPage = lazy(() =>
  import("@/pages/RulesPage").then((m) => ({ default: m.RulesPage }))
);
const SettingsPage = lazy(() =>
  import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage }))
);
const VaultPage = lazy(() =>
  import("@/pages/VaultPage").then((m) => ({ default: m.VaultPage }))
);
const VendorsPage = lazy(() =>
  import("@/pages/VendorsPage").then((m) => ({ default: m.VendorsPage }))
);
const TeamExpensesPage = lazy(() =>
  import("@/pages/TeamExpensesPage").then((m) => ({ default: m.TeamExpensesPage }))
);
const PurchaseManagementPage = lazy(() =>
  import("@/pages/PurchaseManagementPage").then((m) => ({
    default: m.PurchaseManagementPage,
  }))
);
const PaymentsPage = lazy(() =>
  import("@/pages/PaymentsPage").then((m) => ({ default: m.PaymentsPage }))
);
const LedgerLinkPage = lazy(() =>
  import("@/pages/LedgerLinkPage").then((m) => ({ default: m.LedgerLinkPage }))
);

function LazyPage({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<PageLoader />}>{children}</Suspense>;
}

const routerBasename = (
  import.meta.env.VITE_BASE_PATH ?? (import.meta.env.PROD ? "/ledgerlink/" : "/")
).replace(/\/$/, "");

export default function App() {
  return (
    <BrowserRouter basename={routerBasename || undefined}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route
              path="inbox"
              element={
                <LazyPage>
                  <InboxPage />
                </LazyPage>
              }
            />
            <Route
              path="team-expenses"
              element={
                <LazyPage>
                  <TeamExpensesPage />
                </LazyPage>
              }
            />
            <Route
              path="purchases"
              element={
                <LazyPage>
                  <PurchaseManagementPage />
                </LazyPage>
              }
            />
            <Route
              path="matrix"
              element={
                <LazyPage>
                  <MatrixPage />
                </LazyPage>
              }
            />
            <Route
              path="approvals"
              element={
                <LazyPage>
                  <ApprovalsPage />
                </LazyPage>
              }
            />
            <Route
              path="vendors"
              element={
                <LazyPage>
                  <VendorsPage />
                </LazyPage>
              }
            />
            <Route
              path="rules"
              element={
                <LazyPage>
                  <RulesPage />
                </LazyPage>
              }
            />
            <Route
              path="vault"
              element={
                <LazyPage>
                  <VaultPage />
                </LazyPage>
              }
            />
            <Route
              path="payments"
              element={
                <LazyPage>
                  <PaymentsPage />
                </LazyPage>
              }
            />
            <Route
              path="ledger-link"
              element={
                <LazyPage>
                  <LedgerLinkPage />
                </LazyPage>
              }
            />
            <Route
              path="reconciliation"
              element={
                <LazyPage>
                  <ReconciliationPage />
                </LazyPage>
              }
            />
            <Route
              path="reports"
              element={
                <LazyPage>
                  <ReportsPage />
                </LazyPage>
              }
            />
            <Route
              path="billing"
              element={
                <LazyPage>
                  <BillingPage />
                </LazyPage>
              }
            />
            <Route
              path="integrations"
              element={
                <LazyPage>
                  <IntegrationsPage />
                </LazyPage>
              }
            />
            <Route
              path="settings"
              element={
                <LazyPage>
                  <SettingsPage />
                </LazyPage>
              }
            />
            <Route
              path="invoices"
              element={
                <LazyPage>
                  <AllInvoicesPage />
                </LazyPage>
              }
            />
            <Route
              path="invoices/:id"
              element={
                <LazyPage>
                  <InvoiceDetailPage />
                </LazyPage>
              }
            />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
