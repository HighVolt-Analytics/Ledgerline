import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type { PendingTenantInvite, TenantMember } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { formatTenantRole } from "@/lib/tenantRoles";

type Props = {
  tenantId: string;
};

export function PlatformTenantUsersSection({ tenantId }: Props) {
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [pending, setPending] = useState<PendingTenantInvite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listPlatformTenantMembers(tenantId);
      setMembers(data.members);
      setPending(data.pending_invites);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load users");
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card className="p-5 space-y-4 overflow-hidden">
      <div>
        <h2 className="text-sm font-semibold">User management</h2>
        <p className="text-xs text-muted-foreground mt-1">
          All users with access to this client tenant and their roles.
        </p>
      </div>

      {loading && (
        <p className="text-sm text-muted-foreground">Loading users…</p>
      )}
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {!loading && !error && members.length === 0 && pending.length === 0 && (
        <p className="text-sm text-muted-foreground">No users in this tenant yet.</p>
      )}

      {!loading && !error && members.length > 0 && (
        <div className="overflow-x-auto -mx-5">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-y border-border">
                <th className="px-5 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Role</th>
                <th className="px-5 py-2 font-medium text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {members.map((member) => (
                <tr
                  key={member.user_id}
                  className="border-b border-border/60 last:border-0"
                  data-testid={`platform-user-${member.user_id}`}
                >
                  <td className="px-5 py-2.5 font-medium">{member.full_name}</td>
                  <td className="px-3 py-2.5 text-muted-foreground tnum text-xs">
                    {member.email}
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge variant="outline">{formatTenantRole(member.role)}</Badge>
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    {member.is_active ? (
                      <Badge variant="outline">Active</Badge>
                    ) : (
                      <Badge variant="secondary">Inactive</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && pending.length > 0 && (
        <div className="pt-2 border-t border-border space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Pending invites
          </p>
          <ul className="space-y-2">
            {pending.map((invite) => (
              <li
                key={invite.id}
                className="flex items-center justify-between gap-2 text-sm"
                data-testid={`platform-pending-invite-${invite.id}`}
              >
                <span>
                  {invite.full_name}{" "}
                  <span className="text-muted-foreground">({invite.email})</span>
                </span>
                <Badge variant="outline">{formatTenantRole(invite.role)}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
