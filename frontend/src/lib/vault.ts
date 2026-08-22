import type { VaultApiFile, VaultTreeNode as ApiVaultTreeNode } from "@/api/types";

export const VAULT_BOOK_LABEL = "Vault";

export type VaultSelection = {
  org: string;
  book?: string;
  documentType?: string;
  vendor?: string;
  year?: string;
  month?: string;
  poFolder?: string;
};

export type VaultTreeNode = {
  id: string;
  label: string;
  kind: "org" | "book" | "document_type" | "vendor" | "year" | "month" | "po";
  count: number;
  children: VaultTreeNode[];
};

export function vaultAncestorIds(nodeId: string): string[] {
  const parts = nodeId.split("/").filter(Boolean);
  return parts.map((_, index) => parts.slice(0, index + 1).join("/"));
}

/** Keep only one open branch — org → one book → [one dt →] one vendor → one year. */
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
    if (node.kind === "document_type") {
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
  if (selection.documentType) crumbs.push(selection.documentType);
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
    document_type?: string | null;
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
    if (selection.documentType && (f.document_type ?? "") !== selection.documentType) return false;
    if (selection.vendor && f.vendor !== selection.vendor) return false;
    if (selection.year && f.year !== selection.year) return false;
    if (selection.month && f.month !== selection.month) return false;
    if (selection.poFolder && (f.po_folder ?? "") !== selection.poFolder) return false;
    return true;
  });
}

export function selectionFromNode(node: VaultTreeNode): VaultSelection {
  const parts = node.id.split("/");
  const sel: VaultSelection = { org: parts[0] ?? node.label };
  if (parts.length > 1) sel.book = parts[1];
  if (node.kind === "document_type") {
    sel.documentType = parts[2];
    return sel;
  }
  const vaultDt = parts[1] === VAULT_BOOK_LABEL && parts.length >= 4;
  if (vaultDt) {
    if (parts.length >= 3) sel.documentType = parts[2];
    if (parts.length >= 4) sel.vendor = parts[3];
    if (parts.length >= 5) sel.year = parts[4];
    if (parts.length >= 6) sel.month = parts[5];
    if (parts.length >= 7) sel.poFolder = parts[6];
    return sel;
  }
  if (parts.length >= 3) sel.vendor = parts[2];
  if (parts.length >= 4) sel.year = parts[3];
  if (parts.length >= 5) sel.month = parts[4];
  if (parts.length >= 6) sel.poFolder = parts[5];
  return sel;
}

export function toTreeNodes(nodes: ApiVaultTreeNode[]): VaultTreeNode[] {
  return nodes.map((node) => ({
    ...node,
    kind: node.kind as VaultTreeNode["kind"],
    children: toTreeNodes(node.children),
  }));
}

export function findVaultNodeById(
  nodes: VaultTreeNode[],
  id: string | null
): VaultTreeNode | null {
  if (!id) return null;
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findVaultNodeById(node.children, id);
    if (child) return child;
  }
  return null;
}

export function vaultSelectionQueryKey(selection: VaultSelection | null): string {
  if (!selection) return "";
  return [
    selection.org,
    selection.book ?? "",
    selection.documentType ?? "",
    selection.vendor ?? "",
    selection.year ?? "",
    selection.month ?? "",
    selection.poFolder ?? "",
  ].join("\0");
}

export function findVaultFileByInvoiceId(
  files: VaultApiFile[],
  invoiceId: number
): VaultApiFile | undefined {
  return files.find((f) => f.invoice_id === invoiceId);
}

/** Folder node id for vault tree selection (org/book/[dt]/vendor/year/month[/po]). */
export function vaultNodeIdFromFile(
  file: Pick<VaultApiFile, "org" | "book" | "document_type" | "vendor" | "year" | "month" | "po_folder">
): string {
  const parts = [file.org, file.book];
  if (file.document_type) {
    parts.push(file.document_type);
  }
  parts.push(file.vendor, file.year, file.month);
  if (file.po_folder) {
    parts.push(file.po_folder);
  }
  return parts.join("/");
}

export function selectionFromVaultFile(
  file: Pick<VaultApiFile, "org" | "book" | "document_type" | "vendor" | "year" | "month" | "po_folder">
): VaultSelection {
  return {
    org: file.org,
    book: file.book,
    documentType: file.document_type ?? undefined,
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
