import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Layers,
} from "lucide-react";
import type { VaultApiFile, VaultDocumentSetInvoice } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { LazyInvoiceDetailDrawer } from "@/components/LazyInvoiceDetailDrawer";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageHeader } from "@/components/PageHeader";
import { PageTabs } from "@/components/PageTabs";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { VaultPageSkeleton } from "@/components/skeleton/PageSkeletons";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { canRenderTenantOwnedUi } from "@/lib/tenantSession";
import { useRuleBookDocumentTypes } from "@/hooks/useRuleBookConfig";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import {
  MappedDocumentTypeBadge,
  VisionHeadingBadge,
} from "@/components/inbox/DocumentTypeDisplay";
import {
  VAULT_POLL_MS,
  useVaultDocumentSets,
  useVaultFileByInvoice,
  useVaultFiles,
  useVaultTree,
} from "@/hooks/useVault";
import {
  invoiceSourceKind,
  invoiceSourceLabel,
} from "@/lib/invoice";
import { tenantQueryKey } from "@/lib/queryClient";
import {
  accordionExpandedIds,
  filterVaultApiFiles,
  findVaultFileByInvoiceId,
  findVaultNodeById,
  selectionBreadcrumb,
  selectionFromNode,
  selectionFromVaultFile,
  toTreeNodes,
  vaultAncestorIds,
  vaultNodeIdFromFile,
  type VaultSelection,
  type VaultTreeNode,
} from "@/lib/vault";
import { cn } from "@/lib/cn";
import { matchesListSearch } from "@/lib/listSearch";
import { money, vaultDocLabel, vaultDocSubtitle } from "@/lib/format";

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
  const folderTone = depth % 8;
  const folderIconClass = cn(
    "h-4 w-4 shrink-0",
    `vault-folder-icon vault-folder-icon--d${folderTone}`
  );

  return (
    <div className="min-w-0" style={{ paddingLeft: depth > 0 ? `${depth * 10}px` : undefined }}>
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
            <FolderOpen className={folderIconClass} />
          ) : (
            <Folder className={folderIconClass} />
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

type DrawerTab = "fields" | "audit";

function fileSearchHaystack(file: VaultApiFile): Array<string | number | null | undefined> {
  return [
    file.vendor,
    file.file_name,
    file.purchase_document_type,
    file.po_folder,
    file.invoice_id,
    file.invoice_no,
    file.document_ref,
    file.document_heading,
  ];
}

function fileDocLabel(file: VaultApiFile): string {
  return vaultDocLabel({ id: file.invoice_id, document_ref: file.document_ref });
}

function fileDocSubtitle(file: VaultApiFile): string {
  return vaultDocSubtitle({
    invoice_no: file.invoice_no ?? null,
    invoice_date: file.invoice_date ?? null,
  });
}

function setInvoiceLabel(doc: VaultDocumentSetInvoice): string {
  return vaultDocLabel({ id: doc.id, document_ref: doc.document_ref });
}

function setInvoiceSubtitle(doc: VaultDocumentSetInvoice): string {
  return vaultDocSubtitle({
    invoice_no: doc.invoice_no ?? null,
    invoice_date: doc.invoice_date ?? null,
  });
}

export function VaultPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { data: documentTypes } = useRuleBookDocumentTypes();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<"files" | "sets">("files");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selection, setSelection] = useState<VaultSelection | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [drawerId, setDrawerId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitialTab, setDrawerInitialTab] = useState<DrawerTab>("fields");
  const [deepLinkNotice, setDeepLinkNotice] = useState<string | null>(null);

  const orgLabel = user?.tenant_name ?? "your organisation";
  const tenantScope = user?.tenant_id ?? null;
  const scopeOk = canRenderTenantOwnedUi(tenantScope);

  const {
    data: vaultData,
    isLoading: treeLoading,
    isError: treeError,
    error: treeErrorValue,
    refetch: refetchTree,
  } = useVaultTree();
  const folderFilesEnabled = Boolean(selection?.book);
  const {
    data: folderFiles,
    isLoading: folderFilesLoading,
    refetch: refetchFolderFiles,
  } = useVaultFiles(selection, folderFilesEnabled);
  const {
    data: documentSetPayload,
    isLoading: setsLoading,
    refetch: refetchSets,
  } = useVaultDocumentSets(tab === "sets");

  useResetOnTenantChange(() => {
    setSelectedId(null);
    setSelection(null);
    setExpanded(new Set());
    setDrawerId(null);
    setDrawerOpen(false);
    setDeepLinkNotice(null);
    setSearchQuery("");
    setTab("files");
  });

  useEffect(() => {
    setSelectedId(null);
    setSelection(null);
    setExpanded(new Set());
  }, [user?.tenant_id]);

  useVisibilityPolling(() => {
    return Promise.all([
      refetchTree(),
      folderFilesEnabled ? refetchFolderFiles() : Promise.resolve(),
      tab === "sets" ? refetchSets() : Promise.resolve(),
    ]);
  }, VAULT_POLL_MS);

  const folderTree = useMemo(() => toTreeNodes(vaultData?.tree ?? []), [vaultData]);

  useEffect(() => {
    if (folderTree.length === 0) return;
    if (selectedId) return;
    const orgNode = folderTree[0];
    setSelectedId(orgNode.id);
    setSelection(selectionFromNode(orgNode));
    setExpanded(new Set([orgNode.id]));
  }, [folderTree, selectedId]);

  const vaultFiles = folderFilesEnabled ? (folderFiles?.files ?? []) : (vaultData?.files ?? []);
  const selectedNode = useMemo(
    () => findVaultNodeById(folderTree, selectedId),
    [folderTree, selectedId]
  );

  const visibleFiles = useMemo(
    () => (folderFilesEnabled ? vaultFiles : filterVaultApiFiles(vaultFiles, selection)),
    [vaultFiles, selection, folderFilesEnabled]
  );

  const filteredVisibleFiles = useMemo(() => {
    if (!searchQuery.trim()) return visibleFiles;
    return visibleFiles.filter((file) =>
      matchesListSearch(searchQuery, ...fileSearchHaystack(file))
    );
  }, [visibleFiles, searchQuery]);

  const folderFileCount = searchQuery.trim()
    ? filteredVisibleFiles.length
    : (selectedNode?.count ?? folderFiles?.count ?? vaultData?.file_count ?? filteredVisibleFiles.length);

  const documentSetCards = documentSetPayload?.sets ?? [];
  const filteredDocumentSetCards = useMemo(() => {
    if (!searchQuery.trim()) return documentSetCards;
    return documentSetCards
      .map((set) => ({
        ...set,
        invoices: set.invoices.filter((doc) =>
          matchesListSearch(
            searchQuery,
            doc.vendor,
            doc.invoice_no,
            doc.document_ref,
            doc.document_heading,
            doc.id
          )
        ),
      }))
      .filter((set) => set.invoices.length > 0 || matchesListSearch(searchQuery, set.set_name, set.pattern));
  }, [documentSetCards, searchQuery]);

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

  const openDrawer = (id: number, options?: { tab?: DrawerTab }) => {
    setDrawerInitialTab(options?.tab ?? "fields");
    setDrawerId(id);
    setDrawerOpen(true);
  };

  const refreshVault = () => {
    void queryClient.invalidateQueries({ queryKey: tenantQueryKey(["vault"] as const) });
  };

  const pendingInvoiceParam = searchParams.get("invoice");
  const pendingTabParam = searchParams.get("tab");
  const pendingInvoiceId = Number(pendingInvoiceParam);
  const deepLinkInvoiceId =
    pendingInvoiceParam && Number.isFinite(pendingInvoiceId) && pendingInvoiceId > 0
      ? pendingInvoiceId
      : null;
  const { data: deepLinkFiles, isFetched: deepLinkFetched } = useVaultFileByInvoice(
    deepLinkInvoiceId,
    Boolean(deepLinkInvoiceId) && Boolean(vaultData)
  );

  useEffect(() => {
    if (!pendingInvoiceParam || !vaultData) return;

    const clearDeepLinkParams = () => {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete("invoice");
      nextParams.delete("tab");
      setSearchParams(nextParams, { replace: true });
    };

    if (deepLinkInvoiceId == null) {
      setDeepLinkNotice(`Invalid invoice id: ${pendingInvoiceParam}`);
      clearDeepLinkParams();
      return;
    }

    const drawerTab: DrawerTab = pendingTabParam === "audit" ? "audit" : "fields";
    const file =
      findVaultFileByInvoiceId(vaultFiles, deepLinkInvoiceId) ??
      deepLinkFiles?.files[0] ??
      undefined;

    if (file) {
      setTab("files");
      const nodeId = vaultNodeIdFromFile(file);
      setSelectedId(nodeId);
      setSelection(selectionFromVaultFile(file));
      setExpanded(new Set(vaultAncestorIds(nodeId)));
      setDeepLinkNotice(null);
      openDrawer(deepLinkInvoiceId, { tab: drawerTab });
      clearDeepLinkParams();
      return;
    }

    if (!deepLinkFetched) return;

    setDeepLinkNotice(`Invoice #${deepLinkInvoiceId} was not found.`);
    clearDeepLinkParams();
  }, [
    pendingInvoiceParam,
    pendingTabParam,
    vaultData,
    vaultFiles,
    deepLinkFiles,
    deepLinkFetched,
    deepLinkInvoiceId,
    searchParams,
    setSearchParams,
  ]);

  if (treeLoading && !vaultData) {
    return (
      <div>
        <PageHeader title="Vault" subtitle={`Document vault for ${orgLabel}.`} />
        <VaultPageSkeleton />
      </div>
    );
  }

  if (!scopeOk) {
    return (
      <div>
        <PageHeader title="Vault" subtitle={`Document vault for ${orgLabel}.`} />
        <Card className="p-8 text-center text-sm text-muted-foreground">Loading organisation…</Card>
      </div>
    );
  }

  if (treeError && !vaultData) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {treeErrorValue instanceof Error ? treeErrorValue.message : "Failed to load vault"}
      </Card>
    );
  }

  const treeEmpty = folderTree.length === 0 && (vaultData?.file_count ?? 0) === 0;

  return (
    <div>
      <PageHeader title="Vault" subtitle={`Document vault for ${orgLabel}.`} />

      {deepLinkNotice && (
        <Card className="mb-4 ds-warning-panel border px-4 py-3 text-sm ds-warning-text">
          {deepLinkNotice}
        </Card>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <PageTabs
          className="min-w-0 flex-1"
          value={tab}
          onChange={(value) => setTab(value as "files" | "sets")}
          data-testid="vault-tabs"
          tabs={[
            { value: "files", label: "Files", testid: "tab-files" },
            { value: "sets", label: "Document sets", testid: "tab-sets" },
          ]}
        />
        {!treeEmpty ? (
          <ListSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search this list…"
            testId="input-vault-search"
            className="mb-1 ml-auto"
          />
        ) : null}
      </div>

      {treeEmpty ? (
        <EmptyState
          title="Vault is empty"
          hint="Documents appear here once captured and stored — filed under org → vendor → year → month."
          action={
            <Link
              to="/upload"
              className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              data-testid="button-load-samples"
            >
              Go to Upload
            </Link>
          }
        />
      ) : tab === "sets" ? (
        setsLoading && documentSetCards.length === 0 ? (
          <VaultPageSkeleton />
        ) : filteredDocumentSetCards.length === 0 ? (
          <Card className="px-8 py-14 text-center text-sm text-muted-foreground">
            <p className="py-2">
              {searchQuery.trim()
                ? "No documents match your search."
                : "No document set rules defined. Add sets in the Rule Book."}
            </p>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {filteredDocumentSetCards.map((set) => (
              <Card key={set.id} className="p-4" data-testid={`set-${set.id}`}>
                <div className="flex items-center gap-2 mb-2">
                  <Layers className="h-4 w-4 text-primary shrink-0" />
                  <h3 className="text-sm font-semibold truncate">{set.set_name}</h3>
                  <Badge variant="outline" className="tnum ml-auto text-[10px]">
                    {set.match_count}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground mb-3 tnum">Pattern: {set.pattern}</p>
                <div className="space-y-1.5">
                  {set.invoices.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No matched documents.</p>
                  ) : (
                    set.invoices.map((doc) => (
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
                            {setInvoiceLabel(doc)} · {doc.vendor ?? "Unknown vendor"}
                          </div>
                          <div className="text-xs text-muted-foreground truncate tnum">
                            {setInvoiceSubtitle(doc)}
                          </div>
                        </div>
                        <SourceBadge source={invoiceSourceKind(doc)} />
                        <VisionHeadingBadge inv={doc} empty="" />
                        <MappedDocumentTypeBadge inv={doc} documentTypes={documentTypes} />
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
        <div className="vault-explorer-grid">
          <Card className="p-3 h-fit min-w-0 overflow-hidden">
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
                {folderFileCount} files
              </Badge>
            </div>

            {folderFilesEnabled && folderFilesLoading && vaultFiles.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-10">Loading files…</p>
            ) : filteredVisibleFiles.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-10">
                {searchQuery.trim()
                  ? "No documents match your search."
                  : "No documents in this folder."}
              </p>
            ) : (
              <div className="divide-y divide-border/60">
                {filteredVisibleFiles.map((file: VaultApiFile) => (
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
                        {fileDocLabel(file)} · {file.vendor}
                      </div>
                      <div className="text-xs text-muted-foreground truncate tnum">
                        {file.purchase_document_type
                          ? `${file.purchase_document_type.toUpperCase()} · `
                          : ""}
                        {file.po_folder ? `${file.po_folder} · ` : ""}
                        {fileDocSubtitle(file)}
                      </div>
                    </div>
                    <SourceBadge source={invoiceSourceKind(file)} />
                    <VisionHeadingBadge inv={file} empty="" />
                    <MappedDocumentTypeBadge inv={file} documentTypes={documentTypes} />
                    <span className="tnum text-sm font-medium shrink-0">
                      {money(file.total, file.currency)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      <LazyInvoiceDetailDrawer
        invoiceId={drawerId}
        open={drawerOpen}
        initialTab={drawerInitialTab}
        onClose={() => {
          setDrawerOpen(false);
          setDrawerId(null);
        }}
        onUpdated={refreshVault}
      />
    </div>
  );
}
