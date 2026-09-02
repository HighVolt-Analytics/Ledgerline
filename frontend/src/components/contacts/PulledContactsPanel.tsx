import { Link } from "react-router-dom";
import { Loader2, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";

import { CreatePulledXeroContactDialog } from "@/components/contacts/CreatePulledXeroContactDialog";
import { BillProcessingConnectionChip } from "@/components/settings/tax/BillProcessingConnectionChip";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineTableSkeleton } from "@/components/skeleton/PageSkeletons";
import { useToast } from "@/context/ToastContext";
import {
  useCreatePulledXeroContact,
  usePulledXeroContacts,
  useSyncPulledXeroContacts,
} from "@/hooks/usePulledXeroContacts";

type PulledContactsPanelProps = {
  canEdit?: boolean;
};

export function PulledContactsPanel({ canEdit = false }: PulledContactsPanelProps) {
  const { toast } = useToast();
  const {
    xeroConnected,
    loading,
    status,
    contacts,
    contactsLoading,
    contactsError,
  } = usePulledXeroContacts();
  const syncMutation = useSyncPulledXeroContacts();
  const createMutation = useCreatePulledXeroContact();
  const [dialogOpen, setDialogOpen] = useState(false);
  const organisationName = status?.xero.display_name ?? null;

  const handleSync = async () => {
    try {
      const result = await syncMutation.mutateAsync();
      const count = result.contacts?.persisted_total ?? result.contact ?? 0;
      toast({
        title: `Synced ${count} contact${count === 1 ? "" : "s"} from Xero`,
      });
    } catch (err) {
      toast({
        title: err instanceof Error ? err.message : "Could not sync contacts from Xero",
        variant: "destructive",
      });
    }
  };

  const handleSave = async (name: string) => {
    try {
      const result = await createMutation.mutateAsync(name);
      toast({
        title: result.reused ? "Contact already exists in Xero" : "Contact saved in Xero",
      });
      setDialogOpen(false);
    } catch (err) {
      toast({
        title: err instanceof Error ? err.message : "Could not save contact in Xero",
        variant: "destructive",
      });
    }
  };

  if (loading) {
    return (
      <Card className="w-full overflow-hidden" data-testid="pulled-contacts-panel">
        <InlineTableSkeleton rows={6} columns={3} />
      </Card>
    );
  }

  if (contactsError && !xeroConnected) {
    return (
      <Card className="w-full p-6 text-sm text-destructive" data-testid="pulled-contacts-panel">
        Could not load Xero connection status. Refresh the page or open Integrations.
      </Card>
    );
  }

  if (!xeroConnected) {
    return (
      <div className="w-full space-y-4" data-testid="pulled-contacts-panel">
        <h2 className="text-sm font-semibold">Pulled contacts</h2>
        <Card className="w-full p-8" data-testid="pulled-contacts-connect-note">
          <p className="text-center text-sm text-muted-foreground">
            Connect Xero to view pulled contacts.{" "}
            <Link to="/integrations" className="text-primary hover:underline">
              Open Integrations
            </Link>
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="w-full space-y-4" data-testid="pulled-contacts-panel">
      <div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex items-center gap-1.5">
            <h2 className="text-sm font-semibold">Pulled contacts</h2>
            {canEdit ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 cursor-pointer text-muted-foreground"
                onClick={() => void handleSync()}
                disabled={syncMutation.isPending}
                aria-label="Sync contacts from Xero"
                title="Sync contacts from Xero"
                data-testid="button-sync-pulled-contacts"
              >
                {syncMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
              </Button>
            ) : null}
          </div>
          <BillProcessingConnectionChip
            brandId="xero"
            providerName="Xero"
            organisationName={organisationName}
          />
          {canEdit ? (
            <Button
              type="button"
              size="sm"
              className="ml-auto"
              onClick={() => setDialogOpen(true)}
              data-testid="button-add-pulled-contact"
            >
              <Plus className="mr-1 h-4 w-4" />
              Add contact
            </Button>
          ) : null}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Names from the connected Xero organisation. Save creates the contact in Xero.
        </p>
      </div>

      <Card className="overflow-hidden rounded-xl">
        {contactsLoading && contacts.length === 0 ? (
          <InlineTableSkeleton rows={6} columns={2} />
        ) : contactsError ? (
          <p className="px-3 py-8 text-center text-sm text-destructive">
            Could not load pulled contacts.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Type</th>
              </tr>
            </thead>
            <tbody>
              {contacts.length === 0 ? (
                <tr>
                  <td colSpan={2} className="px-3 py-8 text-center text-sm text-muted-foreground">
                    No contacts pulled yet. Sync from Xero or add a name.
                  </td>
                </tr>
              ) : (
                contacts.map((row) => (
                  <tr key={row.xero_contact_id} className="row-band border-b border-border/60">
                    <td className="px-3 py-2">{row.name || "—"}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {row.is_supplier && row.is_customer
                        ? "Supplier · Customer"
                        : row.is_supplier
                          ? "Supplier"
                          : row.is_customer
                            ? "Customer"
                            : "Contact"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </Card>

      <CreatePulledXeroContactDialog
        open={dialogOpen}
        busy={createMutation.isPending}
        onClose={() => setDialogOpen(false)}
        onSave={(name) => void handleSave(name)}
      />
    </div>
  );
}
