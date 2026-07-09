import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ModuleRoute } from "@/components/ModuleRoute";
import { OnboardingGate } from "@/components/OnboardingGate";
import { Layout } from "@/components/Layout";
import { SuperAdminLayout } from "@/components/SuperAdminLayout";
import { SuperAdminRoute } from "@/components/SuperAdminRoute";
import { TenantRoute } from "@/components/TenantRoute";
import { PageLoader } from "@/components/PageLoader";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { getRouterBasename } from "@/lib/routerBasename";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { LoginOauthCallbackPage } from "@/pages/LoginOauthCallbackPage";
import { SignupPage } from "@/pages/SignupPage";
import { SuperAdminEmbedPage } from "@/pages/SuperAdminEmbedPage";
import { AcceptInvitePage } from "@/pages/AcceptInvitePage";
import { OnboardingPage } from "@/pages/OnboardingPage";
import { SignupPage } from "@/pages/SignupPage";

const ApprovalsPage = lazy(() =>
  import("@/pages/ApprovalsPage").then((m) => ({ default: m.ApprovalsPage }))
);
const BillingPage = lazy(() =>
  import("@/pages/BillingPage").then((m) => ({ default: m.BillingPage }))
);
const ConnectMailboxPage = lazy(() =>
  import("@/pages/ConnectMailboxPage").then((m) => ({ default: m.ConnectMailboxPage }))
);
const UploadPage = lazy(() =>
  import("@/pages/UploadPage").then((m) => ({ default: m.UploadPage }))
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
const ExpensesManagementPage = lazy(() =>
  import("@/pages/ExpensesManagementPage").then((m) => ({
    default: m.ExpensesManagementPage,
  }))
);
const PurchaseManagementPage = lazy(() =>
  import("@/pages/PurchaseManagementPage").then((m) => ({
    default: m.PurchaseManagementPage,
  }))
);
const SalesManagementPage = lazy(() =>
  import("@/pages/SalesManagementPage").then((m) => ({
    default: m.SalesManagementPage,
  }))
);
const DossiersPage = lazy(() =>
  import("@/pages/DossiersPage").then((m) => ({ default: m.DossiersPage }))
);
const DossierDetailPage = lazy(() =>
  import("@/pages/DossierDetailPage").then((m) => ({ default: m.DossierDetailPage }))
);
const CollectionsPage = lazy(() =>
  import("@/pages/CollectionsPage").then((m) => ({ default: m.CollectionsPage }))
);
const CustomersPage = lazy(() =>
  import("@/pages/CustomersPage").then((m) => ({ default: m.CustomersPage }))
);
const PaymentsPage = lazy(() =>
  import("@/pages/PaymentsPage").then((m) => ({ default: m.PaymentsPage }))
);
const LedgerLinkPage = lazy(() =>
  import("@/pages/LedgerLinkPage").then((m) => ({ default: m.LedgerLinkPage }))
);
const ClientsPage = lazy(() =>
  import("@/pages/platform/ClientsPage").then((m) => ({ default: m.ClientsPage }))
);
const CreditSettingsPage = lazy(() =>
  import("@/pages/platform/CreditSettingsPage").then((m) => ({
    default: m.CreditSettingsPage,
  }))
);
const TenantSettingsPage = lazy(() =>
  import("@/pages/platform/TenantSettingsPage").then((m) => ({
    default: m.TenantSettingsPage,
  }))
);

function LazyPage({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<PageLoader />}>{children}</Suspense>;
}

const routerBasename = getRouterBasename();

export default function App() {
  return (
    <BrowserRouter basename={routerBasename}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/login/oauth/callback" element={<LoginOauthCallbackPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/platform/embed" element={<SuperAdminEmbedPage />} />
        <Route path="/accept-invite" element={<AcceptInvitePage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/setup" element={<SignupPage />} />
        <Route
          path="/connect-mailbox"
          element={
            <LazyPage>
              <ConnectMailboxPage />
            </LazyPage>
          }
        />

        {/* Tenant app — hidden from super admins */}
        <Route path="/" element={<ProtectedRoute />}>
          <Route element={<TenantRoute />}>
            <Route path="onboarding" element={<OnboardingPage />} />
            <Route element={<OnboardingGate />}>
            <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="inbox" element={<Navigate to="/upload" replace />} />
            <Route
              path="upload"
              element={
                <LazyPage>
                  <UploadPage />
                </LazyPage>
              }
            />
            <Route
              path="team-expenses"
              element={
                <ModuleRoute moduleKey="team_expenses">
                  <LazyPage>
                    <TeamExpensesPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="expenses"
              element={
                <ModuleRoute moduleKey="expenses">
                  <LazyPage>
                    <ExpensesManagementPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="purchases"
              element={
                <ModuleRoute moduleKey="purchase">
                  <LazyPage>
                    <PurchaseManagementPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="sales"
              element={
                <ModuleRoute moduleKey="sales">
                  <LazyPage>
                    <SalesManagementPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="customers"
              element={
                <ModuleRoute moduleKey="sales">
                  <LazyPage>
                    <CustomersPage />
                  </LazyPage>
                </ModuleRoute>
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
              path="dossiers"
              element={
                <ModuleRoute moduleKey="dossiers">
                  <LazyPage>
                    <DossiersPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="dossiers/:dossierId"
              element={
                <ModuleRoute moduleKey="dossiers">
                  <LazyPage>
                    <DossierDetailPage />
                  </LazyPage>
                </ModuleRoute>
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
                <ModuleRoute moduleKey="rule_book">
                  <LazyPage>
                    <RulesPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="vault"
              element={
                <ModuleRoute moduleKey="vault">
                  <LazyPage>
                    <VaultPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="payments"
              element={
                <ModuleRoute moduleKey="payments">
                  <LazyPage>
                    <PaymentsPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="collections"
              element={
                <ModuleRoute moduleKey="sales">
                  <LazyPage>
                    <CollectionsPage />
                  </LazyPage>
                </ModuleRoute>
              }
            />
            <Route
              path="ledger-link"
              element={
                <ModuleRoute moduleKey="ledger_link">
                  <LazyPage>
                    <LedgerLinkPage />
                  </LazyPage>
                </ModuleRoute>
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
                <ModuleRoute moduleKey="reports">
                  <LazyPage>
                    <ReportsPage />
                  </LazyPage>
                </ModuleRoute>
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
          </Route>
        </Route>

        {/* Super admin platform console */}
        <Route path="/platform" element={<ProtectedRoute />}>
          <Route element={<SuperAdminRoute />}>
            <Route element={<SuperAdminLayout />}>
              <Route index element={<Navigate to="clients" replace />} />
              <Route
                path="clients"
                element={
                  <LazyPage>
                    <ClientsPage />
                  </LazyPage>
                }
              />
              <Route
                path="clients/:tenantId"
                element={
                  <LazyPage>
                    <TenantSettingsPage />
                  </LazyPage>
                }
              />
              <Route
                path="credit-settings"
                element={
                  <LazyPage>
                    <CreditSettingsPage />
                  </LazyPage>
                }
              />
            </Route>
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
