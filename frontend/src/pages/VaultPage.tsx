import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Layers,
} from "lucide-react";
import { api } from "@/api/client";
import type { DocumentSetRule, Invoice, VaultApiFile } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { PageHeader } from "@/components/PageHeader";
import { RoutedInvoicesPanel } from "@/components/rule-book/RoutedInvoicesPanel";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { invoiceMatchesDocSet } from "@/lib/documentSets";
import { ruleBookConfigFromApi } from "@/lib/ruleBookConfigApi";
import type { DocumentSetRule as ConfigDocumentSet } from "@/lib/v4RuleBookTypes";
import {
  invoiceDocumentType,
  invoiceDocumentTypeLabel,
  invoiceSourceKind,
  invoiceSourceLabel,
} from "@/lib/invoice";
import {
  accordionExpandedIds,
  fetchAllInvoices,
  filterVaultApiFiles,
  selectionBreadcrumb,
  selectionFromNode,
  toTreeNodes,
  vaultAncestorIds,
  type VaultSelection,
  type VaultTreeNode,
} from "@/lib/vault";
import { cn } from "@/lib/cn";
import { money, vaultDocLabel, vaultDocSubtitle } from "@/lib/format";

const VAULT_POLL_MS = 30_000;
const API_HINT = " Ensure the API is running on port 8001.";

function SourceBadge({ source }: { source: ReturnType<typeof invoiceSourceKind> }) {
  return (
    <Badge
      variant="outline"
      className="text-[10px] font-normal border-border text-muted-foreground shrink-0"
    >
      {invoiceSourceLabel(source)}
    </Badge>
  );
}

function DocTypeBadge({ type }: { type: ReturnType<typeof invoiceDocumentType> }) {
  return (
    <Badge className="bg-accent text-accent-foreground border-0 text-[10px] shrink-0 font-normal">
      {invoiceDocumentTypeLabel(type)}
    </Badge>
  );
}

type DocSetWithDocs = ConfigDocumentSet & { docs: Invoice[] };

function toApiDocSet(set: ConfigDocumentSet): DocumentSetRule {
  return {
    id: set.id,
    pattern: set.pattern,
    set_name: set.setName,
    isolated: set.isolated,
  };
}

