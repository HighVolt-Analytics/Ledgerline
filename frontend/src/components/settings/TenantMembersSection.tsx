import { useCallback, useEffect, useState } from "react";
import { Trash2, UserPlus } from "lucide-react";
import { api } from "@/api/client";
import type { PendingTenantInvite, TenantMember } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { usePermissions } from "@/hooks/usePermissions";
import { formatTenantRole, TENANT_ROLE_OPTIONS } from "@/lib/tenantRoles";

function InviteMemberDialog({
  open,
  onClose,
  onInvited,
}: {
  open: boolean;
  onClose: () => void;
  onInvited: () => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("approver");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    accept_url: string;
    email_sent: boolean;
    email_error?: string | null;
  } | null>(null);

  useEffect(() => {
    if (!open) {
      setEmail("");
      setFullName("");
      setRole("approver");
      setError(null);
      setResult(null);
    }
  }, [open]);

  if (!open) return null;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.inviteTenantMember({
        email: email.trim(),
        full_name: fullName.trim() || email.split("@")[0],
        role,
      });
      setResult({
        accept_url: created.accept_url,
        email_sent: created.email_sent === true,
        email_error: created.email_error,
      });
      onInvited();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send invite");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/80"
        aria-label="Close dialog"
        onClick={onClose}
      />
      <div className="relative z-10 w-full max-w-md rounded-lg border border-border bg-background p-6 shadow-lg">
        <h4 className="text-sm font-semibold mb-1">Invite team member</h4>
        <p className="text-sm text-muted-foreground mb-4">
          They will receive an email to set a password and join this organisation.
        </p>
        <div className="space-y-3">
          <Input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email@company.com"
            type="email"
            data-testid="input-invite-email"
          />
          <Input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Full name"
            data-testid="input-invite-name"
          />
          <Select
            value={role}
            onValueChange={setRole}
            options={TENANT_ROLE_OPTIONS}
            size="md"
            data-testid="select-invite-role"
          />
        </div>
        {error && <p className="text-xs text-destructive mt-2">{error}</p>}
        {result && (
          <div className="mt-3 space-y-2">
            {result.email_sent ? (
              <p className="text-xs text-[hsl(var(--chart-1))]">
                Invitation email sent to {email.trim()}.
              </p>
            ) : (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                {result.email_error ??
                  "Email could not be sent. Share the invite link manually:"}
              </p>
            )}
            <p className="text-xs text-muted-foreground break-all">
              Invite link: {result.accept_url}
            </p>
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {result ? "Close" : "Cancel"}
          </Button>
          {!result && (
            <Button onClick={() => void submit()} disabled={busy || !email.trim()}>
              {busy ? "Sending…" : "Send invite"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export function TenantMembersSection() {
  const { permissions } = usePermissions();
  const canManage = permissions?.permissions["Manage Users"] === true;
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [pending, setPending] = useState<PendingTenantInvite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [busyUserId, setBusyUserId] = useState<number | null>(null);
  const [busyInviteId, setBusyInviteId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listTenantMembers();
      setMembers(data.members);
      setPending(data.pending_invites);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load team");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onRoleChange = async (userId: number, role: string) => {
    setBusyUserId(userId);
    try {
      await api.updateTenantMemberRole(userId, role);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not update role");
    } finally {
      setBusyUserId(null);
    }
  };

  const onRevokeInvite = async (inviteId: number) => {
    if (!window.confirm("Revoke this invitation? The invite link will no longer work.")) {
      return;
    }
    setBusyInviteId(inviteId);
    try {
      await api.revokeTenantInvite(inviteId);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not revoke invite");
    } finally {
      setBusyInviteId(null);
    }
  };

  const onDeactivate = async (userId: number) => {
    if (!window.confirm("Deactivate this member? They will lose access to this organisation.")) {
      return;
    }
    setBusyUserId(userId);
    try {
      await api.deactivateTenantMember(userId);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not deactivate member");
    } finally {
      setBusyUserId(null);
    }
  };

  return (
    <Card className="overflow-hidden max-w-3xl">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border">
        <div>
          <h3 className="text-sm font-semibold">Team members</h3>
          <p className="text-xs text-muted-foreground">
            Roles control what each person can do in this organisation.
          </p>
        </div>
        {canManage && (
          <Button size="sm" onClick={() => setInviteOpen(true)} data-testid="button-invite-member">
            <UserPlus className="h-4 w-4 mr-1.5" />
            Invite
          </Button>
        )}
      </div>

      {loading && <p className="px-4 py-6 text-sm text-muted-foreground">Loading team…</p>}
      {error && <p className="px-4 py-3 text-sm text-destructive">{error}</p>}

      {!loading && !error && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground border-b border-border">
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Email</th>
              <th className="px-4 py-2 font-medium">Role</th>
              <th className="px-4 py-2 font-medium text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr
                key={member.user_id}
                className="row-band border-b border-border/60 last:border-0"
                data-testid={`user-${member.user_id}`}
              >
                <td className="px-4 py-2.5 font-medium">{member.full_name}</td>
                <td className="px-3 py-2.5 text-muted-foreground tnum text-xs">{member.email}</td>
                <td className="px-4 py-2.5">
                  {canManage && member.is_active ? (
                    <Select
                      value={member.role}
                      onValueChange={(value) => void onRoleChange(member.user_id, value)}
                      options={TENANT_ROLE_OPTIONS}
                      disabled={busyUserId === member.user_id}
                      data-testid={`select-role-${member.user_id}`}
                    />
                  ) : (
                    <Badge variant="outline">{formatTenantRole(member.role)}</Badge>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right">
                  {member.is_active ? (
                    canManage ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        disabled={busyUserId === member.user_id}
                        onClick={() => void onDeactivate(member.user_id)}
                      >
                        Deactivate
                      </Button>
                    ) : (
                      <Badge variant="outline">Active</Badge>
                    )
                  ) : (
                    <Badge variant="secondary">Inactive</Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!loading && pending.length > 0 && (
        <div className="border-t border-border px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Pending invites
          </p>
          <ul className="space-y-2">
            {pending.map((invite) => (
              <li
                key={invite.id}
                className="flex items-center justify-between gap-2 text-sm"
                data-testid={`pending-invite-${invite.id}`}
              >
                <span>
                  {invite.full_name}{" "}
                  <span className="text-muted-foreground">({invite.email})</span>
                </span>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge variant="outline">{formatTenantRole(invite.role)}</Badge>
                  {canManage && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive h-8 w-8 p-0"
                      disabled={busyInviteId === invite.id}
                      onClick={() => void onRevokeInvite(invite.id)}
                      aria-label={`Revoke invite for ${invite.email}`}
                      data-testid={`revoke-invite-${invite.id}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <InviteMemberDialog
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        onInvited={() => void load()}
      />
    </Card>
  );
}
