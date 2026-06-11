import type { VaultApiFile, VaultTreeNode as ApiVaultTreeNode } from "@/api/types";

export type VaultSelection = {
  org: string;
  book?: string;
  vendor?: string;
  year?: string;
  month?: string;
  poFolder?: string;
};

export type VaultTreeNode = {
  id: string;
  label: string;
  kind: "org" | "book" | "vendor" | "year" | "month" | "po";
  count: number;
  children: VaultTreeNode[];
};

export function vaultAncestorIds(nodeId: string): string[] {
  const parts = nodeId.split("/").filter(Boolean);
  return parts.map((_, index) => parts.slice(0, index + 1).join("/"));
}

/** Keep only one open branch — org → one book → one vendor → one year. */
export function accordionExpandedIds(
  node: VaultTreeNode,
  currentlyExpanded: Set<string>
): Set<string> {
  const isOpen = currentlyExpanded.has(node.id);

  if (node.kind === "month" || node.kind === "po" || node.children.length === 0) {
    return new Set(vaultAncestorIds(node.id));
  }

  if (isOpen) {
    if (node.kind === "year") {
      return new Set(vaultAncestorIds(node.id).slice(0, -1));
    }
    if (node.kind === "vendor") {
      return new Set(vaultAncestorIds(node.id).slice(0, -2));
    }
    if (node.kind === "book") {
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
  if (selection.book) crumbs.push(selection.book);
  if (selection.vendor) crumbs.push(selection.vendor);
  if (selection.year) crumbs.push(selection.year);
  if (selection.month) crumbs.push(selection.month);
  if (selection.poFolder) crumbs.push(selection.poFolder);
  return crumbs;
}

export function filterVaultApiFiles<
  T extends {
    org: string;
    book: string;
    vendor: string;
    year: string;
    month: string;
    po_folder?: string | null;
  },
>(files: T[], selection: VaultSelection | null): T[] {
  if (!selection) return [];
  return files.filter((f) => {
    if (f.org !== selection.org) return false;
    if (selection.book && f.book !== selection.book) return false;
    if (selection.vendor && f.vendor !== selection.vendor) return false;
    if (selection.year && f.year !== selection.year) return false;
    if (selection.month && f.month !== selection.month) return false;
    if (selection.poFolder && (f.po_folder ?? "") !== selection.poFolder) return false;
    return true;
  });
}

export function selectionFromNode(node: VaultTreeNode): VaultSelection {
  const parts = node.id.split("/");
  return {
    org: parts[0] ?? node.label,
    book: parts[1],
    vendor: parts[2],
    year: parts[3],
    month: parts[4],
    poFolder: parts[5],
  };
}

export function toTreeNodes(nodes: ApiVaultTreeNode[]): VaultTreeNode[] {
  return nodes.map((node) => ({
    ...node,
    kind: node.kind as VaultTreeNode["kind"],
    children: toTreeNodes(node.children),
  }));
}

export function findVaultFileByInvoiceId(
  files: VaultApiFile[],
  invoiceId: number
): VaultApiFile | undefined {
  return files.find((f) => f.invoice_id === invoiceId);
}

/** Folder node id for vault tree selection (org/book/vendor/year/month[/po]). */
export function vaultNodeIdFromFile(
  file: Pick<VaultApiFile, "org" | "book" | "vendor" | "year" | "month" | "po_folder">
): string {
  const parts = [file.org, file.book, file.vendor, file.year, file.month];
  if (file.po_folder) {
    parts.push(file.po_folder);
  }
  return parts.join("/");
}

export function selectionFromVaultFile(
  file: Pick<VaultApiFile, "org" | "book" | "vendor" | "year" | "month" | "po_folder">
): VaultSelection {
  return {
    org: file.org,
    book: file.book,
    vendor: file.vendor,
    year: file.year,
    month: file.month,
    poFolder: file.po_folder ?? undefined,
  };
}

/** In-app deep link — React Router resolves basename (e.g. /ledgerlink/vault?invoice=36). */
export function vaultInvoiceLink(
  invoiceId: number,
  options?: { tab?: "audit" | "fields" }
): string {
  const params = new URLSearchParams({ invoice: String(invoiceId) });
  if (options?.tab) {
    params.set("tab", options.tab);
  }
  return `/vault?${params.toString()}`;
}

export { fetchAllInvoices } from "@/lib/invoices";