function VaultTreeItem({
  node,
  depth,
  expanded,
  selectedId,
  onToggle,
  onSelect,
}: {
  node: VaultTreeNode;
  depth: number;
  expanded: Set<string>;
  selectedId: string | null;
  onToggle: (node: VaultTreeNode) => void;
  onSelect: (node: VaultTreeNode) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isOpen = expanded.has(node.id);
  const isSelected = selectedId === node.id;

  return (
    <div className="min-w-0" style={{ paddingLeft: depth > 0 ? `${depth * 12}px` : undefined }}>
      <div
        className={cn(
          "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm hover-elevate min-w-0",
          isSelected && "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
        )}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => onToggle(node)}
            className="shrink-0 rounded hover:bg-muted/60"
            aria-label={isOpen ? "Collapse folder" : "Expand folder"}
          >
            {isOpen ? (
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
            )}
          </button>
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        <button
          type="button"
          onClick={() => onSelect(node)}
          className="flex-1 flex items-center gap-2 min-w-0 text-left"
          title={node.label}
          data-testid={`folder-${node.id.replace(/[/\s&]+/g, "-")}`}
        >
          {isSelected || isOpen ? (
            <FolderOpen className="h-4 w-4 shrink-0 text-primary" />
          ) : (
            <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="flex-1 text-left truncate">{node.label}</span>
          <Badge variant="outline" className="tnum text-[10px] shrink-0">
            {node.count}
          </Badge>
        </button>
      </div>
      {hasChildren && isOpen && (
        <div>
          {node.children.map((child) => (
            <VaultTreeItem
              key={child.id}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              selectedId={selectedId}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function VaultPage() {
  const { user } = useAuth();
  const [vaultData, setVaultData] = useState<Awaited<ReturnType<typeof api.getVaultTree>> | null>(
    null
  );
  const [rows, setRows] = useState<Invoice[]>([]);
  const [documentSets, setDocumentSets] = useState<ConfigDocumentSet[]>([]);
  const [tab, setTab] = useState<"files" | "sets">("files");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selection, setSelection] = useState<VaultSelection | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [drawerId, setDrawerId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const orgLabel = user?.org_name ?? "your organisation";

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
      setError(null);
      setWarning(null);
    }
    const fresh = options?.fresh ?? !options?.silent;

    const [vaultResult, invoicesResult, configResult] = await Promise.allSettled([
      api.getVaultTree({ fresh }),
      fetchAllInvoices(fresh),
      api.getRuleBookConfig(),
    ]);

    if (vaultResult.status === "fulfilled") {
      setVaultData(vaultResult.value);
    } else if (!options?.silent) {
      setVaultData(null);
      setError(
        vaultResult.reason instanceof Error
          ? vaultResult.reason.message + API_HINT
          : "Failed to load vault" + API_HINT
      );
    }

    if (invoicesResult.status === "fulfilled") {
      setRows(invoicesResult.value);
    } else if (!options?.silent) {
      setRows([]);
      setWarning(
        invoicesResult.reason instanceof Error
          ? invoicesResult.reason.message
          : "Failed to load invoices for document sets"
      );
    }

    if (configResult.status === "fulfilled") {
      setDocumentSets(ruleBookConfigFromApi(configResult.value).documentSets);
    } else if (!options?.silent) {
      setDocumentSets([]);
      setWarning((prev) =>
        prev
          ? `${prev}; rule book unavailable`
          : "Rule book unavailable — document sets may be empty"
      );
    }

    if (!options?.silent) setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load, user?.org_id]);

  useEffect(() => {
    setSelectedId(null);
    setSelection(null);
    setExpanded(new Set());
  }, [user?.org_id]);

  useVisibilityPolling(() => {
    void load({ silent: true, fresh: true });
  }, VAULT_POLL_MS);

  const invoiceById = useMemo(() => new Map(rows.map((doc) => [doc.id, doc])), [rows]);

  const vaultFiles = vaultData?.files ?? [];
  const folderTree = useMemo(() => toTreeNodes(vaultData?.tree ?? []), [vaultData]);

  useEffect(() => {
    if (folderTree.length === 0) return;
    if (selectedId) return;
    const orgNode = folderTree[0];
    setSelectedId(orgNode.id);
    setSelection(selectionFromNode(orgNode));
    setExpanded(new Set([orgNode.id]));
  }, [folderTree, selectedId]);

  const visibleFiles = useMemo(
    () => filterVaultApiFiles(vaultFiles, selection),
    [vaultFiles, selection]
  );

  const documentSetCards = useMemo((): DocSetWithDocs[] => {
    const sets = documentSets;
    const assigned = new Set<number>();
    return sets.map((set) => {
      let docs = rows.filter((inv) => invoiceMatchesDocSet(inv, toApiDocSet(set).pattern));
      if (set.isolated ?? false) {
        docs = docs.filter((inv) => !assigned.has(inv.id));
        for (const inv of docs) assigned.add(inv.id);
      }
      return { ...set, docs };
    });
  }, [documentSets, rows]);

  const breadcrumbs = useMemo(() => selectionBreadcrumb(selection), [selection]);

  const toggleExpanded = (node: VaultTreeNode) => {
    setExpanded((prev) => accordionExpandedIds(node, prev));
  };

  const selectNode = (node: VaultTreeNode) => {
    const nextSelection = selectionFromNode(node);
    setSelectedId(node.id);
    setSelection(nextSelection);
    setExpanded(new Set(vaultAncestorIds(node.id)));
  };

  const openDrawer = (id: number) => {
    setDrawerId(id);
    setDrawerOpen(true);
  };

  if (loading && !vaultData) {
    return (
      <div>
        <PageHeader title="Vault" subtitle={`Document vault for ${orgLabel}.`} />
        <Card className="p-8 text-center text-sm text-muted-foreground">Loading vault…</Card>
      </div>
    );
  }

  if (error && !vaultData) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {error}
      </Card>
    );
  }

  return (
    <div>
      <PageHeader title="Vault" subtitle={`Document vault for ${orgLabel}.`} />

      {error && (
        <Card className="p-3 mb-4 text-xs text-destructive border-destructive/30 bg-destructive/5">
          {error}
        </Card>
      )}

      {warning && !error && (
        <Card className="p-3 mb-4 text-xs text-muted-foreground border-dashed">
          {warning}
        </Card>
      )}

      <div className="mb-5">
        <RoutedInvoicesPanel
          routeTarget="Vault"
          title="Routed to Vault"
          hint="Documents assigned Vault by email capture rules."
          testId="routed-vault-invoices"
        />
      </div>

      <div className="flex gap-1 mb-4 border-b border-border">
        {(
          [
            { id: "files" as const, label: "Files" },
            { id: "sets" as const, label: "Document sets" },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            data-testid={`tab-${t.id}`}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t.id
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && vaultFiles.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">Loading vault…</Card>
      ) : vaultFiles.length === 0 ? (
        <EmptyState
          title="Vault is empty"
          hint="Documents appear here once captured and stored — filed under org → vendor → year → month."
          action={
            <Link
              to="/inbox"
              className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              data-testid="button-load-samples"
            >
              Go to Inbox
            </Link>
          }
        />
      ) : tab === "sets" ? (
        documentSetCards.length === 0 ? (
          <Card className="p-8 text-center text-sm text-muted-foreground">
            No document set rules defined. Add sets in the Rule Book.
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {documentSetCards.map((set) => (
              <Card key={set.id} className="p-4" data-testid={`set-${set.id}`}>
                <div className="flex items-center gap-2 mb-2">
                  <Layers className="h-4 w-4 text-primary shrink-0" />
                  <h3 className="text-sm font-semibold truncate">{set.setName}</h3>
                  <Badge variant="outline" className="tnum ml-auto text-[10px]">
                    {set.docs.length}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground mb-3 tnum">Pattern: {set.pattern}</p>
                <div className="space-y-1.5">
                  {set.docs.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No matched documents.</p>
                  ) : (
                    set.docs.map((doc) => (
                      <button
                        key={doc.id}
                        type="button"
                        onClick={() => openDrawer(doc.id)}
                        className="w-full flex items-center gap-2 text-sm border-b border-border/60 pb-1.5 hover:text-primary text-left"
                        data-testid={`set-doc-${doc.id}`}
                      >
                        <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <div className="min-w-0 flex-1 truncate">
                          <div className="text-sm font-medium truncate">
                            {vaultDocLabel(doc.id)} · {doc.vendor ?? "Unknown vendor"}
                          </div>
                          <div className="text-xs text-muted-foreground truncate tnum">
                            {vaultDocSubtitle(doc)}
                          </div>
                        </div>
                        <SourceBadge source={invoiceSourceKind(doc)} />
                        <DocTypeBadge type={invoiceDocumentType(doc)} />
                        <span className="tnum text-sm font-medium shrink-0">
                          {money(doc.total, doc.currency)}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </Card>
            ))}
          </div>
        )
      ) : (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          <Card className="p-3 h-fit min-w-0">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2 px-1">
              Folders
            </div>
            <div className="mt-1 space-y-0.5 min-w-0">
              {folderTree.map((orgNode) => (
                <VaultTreeItem
                  key={orgNode.id}
                  node={orgNode}
                  depth={0}
                  expanded={expanded}
                  selectedId={selectedId}
                  onToggle={toggleExpanded}
                  onSelect={selectNode}
                />
              ))}
            </div>
          </Card>

          <Card className="overflow-hidden min-w-0">
            <div className="px-4 py-2.5 border-b border-border flex items-center gap-2 text-sm min-h-[42px]">
              <span className="text-muted-foreground shrink-0">Vault</span>
              {breadcrumbs.map((crumb, i) => (
                <span key={`${crumb}-${i}`} className="inline-flex items-center gap-2 min-w-0">
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span
                    className={cn(
                      "truncate",
                      i === breadcrumbs.length - 1 ? "font-medium" : "text-muted-foreground"
                    )}
                  >
                    {crumb}
                  </span>
                </span>
              ))}
              <Badge variant="outline" className="tnum ml-auto shrink-0">
                {visibleFiles.length} files
              </Badge>
            </div>

            {visibleFiles.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-10">
                No documents in this folder.
              </p>
            ) : (
              <div className="divide-y divide-border/60">
                {visibleFiles.map((file: VaultApiFile) => {
                  const doc = invoiceById.get(file.invoice_id);
                  return (
                    <button
                      key={file.invoice_id}
                      type="button"
                      onClick={() => openDrawer(file.invoice_id)}
                      className="w-full flex items-center gap-3 px-4 py-3 text-left hover-elevate"
                      data-testid={`file-${file.invoice_id}`}
                    >
                      <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate">
                          {doc
                            ? `${vaultDocLabel(doc.id)} · ${doc.vendor ?? file.vendor}`
                            : file.vendor}
                        </div>
                        <div className="text-xs text-muted-foreground truncate tnum">
                          {doc ? vaultDocSubtitle(doc) : file.file_name}
                        </div>
                      </div>
                      {doc && (
                        <>
                          <SourceBadge source={invoiceSourceKind(doc)} />
                          <DocTypeBadge type={invoiceDocumentType(doc)} />
                          <span className="tnum text-sm font-medium shrink-0">
                            {money(doc.total, doc.currency)}
                          </span>
                        </>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      )}

      <InvoiceDetailDrawer
        invoiceId={drawerId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onUpdated={() => load({ fresh: true })}
      />
    </div>
  );
}
