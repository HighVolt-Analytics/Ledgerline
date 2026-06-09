import type { VaultTreeNode as ApiVaultTreeNode } from "@/api/types";

export type VaultSelection = {
  org: string;
  vendor?: string;
  year?: string;
  month?: string;
};

export type VaultTreeNode = {
  id: string;
  label: string;
  kind: "org" | "vendor" | "year" | "month";
  count: number;
  children: VaultTreeNode[];
};

export function vaultAncestorIds(nodeId: string): string[] {
  const parts = nodeId.split("/").filter(Boolean);
  return parts.map((_, index) => parts.slice(0, index + 1).join("/"));
}

/** Keep only one open branch — org → one vendor → one year. */
export function accordionExpandedIds(
  node: VaultTreeNode,
  currentlyExpanded: Set<string>
): Set<string> {
  const isOpen = currentlyExpanded.has(node.id);

  if (node.kind === "month" || node.children.length === 0) {
    return new Set(vaultAncestorIds(node.id));
  }

  if (isOpen) {
    if (node.kind === "year") {
      return new Set(vaultAncestorIds(node.id).slice(0, -1));
    }
    if (node.kind === "vendor") {
      return new Set([node.id.split("/")[0] ?? node.id]);
    }
    return new Set();
  }

  if (node.kind === "org") {
    return new Set([node.id]);
  }

  return new Set(vaultAncestorIds(node.id));
}

export function selectionBreadcrumb(selection: VaultSelection | null): string[] {
  if (!selection) return [];
  const crumbs = [selection.org];
  if (selection.vendor) crumbs.push(selection.vendor);
  if (selection.year) crumbs.push(selection.year);
  if (selection.month) crumbs.push(selection.month);
  return crumbs;
}

export function filterVaultApiFiles<
  T extends { org: string; vendor: string; year: string; month: string },
>(files: T[], selection: VaultSelection | null): T[] {
  if (!selection) return [];
  return files.filter((f) => {
    if (f.org !== selection.org) return false;
    if (selection.vendor && f.vendor !== selection.vendor) return false;
    if (selection.year && f.year !== selection.year) return false;
    if (selection.month && f.month !== selection.month) return false;
    return true;
  });
}

export function selectionFromNode(node: VaultTreeNode): VaultSelection {
  const parts = node.id.split("/");
  return {
    org: parts[0] ?? node.label,
    vendor: parts[1],
    year: parts[2],
    month: parts[3],
  };
}

export function toTreeNodes(nodes: ApiVaultTreeNode[]): VaultTreeNode[] {
  return nodes.map((node) => ({
    ...node,
    kind: node.kind as VaultTreeNode["kind"],
    children: toTreeNodes(node.children),
  }));
}

export { fetchAllInvoices } from "@/lib/invoices";
