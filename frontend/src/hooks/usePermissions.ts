import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { UserPermissions } from "@/api/types";
import { useAuth } from "@/context/AuthContext";

export function usePermissions() {
  const { user, loading: authLoading } = useAuth();
  const [permissions, setPermissions] = useState<UserPermissions | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      setPermissions(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    void api
      .getMyPermissions()
      .then((data) => {
        if (!cancelled) setPermissions(data);
      })
      .catch(() => {
        if (!cancelled) setPermissions(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [user?.id, user?.tenant_id, authLoading]);

  return { permissions, loading };
}

export function canAccessNavPath(
  path: string,
  permissions: UserPermissions | null
): boolean {
  if (!permissions) return true;
  if (path === "/rules") return permissions.permissions["Edit Policy"] === true;
  if (path === "/integrations") return permissions.permissions["Manage Users"] === true;
  if (path === "/upload") {
    return (
      permissions.permissions.Comment === true ||
      permissions.permissions.Approve === true ||
      permissions.permissions.Publish === true
    );
  }
  return permissions.permissions.View !== false;
}
