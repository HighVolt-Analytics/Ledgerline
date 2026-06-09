import { useCallback, useEffect, useState } from "react";
import { Activity, ArrowLeftRight, Cloud, Database, FileSearch, Mail, Plus, Server, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import type { AppSettings, ConnectedMailbox } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";

function statusBadge(ok: boolean) {
  return ok ? (
    <Badge variant="outline" className="border-[hsl(var(--chart-1)/0.4)] text-[hsl(var(--chart-1))]">
      Connected
    </Badge>
  ) : (
    <Badge variant="secondary">Not connected</Badge>
  );
}

export function IntegrationsPage() {
  const { user } = useAuth();
  const [s, setS] = useState<AppSettings | null>(null);
  const [mailboxes, setMailboxes] = useState<ConnectedMailbox[]>([]);
  const [newEmail, setNewEmail] = useState("");
  const [mbError, setMbError] = useState<string | null>(null);

  const loadMailboxes = useCallback((fresh = false) => {
    api.listMailboxes({ fresh }).then(setMailboxes).catch(() => setMailboxes([]));
  }, []);

  useEffect(() => {
    api.getSettings().then(setS);
    loadMailboxes();
  }, [loadMailboxes]);

  useEffect(() => {
    if (user?.email) {
      setNewEmail((prev) => prev || user.email);
    }
  }, [user?.email]);

  async function addMailbox() {
    setMbError(null);
    const email = newEmail.trim().toLowerCase();
    if (!email) return;
    try {
      await api.addMailbox(email);
      setNewEmail("");
      loadMailboxes();
    } catch (e) {
      setMbError(e instanceof Error ? e.message : "Failed to add mailbox");
    }
  }

  if (!s) {
    return <p className="text-sm text-muted-foreground">Loading integrations…</p>;
  }

  const items = [
    {
      id: "graph",
      name: "Microsoft Graph",
      tagline: s.graph_mailbox || "Outlook capture",
      ok: s.graph_enabled,
      icon: Mail,
    },
    {
      id: "blob",
      name: "Azure Blob Storage",
      tagline: s.azure_storage_container,
      ok: s.blob_enabled,
      icon: Cloud,
    },
    {
      id: "di",
      name: "Azure Document Intelligence",
      tagline: "Invoice OCR & extraction",
      ok: s.azure_di_enabled,
      icon: FileSearch,
    },
    {
      id: "postgres",
      name: "Azure PostgreSQL",
      tagline: s.azure_location ? `${s.azure_location} flexible server` : "Managed database",
      ok: s.azure_postgres_enabled,
      icon: Database,
    },
    {
      id: "redis",
      name: "Azure Redis",
      tagline: "Celery broker & task queue",
      ok: s.azure_redis_enabled,
      icon: Server,
    },
    {
      id: "appinsights",
      name: "Application Insights",
      tagline: "Telemetry & monitoring",
      ok: s.appinsights_enabled,
      icon: Activity,
    },
    {
      id: "xero",
      name: "Xero",
      tagline: "Chart of accounts & journals",
      ok: false,
      icon: ArrowLeftRight,
    },
    {
      id: "qbo",
      name: "QuickBooks Online",
      tagline: "Bills & journals (coming soon)",
      ok: false,
      icon: ArrowLeftRight,
    },
    {
      id: "myob",
      name: "MYOB",
      tagline: "Purchase entries (coming soon)",
      ok: false,
      icon: ArrowLeftRight,
    },
    {
      id: "stripe",
      name: "Stripe",
      tagline: "Credit pack billing (coming soon)",
      ok: false,
      icon: ArrowLeftRight,
    },
  ];

  const connected = items.filter((i) => i.ok).length;

  return (
    <div>
      <PageHeader
        title="Integrations"
        subtitle={`${connected} of ${items.length} services connected`}
      />

      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-3 mb-6">
        {items.map((h) => (
          <Card
            key={h.id}
            className="p-4 flex flex-col gap-3"
            data-testid={`card-integration-${h.id}`}
          >
            <div className="flex items-start justify-between">
              <div className="h-10 w-10 rounded-md bg-muted flex items-center justify-center text-primary">
                <h.icon className="h-5 w-5" />
              </div>
              {statusBadge(h.ok)}
            </div>
            <div>
              <p className="text-sm font-medium">{h.name}</p>
              <p className="text-xs text-muted-foreground">{h.tagline}</p>
            </div>
            <div className="flex items-center justify-between mt-auto pt-1">
              <span className="text-[11px] text-muted-foreground">Live from /api/settings</span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  disabled={!h.ok}
                  data-testid={`button-connect-${h.id}`}
                >
                  {h.ok ? "Connected" : "Connect"}
                </Button>
                {h.ok && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs"
                    disabled
                    data-testid={`button-sync-${h.id}`}
                  >
                    Sync now
                  </Button>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card className="p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">Connected mailboxes</h2>
            <p className="text-xs text-muted-foreground">
              Microsoft Graph polls these Outlook addresses (not your app login email unless listed
              here). Tenant admin must grant the Azure app access to each mailbox.
            </p>
            {user && (
              <p className="text-xs text-muted-foreground mt-1">
                Signed in as <span className="font-medium text-foreground">{user.email}</span>
              </p>
            )}
          </div>
          <Mail className="h-5 w-5 text-muted-foreground" />
        </div>
        {user?.role === "admin" && (
          <div className="flex flex-wrap gap-2 mb-4">
            <Input
              type="email"
              placeholder="user@company.com"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              className="max-w-xs"
            />
            <Button size="sm" onClick={addMailbox} disabled={!newEmail.trim()}>
              <Plus className="h-4 w-4 mr-1" />
              Add mailbox
            </Button>
          </div>
        )}
        {mbError && <p className="text-sm text-destructive mb-2">{mbError}</p>}
        {mailboxes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No mailboxes yet. Add an address or set GRAPH_MAILBOX in backend .env (synced on startup).
          </p>
        ) : (
          <ul className="space-y-2">
            {mailboxes.map((mb) => (
              <li
                key={mb.id}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
              >
                <div>
                  <span className="font-medium">{mb.email}</span>
                  {!mb.is_active && (
                    <Badge variant="secondary" className="ml-2 text-[10px]">
                      Paused
                    </Badge>
                  )}
                </div>
                {user?.role === "admin" && (
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={async () => {
                        try {
                          const updated = await api.toggleMailbox(mb.id);
                          setMailboxes((prev) =>
                            prev.map((m) => (m.id === updated.id ? updated : m))
                          );
                          setMbError(null);
                        } catch (e) {
                          setMbError(
                            e instanceof Error ? e.message : "Failed to update mailbox"
                          );
                        }
                      }}
                    >
                      {mb.is_active ? "Pause" : "Resume"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive"
                      onClick={async () => {
                        try {
                          await api.removeMailbox(mb.id);
                          loadMailboxes(true);
                          setMbError(null);
                        } catch (e) {
                          setMbError(
                            e instanceof Error ? e.message : "Failed to remove mailbox"
                          );
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-5">
        <h2 className="text-sm font-semibold mb-1">What syncs when connected to Xero?</h2>
        <p className="text-xs text-muted-foreground mb-4">
          Bidirectional sync keeps your ledger and Ledgerline aligned.
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {["Chart of accounts", "Contacts", "Bills & payments", "Tax rates", "Tracking categories"].map(
            (h) => (
              <div
                key={h}
                className="flex items-center gap-3 rounded-md border border-border p-3"
              >
                <span className="text-[11px] font-semibold text-primary">Ledgerline</span>
                <ArrowLeftRight className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="text-[11px] font-semibold text-muted-foreground">Xero</span>
                <span className="text-sm ml-auto">{h}</span>
              </div>
            )
          )}
        </div>
      </Card>
    </div>
  );
}
