import { describe, expect, it } from "vitest";
import { canAccessNavPath } from "@/hooks/usePermissions";
import type { UserPermissions } from "@/api/types";

function perms(flags: Record<string, boolean>): UserPermissions {
  return {
    role: "employee",
    matrix_role: "Employee",
    permissions: flags as UserPermissions["permissions"],
    enabled_modules: {},
  };
}

describe("canAccessNavPath", () => {
  it("allows all paths before permissions load", () => {
    expect(canAccessNavPath("/upload", null)).toBe(true);
    expect(canAccessNavPath("/rules", null)).toBe(true);
  });

  it("keeps Upload visible for View-only roles (employees must upload claims)", () => {
    expect(
      canAccessNavPath(
        "/upload",
        perms({ View: true, Comment: false, Approve: false })
      )
    ).toBe(true);
  });

  it("hides Upload when View is explicitly denied", () => {
    expect(
      canAccessNavPath(
        "/upload",
        perms({ View: false, Comment: false, Approve: false })
      )
    ).toBe(false);
  });

  it("still gates Rule Book and Integrations on elevated privileges", () => {
    expect(
      canAccessNavPath("/rules", perms({ View: true, "Edit Policy": false }))
    ).toBe(false);
    expect(
      canAccessNavPath("/rules", perms({ View: true, "Edit Policy": true }))
    ).toBe(true);
    expect(
      canAccessNavPath(
        "/integrations",
        perms({ View: true, "Manage Users": false })
      )
    ).toBe(false);
  });
});
