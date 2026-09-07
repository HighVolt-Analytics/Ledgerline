import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ModuleRoute } from "@/components/ModuleRoute";
import { OnboardingGate } from "@/components/OnboardingGate";
import { Layout } from "@/components/Layout";
import { SuperAdminLayout } from "@/components/SuperAdminLayout";
import { SuperAdminRoute } from "@/components/SuperAdminRoute";
import { TenantRoute } from "@/components/TenantRoute";
import { PageLoader, type PageLoaderVariant } from "@/components/PageLoader";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { getRouterBasename } from "@/lib/routerBasename";
import { ALL_PUBLIC_SIGNUP_PATHS } from "@/lib/publicSignupRoutes";

const DashboardPage = lazy(() =>
  import("@/pages/DashboardPage").then((m) => ({ default: m.DashboardPage }))
);
const LoginPage = lazy(() =>
  import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage }))
);
const LoginOauthCallbackPage = lazy(() =>
  import("@/pages/LoginOauthCallbackPage").then((m) => ({
    default: m.LoginOauthCallbackPage,
  }))
);
const ForgotPasswordPage = lazy(() =>
  import("@/pages/ForgotPasswordPage").then((m) => ({ default: m.ForgotPasswordPage }))
);
const ResetPasswordPage = lazy(() =>
  import("@/pages/ResetPasswordPage").then((m) => ({ default: m.ResetPasswordPage }))
);
const SignupPage = lazy(() =>
  import("@/pages/SignupPage").then((m) => ({ default: m.SignupPage }))
);
const SuperAdminEmbedPage = lazy(() =>
  import("@/pages/SuperAdminEmbedPage").then((m) => ({ default: m.SuperAdminEmbedPage }))
);
const AcceptInvitePage = lazy(() =>
  import("@/pages/AcceptInvitePage").then((m) => ({ default: m.AcceptInvitePage }))
);
const ConfirmMasterPage = lazy(() =>
  import("@/pages/ConfirmMasterPage").then((m) => ({ default: m.ConfirmMasterPage }))
);
const OnboardingPage = lazy(() =>
  import("@/pages/OnboardingPage").then((m) => ({ default: m.OnboardingPage }))
);
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
const CreationsPage = lazy(() =>
  import("@/pages/CreationsPage").then((m) => ({ default: m.CreationsPage }))
);
const SettingsPage = lazy(() =>
  import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage }))
);
const VaultPage = lazy(() =>
  import("@/pages/VaultPage").then((m) => ({ default: m.VaultPage }))
);
const MobilePrototypeRedirect = lazy(() =>
  import("@/mobile/MobilePrototypeRedirect").then((m) => ({
    default: m.MobilePrototypeRedirect,
  }))
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
const CollectionsPage = lazy(() =>
  import("@/pages/CollectionsPage").then((m) => ({ default: m.CollectionsPage }))
);
const CustomersPage = lazy(() =>
  import("@/pages/CustomersPage").then((m) => ({ default: m.CustomersPage }))
);
const PaymentsPage = lazy(() =>
  import("@/pages/PaymentsPage").then((m) => ({ default: m.PaymentsPage }))
);
const BankFeedsPage = lazy(() =>
  import("@/pages/BankFeedsPage").then((m) => ({ default: m.BankFeedsPage }))
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
const DeveloperPortPage = lazy(() =>
  import("@/pages/platform/DeveloperPortPage").then((m) => ({
    default: m.DeveloperPortPage,
  }))
);
const TenantSettingsPage = lazy(() =>
  import("@/pages/platform/TenantSettingsPage").then((m) => ({
    default: m.TenantSettingsPage,
  }))
);

function LazyPage({
  children,
  loaderVariant,
}: {
  children: React.ReactNode;
  loaderVariant?: PageLoaderVariant;
}) {
  return <Suspense fallback={<PageLoader variant={loaderVariant} />}>{children}</Suspense>;
}

const routerBasename = getRouterBasename();

export default function App() {
  return (
    <BrowserRouter basename={routerBasename}>
      <Routes>
        <Route
          path="/login"
          element={
            <LazyPage>
              <LoginPage />
            </LazyPage>
          }
        />
        <Route
          path="/login/oauth/callback"
          element={
            <LazyPage>
              <LoginOauthCallbackPage />
            </LazyPage>
          }
        />
        <Route
          path="/forgot-password"
          element={
            <LazyPage>
              <ForgotPasswordPage />
            </LazyPage>
          }
        />
        <Route
          path="/reset-password"
          element={
            <LazyPage>
              <ResetPasswordPage />
            </LazyPage>
          }
        />
        {ALL_PUBLIC_SIGNUP_PATHS.map((path) => (
          <Route
            key={path}
            path={path}
            element={
              <LazyPage>
                <SignupPage />
              </LazyPage>
            }
          />
        ))}
        <Route
          path="/platform/embed"
          element={
            <LazyPage>
              <SuperAdminEmbedPage />
            </LazyPage>
          }
        />
        <Route
          path="/accept-invite"
          element={
            <LazyPage>
              <AcceptInvitePage />
            </LazyPage>
          }
        />
        <Route
          path="/confirm-master"
          element={
            <LazyPage>
              <ConfirmMasterPage />
            </LazyPage>
          }
        />
        <Route
          path="/setup"
          element={
            <LazyPage>
              <SignupPage />
            </LazyPage>
          }
        />
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
            <Route
              path="onboarding"
              element={
                <LazyPage>
                  <OnboardingPage />
                </LazyPage>
              }
            />
            <Route element={<OnboardingGate />}>
            <Route element={<Layout />}>
            <Route
              index
              element={
                <LazyPage>
                  <DashboardPage />
                </LazyPage>
              }
            />
            <Route path="inbox" element={<Navigate to="/upload" replace />} />
            <Route
              path="upload"
              element={
                <LazyPage loaderVariant="upload">
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
            <Route path="dossiers" element={<Navigate to="/upload" replace />} />
            <Route path="dossiers/:dossierId" element={<Navigate to="/upload" replace />} />
            <Route
              path="vendors"
              element={
                <LazyPage>
                  <VendorsPage />
                </LazyPage>
              }
            />
            <Route
              path="creations"
              element={
                <LazyPage>
                  <CreationsPage />
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
              path="bank-feeds"
              element={
                <ModuleRoute moduleKey="bank_feeds">
                  <LazyPage>
                    <BankFeedsPage />
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
              <Route
                path="developer-port"
                element={
                  <LazyPage>
                    <DeveloperPortPage />
                  </LazyPage>
                }
              />
            </Route>
          </Route>
        </Route>

        {/* Mobile: same login/OTP/tenant as desktop, then exact prototype UI (no API yet) */}
        <Route element={<ProtectedRoute />}>
          <Route element={<TenantRoute />}>
            <Route
              path="/m"
              element={
                <LazyPage>
                  <MobilePrototypeRedirect />
                </LazyPage>
              }
            />
            <Route
              path="/m/*"
              element={
                <LazyPage>
                  <MobilePrototypeRedirect />
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
