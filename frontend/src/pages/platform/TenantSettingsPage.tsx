import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ExternalLink, Save } from "lucide-react";
import { api } from "@/api/client";
import type { PlatformTenantDetail } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/cn";

const LIFECYCLE_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "trial", label: "Trial" },
  { value: "suspended", label: "Suspended" },
];

export function TenantSettingsPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const navigate = useNavigate();
  const { enterClientWorkspace } = useAuth();
  const id = tenantId?.trim() ?? "";
  const isValidId = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id);

  const [tenant, setTenant] = useState<PlatformTenantDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [entering, setEntering] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmSlug, setConfirmSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviting, setInviting] = useState(false);
  const [inviteSent, setInviteSent] = useState(false);

  const [name, setName] = useState("");
  const [lifecycleStatus, setLifecycleStatus] = useState("active");
  const [isActive, setIsActive] = useState(true);
  const [modules, setModules] = useState<Record<string, boolean>>({});

  const loadTenant = useCallback(() => {
    if (!isValidId) return;
    setLoading(true);
    setError(null);
    api
      .getPlatformTenant(id)
      .then((data) => {
        setTenant(data);
        setName(data.name);
        setLifecycleStatus(data.lifecycle_status);
        setIsActive(data.is_active);
        setModules(
          Object.fromEntries(data.modules.map((m) => [m.module_key, m.is_active]))
        );
        const onboardingDone = Boolean(data.settings_json?.onboarding_completed);
        if (!onboardingDone && data.user_count === 0 && data.pending_invite_count > 0) {
          setInviteSent(true);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load tenant"))
      .finally(() => setLoading(false));
  }, [id, isValidId]);

  useEffect(() => {
    loadTenant();
  }, [loadTenant]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 3000);
    return () => clearTimeout(t);
  }, [saved]);

  async function handleEnterWorkspace() {
    if (!tenant) return;
    setEntering(true);
    setError(null);
    try {
      await enterClientWorkspace(tenant.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open workspace");
      setEntering(false);
    }
  }

  async function handleDeletePermanently() {
    if (!tenant) return;
    if (confirmSlug.trim().toLowerCase() !== tenant.slug) {
      setError(`Type "${tenant.slug}" to confirm deletion.`);
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await api.deletePlatformTenant(tenant.id, confirmSlug.trim().toLowerCase());
      navigate("/platform/clients", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete tenant");
      setDeleting(false);
    }
  }

  async function handleInviteAdmin(e: React.FormEvent) {
    e.preventDefault();
    if (!tenant) return;
    if (!inviteEmail.trim() || !inviteName.trim()) {
      setError("Admin name and email are required.");
      return;
    }
    setInviting(true);
    setError(null);
    try {
      await api.invitePlatformTenantAdmin(tenant.id, {
        email: inviteEmail.trim(),
        full_name: inviteName.trim(),
      });
      setInviteSent(true);
      loadTenant();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send invite");
    } finally {
      setInviting(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!tenant) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updatePlatformTenant(tenant.id, {
        name: name.trim(),
        lifecycle_status: lifecycleStatus,
        is_active: isActive,
        modules: Object.entries(modules).map(([module_key, is_active]) => ({
          module_key,
          is_active,
        })),
      });
      setTenant(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save changes");
    } finally {
      setSaving(false);
    }
  }

  if (!isValidId) {
    return <p className="text-sm text-destructive">Invalid tenant ID.</p>;
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading tenant settings…</p>;
  }

  if (!tenant) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-destructive">{error ?? "Tenant not found."}</p>
        <Button variant="outline" onClick={() => navigate("/platform/clients")}>
          Back to clients
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link
          to="/platform/clients"
          className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Clients
        </Link>
        <span>/</span>
        <span className="text-foreground font-medium">{tenant.name}</span>
      </div>

      <PageHeader
        title={tenant.name}
        subtitle={`Tenant settings · ${tenant.slug}`}
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              data-testid="button-enter-workspace"
              disabled={entering || !tenant.is_active}
              onClick={() => void handleEnterWorkspace()}
            >
              <ExternalLink className="h-4 w-4 mr-1.5" />
              {entering ? "Opening…" : "Open workspace"}
            </Button>
            {saved ? (
              <Badge variant="outline" className="text-[hsl(var(--chart-1))]">
                Saved
              </Badge>
            ) : null}
          </div>
        }
      />

      <form onSubmit={handleSave} className="space-y-6">
        <Card className="p-5 space-y-4">
          <h2 className="text-sm font-semibold">General</h2>
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="tenant-name-edit">
              Client name
            </label>
            <Input
              id="tenant-name-edit"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Slug</label>
            <Input value={tenant.slug} disabled className="font-mono text-xs" />
            <p className="text-xs text-muted-foreground">Slug cannot be changed after creation.</p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="lifecycle-status">
                Lifecycle status
              </label>
              <Select
                id="lifecycle-status"
                value={lifecycleStatus}
                onValueChange={setLifecycleStatus}
                size="md"
                options={LIFECYCLE_OPTIONS}
                className="w-full"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="tenant-active">
                Access
              </label>
              <Select
                id="tenant-active"
                value={isActive ? "true" : "false"}
                onValueChange={(v) => setIsActive(v === "true")}
                size="md"
                options={[
                  { value: "true", label: "Enabled" },
                  { value: "false", label: "Disabled" },
                ]}
                className="w-full"
              />
            </div>
          </div>
        </Card>

        <Card className="p-5 space-y-4">
          <h2 className="text-sm font-semibold">Usage</h2>
          <dl className="grid sm:grid-cols-4 gap-4 text-sm">
            <div>
              <dt className="text-muted-foreground">Users</dt>
              <dd className="text-lg font-semibold tnum">{tenant.user_count}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Pending invites</dt>
              <dd className="text-lg font-semibold tnum">{tenant.pending_invite_count}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Invoices</dt>
              <dd className="text-lg font-semibold tnum">{tenant.invoice_count}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Credit balance</dt>
              <dd className="text-lg font-semibold tnum">
                {tenant.credit_balance.toLocaleString()}
              </dd>
            </div>
          </dl>
          {tenant.created_at && (
            <p className="text-xs text-muted-foreground">
              Created {new Date(tenant.created_at).toLocaleString()}
            </p>
          )}
        </Card>

        {(tenant.user_count === 0 || tenant.pending_invite_count > 0) && (
          <Card className="p-5 space-y-4">
            <h2 className="text-sm font-semibold">Client onboarding</h2>
            <p className="text-xs text-muted-foreground">
              The first client administrator must accept their invite and complete onboarding in
              the tenant app. Super admins should not complete setup on the client&apos;s behalf.
            </p>
            {tenant.user_count === 0 && tenant.pending_invite_count > 0 && (
              <Badge variant="outline" className="text-xs">
                Waiting for first admin to accept invite ({tenant.pending_invite_count} pending)
              </Badge>
            )}
            {tenant.user_count > 0 && tenant.settings_json?.onboarding_completed === false && (
              <Badge variant="outline" className="text-xs">
                First admin has not completed onboarding yet
              </Badge>
            )}
            {tenant.user_count > 0 && tenant.settings_json?.onboarding_completed === true && (
              <Badge variant="outline" className="text-xs text-[hsl(var(--chart-1))]">
                Onboarding complete
              </Badge>
            )}
            <form onSubmit={handleInviteAdmin} className="space-y-3 pt-1">
              <p className="text-sm font-medium">
                {inviteSent ? "Resend or invite another admin" : "Invite first admin"}
              </p>
              <div className="grid sm:grid-cols-2 gap-3">
                <Input
                  value={inviteName}
                  onChange={(e) => setInviteName(e.target.value)}
                  placeholder="Admin full name"
                  required
                />
                <Input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="Admin email"
                  required
                />
              </div>
              <Button type="submit" size="sm" disabled={inviting}>
                {inviting ? "Sending…" : inviteSent ? "Send invite" : "Invite admin"}
              </Button>
            </form>
          </Card>
        )}

        <Card className="p-5 space-y-4">
          <h2 className="text-sm font-semibold">Modules</h2>
          <p className="text-xs text-muted-foreground">
            Enable or disable product modules for this client tenant.
          </p>
          <div className="space-y-2">
            {Object.entries(modules).map(([key, active]) => (
              <label
                key={key}
                className={cn(
                  "flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm",
                  !active && "opacity-70"
                )}
              >
                <span className="capitalize">{key.replace(/_/g, " ")}</span>
                <input
                  type="checkbox"
                  checked={active}
                  onChange={(e) =>
                    setModules((prev) => ({ ...prev, [key]: e.target.checked }))
                  }
                  className="h-4 w-4"
                />
              </label>
            ))}
          </div>
        </Card>

        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => navigate("/platform/clients")}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            <Save className="h-4 w-4 mr-1.5" />
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </form>

      <Card className="p-5 border-destructive/40 space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-destructive">Danger zone</h2>
          <p className="text-xs text-muted-foreground mt-1">
            Permanently delete this client tenant, all users, invoices, and configuration.
            This cannot be undone.
          </p>
        </div>
        {!deleteOpen ? (
          <Button
            type="button"
            variant="destructive"
            data-testid="button-delete-tenant-open"
            onClick={() => {
              setDeleteOpen(true);
              setConfirmSlug("");
              setError(null);
            }}
          >
            Delete tenant permanently
          </Button>
        ) : (
          <div className="space-y-3 rounded-md border border-destructive/30 bg-destructive/5 p-4">
            <p className="text-sm">
              Type <span className="font-mono font-semibold">{tenant.slug}</span> to confirm.
            </p>
            <Input
              data-testid="input-delete-tenant-confirm"
              value={confirmSlug}
              onChange={(e) => setConfirmSlug(e.target.value)}
              placeholder={tenant.slug}
              autoComplete="off"
              disabled={deleting}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="destructive"
                data-testid="button-delete-tenant-confirm"
                disabled={deleting || confirmSlug.trim().toLowerCase() !== tenant.slug}
                onClick={() => void handleDeletePermanently()}
              >
                {deleting ? "Deleting…" : "Delete permanently"}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={deleting}
                onClick={() => {
                  setDeleteOpen(false);
                  setConfirmSlug("");
                  setError(null);
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
