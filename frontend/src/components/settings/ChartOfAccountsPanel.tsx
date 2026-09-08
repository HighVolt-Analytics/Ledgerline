import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";

import type { ChartOfAccountRow, PlatformChartOfAccountRow, SubLedgerRow } from "@/api/types";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import { BillProcessingConnectionChip } from "@/components/settings/tax/BillProcessingConnectionChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineTableSkeleton } from "@/components/skeleton/PageSkeletons";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/context/ToastContext";
import {
  CHART_OF_ACCOUNT_TYPES,
  chartOfAccountRowToPayload,
  coaTypeMisclassificationWarnings,
  inferChartOfAccountTypeFromName,
  newChartOfAccountRow,
  normalizeChartOfAccountType,
  useChartOfAccountsWorkspace,
  useCreateQboChartOfAccount,
  useCreateXeroChartOfAccount,
  useDeleteQboChartOfAccount,
  useDeleteXeroChartOfAccount,
  usePullQboChartOfAccount,
  usePullXeroChartOfAccount,
  useSaveChartOfAccounts,
  useSyncChartOfAccounts,
  useUpdateQboChartOfAccount,
  useUpdateXeroChartOfAccount,
} from "@/hooks/useChartOfAccounts";
import { cn } from "@/lib/cn";
import { newClientRowKey } from "@/lib/clientRowKey";
import {
  defaultQboAccountType,
  normalizeQboAccountType,
  qboAccountTypeOptions,
} from "@/lib/qboAccountTypes";
import { defaultXeroSubtype, normalizeXeroSubtype, xeroSubtypeOptions } from "@/lib/xeroAccountTypes";

type SubLedgerRowLocal = SubLedgerRow & { _rowKey: string };
type ChartOfAccountRowLocal = Omit<ChartOfAccountRow, "subLedgers"> & {
  _rowKey: string;
  subLedgers: SubLedgerRowLocal[];
  _inferType?: boolean;
};
type PlatformRowLocal = PlatformChartOfAccountRow & {
  _rowKey: string;
  subLedgers: SubLedgerRowLocal[];
  dirty?: boolean;
  staged?: boolean;
};

type ChartOfAccountsPanelProps = {
  canEdit?: boolean;
  onSaved?: () => void;
};

function newSubLedgerRowLocal(): SubLedgerRowLocal {
  return { code: "", name: "", _rowKey: newClientRowKey("sub-coa") };
}

function withSubKeys(subs: SubLedgerRow[] | undefined): SubLedgerRowLocal[] {
  return (subs ?? []).map((sub) => ({ ...sub, _rowKey: newClientRowKey("sub-coa") }));
}

function toLocalRow(row: ChartOfAccountRow, infer = false): ChartOfAccountRowLocal {
  return {
    ...row,
    type: normalizeChartOfAccountType(row.type),
    subLedgers: withSubKeys(row.subLedgers),
    _rowKey: newClientRowKey("coa"),
    _inferType: infer,
  };
}

function toPlatformRow(row: PlatformChartOfAccountRow, staged = false): PlatformRowLocal {
  return {
    ...row,
    subLedgers: withSubKeys(row.subLedgers),
    _rowKey: newClientRowKey("xero-coa"),
    dirty: staged,
    staged,
  };
}

function validateAccounts(accounts: { code: string; name: string; subLedgers: SubLedgerRowLocal[] }[]): string | null {
  if (!accounts.length) return null;
  const codes = new Set<string>();
  const names = new Set<string>();
  for (const row of accounts) {
    const code = row.code.trim();
    const name = row.name.trim();
    if (!code) return "Every account needs a code";
    if (!name) return "Every account needs a name";
    const codeKey = code.toUpperCase();
    if (codes.has(codeKey)) return `Duplicate account code: ${code}`;
    codes.add(codeKey);
    const nameKey = name.toLowerCase();
    if (names.has(nameKey)) return `Duplicate account name: ${name}`;
    names.add(nameKey);
    const subCodes = new Set<string>();
    const subNames = new Set<string>();
    for (const sub of row.subLedgers ?? []) {
      const subCode = sub.code.trim();
      const subName = sub.name.trim();
      if (!subCode && !subName) continue;
      if (!subCode) return `Sub-ledger under ${name} needs a code`;
      if (!subName) return `Sub-ledger under ${name} needs a name`;
      if (subCodes.has(subCode.toUpperCase())) return `Duplicate sub-ledger code ${subCode} under ${name}`;
      subCodes.add(subCode.toUpperCase());
      if (subNames.has(subName.toLowerCase())) return `Duplicate sub-ledger name ${subName} under ${name}`;
      subNames.add(subName.toLowerCase());
    }
  }
  return null;
}

function compactSubs(subs: SubLedgerRowLocal[]) {
  return subs
    .map((sub) => ({
      code: sub.code.trim(),
      name: sub.name.trim(),
      ...(sub.origin ? { origin: sub.origin } : {}),
    }))
    .filter((sub) => sub.code && sub.name);
}

function ProviderTags({ providers }: { providers?: string[] }) {
  const tags = providers ?? [];
  if (!tags.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((id) =>
        id === "xero" ? (
          <span key={id} className="inline-flex items-center gap-1 rounded-full border border-border px-1.5 py-0.5 text-[10px]">
            <IntegrationBrandIcon id="xero" size={12} />
            Xero
          </span>
        ) : id === "quickbooks" || id === "quickbooks_online" || id === "qbo" ? (
          <span key={id} className="inline-flex items-center gap-1 rounded-full border border-border px-1.5 py-0.5 text-[10px]">
            <IntegrationBrandIcon id="qbo" size={12} />
            QuickBooks
          </span>
        ) : (
          <Badge key={id} variant="outline" className="text-[10px]">
            {id}
          </Badge>
        )
      )}
    </div>
  );
}

export function ChartOfAccountsPanel({ canEdit = false, onSaved }: ChartOfAccountsPanelProps) {
  const { toast } = useToast();
  const { data, isLoading, isError, blocked } = useChartOfAccountsWorkspace();
  const saveMutation = useSaveChartOfAccounts();
  const syncMutation = useSyncChartOfAccounts();
  const createXero = useCreateXeroChartOfAccount();
  const updateXero = useUpdateXeroChartOfAccount();
  const deleteXero = useDeleteXeroChartOfAccount();
  const pullXero = usePullXeroChartOfAccount();
  const createQbo = useCreateQboChartOfAccount();
  const updateQbo = useUpdateQboChartOfAccount();
  const deleteQbo = useDeleteQboChartOfAccount();
  const pullQbo = usePullQboChartOfAccount();
  const [localRows, setLocalRows] = useState<ChartOfAccountRowLocal[]>([]);
  const [platformRows, setPlatformRows] = useState<PlatformRowLocal[]>([]);
  const [dirty, setDirty] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const stagedRef = useRef<PlatformRowLocal[]>([]);
  const isQbo = data?.source === "quickbooks_online";
  const platformConnected = Boolean(data?.xero_connected) || isQbo;
  const platformName = isQbo ? "QuickBooks" : "Xero";
  const lockedMessage = isQbo
    ? "This is a default QuickBooks account and cannot be changed."
    : "This is a default Xero account and cannot be changed.";

  useEffect(() => {
    stagedRef.current = platformRows.filter((row) => row.staged);
  }, [platformRows]);

  useEffect(() => {
    if (!data) return;
    const staged = stagedRef.current;
    const stagedCodes = new Set(staged.map((row) => row.code.trim().toUpperCase()).filter(Boolean));
    const serverPlatform = (data.platform_accounts ?? []).map((row) => toPlatformRow(row));
    const serverCodes = new Set(serverPlatform.map((row) => row.code.trim().toUpperCase()).filter(Boolean));
    const keptStaged = staged.filter((row) => {
      const code = row.code.trim().toUpperCase();
      return Boolean(code) && !serverCodes.has(code);
    });
    setLocalRows(
      (data.local_accounts ?? data.accounts ?? [])
        .filter((row) => !stagedCodes.has((row.code ?? "").trim().toUpperCase()))
        .map((row) => toLocalRow(row))
    );
    setPlatformRows([...serverPlatform, ...keptStaged]);
    setDirty(false);
  }, [data]);

  const catalogueForSave = useMemo(() => data?.accounts ?? [], [data]);

  const toggleExpanded = (rowKey: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(rowKey)) next.delete(rowKey);
      else next.add(rowKey);
      return next;
    });
  };

  const updateLocal = (index: number, patch: Partial<ChartOfAccountRowLocal>) => {
    setLocalRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    setDirty(true);
  };

  const saveLocalCatalogue = async (rows: ChartOfAccountRowLocal[]) => {
    const linkedUpdates = (data?.platform_accounts ?? [])
      .map((server) => {
        const live = platformRows.find(
          (item) => !item.staged && item.xero_account_id === server.xero_account_id
        );
        const base = catalogueForSave.find(
          (item) => item.code.trim().toUpperCase() === server.code.trim().toUpperCase()
        );
        if (!base) return null;
        return chartOfAccountRowToPayload({
          ...base,
          subLedgers: live ? compactSubs(live.subLedgers) : base.subLedgers ?? [],
        });
      })
      .filter((row): row is ReturnType<typeof chartOfAccountRowToPayload> => row != null);
    const error = validateAccounts([...rows, ...linkedUpdates.map((row) => toLocalRow(row))]);
    if (error) {
      toast({ title: error, variant: "destructive" });
      return false;
    }
    await saveMutation.mutateAsync([...rows.map((row) => chartOfAccountRowToPayload(row)), ...linkedUpdates]);
    return true;
  };

  const handleLocalSave = async () => {
    const stagedCodes = new Set(
      platformRows.filter((row) => row.staged).map((row) => row.code.trim().toUpperCase()).filter(Boolean)
    );
    const visible = localRows.filter((row) => !stagedCodes.has(row.code.trim().toUpperCase()));
    try {
      const ok = await saveLocalCatalogue(visible);
      if (!ok) return;
      setDirty(false);
      onSaved?.();
      toast({ title: "Chart of accounts saved" });
    } catch (err) {
      toast({
        title: err instanceof Error ? err.message : "Could not save chart of accounts",
        variant: "destructive",
      });
    }
  };

  const pushLocal = (index: number) => {
    const row = localRows[index];
    if (!row) return;
    const warnings = coaTypeMisclassificationWarnings([row]);
    if (warnings.length) toast({ title: "Chart of accounts type hints", description: warnings[0] });
    const staged = toPlatformRow(
      {
        xero_account_id: `staged:${row._rowKey}`,
        code: row.code,
        name: row.name,
        type: row.type,
        sub_type: isQbo ? defaultQboAccountType(row.type) : defaultXeroSubtype(row.type),
        can_edit: true,
        can_delete: true,
        can_pull: false,
        linked_providers: isQbo ? ["quickbooks"] : ["xero"],
        subLedgers: row.subLedgers,
        status: "STAGED",
      },
      true
    );
    setPlatformRows((prev) => [...prev, staged]);
    setLocalRows((prev) => prev.filter((_, i) => i !== index));
  };

  const cancelStaged = (index: number) => {
    const row = platformRows[index];
    if (!row?.staged) return;
    setLocalRows((prev) => [
      ...prev,
      toLocalRow({
        code: row.code,
        name: row.name,
        type: row.type,
        sub_type: row.sub_type,
        linked_providers: [],
        subLedgers: row.subLedgers,
      }),
    ]);
    setPlatformRows((prev) => prev.filter((_, i) => i !== index));
    setDirty(true);
  };

  const savePlatformRow = async (index: number) => {
    const row = platformRows[index];
    if (!row) return;
    const error = validateAccounts([row]);
    if (error) {
      toast({ title: error, variant: "destructive" });
      return;
    }
    const body = {
      code: row.code.trim(),
      name: row.name.trim(),
      type: row.type,
      sub_type: isQbo
        ? normalizeQboAccountType(row.type, row.sub_type)
        : normalizeXeroSubtype(row.type, row.sub_type),
      sub_ledgers: compactSubs(row.subLedgers),
    };
    try {
      if (row.staged) {
        if (isQbo) await createQbo.mutateAsync(body);
        else await createXero.mutateAsync(body);
        toast({ title: `Account created in ${platformName}` });
      } else if (isQbo) {
        await updateQbo.mutateAsync({ accountId: row.xero_account_id, body });
        toast({
          title: row.can_edit === false ? "Sub-ledgers saved" : "Account updated in QuickBooks",
        });
      } else {
        await updateXero.mutateAsync({ accountId: row.xero_account_id, body });
        toast({
          title: row.can_edit === false ? "Sub-ledgers saved" : "Account updated in Xero",
        });
      }
      onSaved?.();
    } catch (err) {
      toast({
        title: err instanceof Error ? err.message : `Could not save ${platformName} account`,
        variant: "destructive",
      });
    }
  };

  if (isLoading || blocked) {
    return (
      <Card className="w-full overflow-hidden" data-testid="chart-of-accounts-panel">
        <InlineTableSkeleton rows={8} columns={4} />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card className="w-full p-6 text-sm text-destructive">
        Could not load chart of accounts for this organisation.
      </Card>
    );
  }

  const renderSubLedgers = (
    row: { _rowKey: string; name: string; subLedgers: SubLedgerRowLocal[]; linked_providers?: string[] },
    onChange: (subs: SubLedgerRowLocal[]) => void,
    colSpan: number
  ) => (
    <tr className="border-b border-border/60 bg-muted/20">
      <td colSpan={colSpan} className="px-4 py-3">
        <div className="space-y-2 pl-6">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[11px] font-medium text-muted-foreground">
              Sub-ledgers for {row.name.trim() || "this account"}
            </p>
            <ProviderTags providers={row.linked_providers} />
          </div>
          {row.subLedgers.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">No sub-ledgers defined.</p>
          ) : (
            <div className="space-y-1">
              {row.subLedgers.map((sub, subIndex) => (
                <div key={sub._rowKey} className="flex flex-wrap items-center gap-2">
                  {canEdit ? (
                    <>
                      <Input
                        value={sub.code}
                        onChange={(e) =>
                          onChange(
                            row.subLedgers.map((item, j) =>
                              j === subIndex ? { ...item, code: e.target.value } : item
                            )
                          )
                        }
                        className="h-7 w-24 font-mono text-xs"
                        placeholder="Code"
                      />
                      <Input
                        value={sub.name}
                        onChange={(e) =>
                          onChange(
                            row.subLedgers.map((item, j) =>
                              j === subIndex ? { ...item, name: e.target.value } : item
                            )
                          )
                        }
                        className="h-7 min-w-[10rem] flex-1 text-xs"
                        placeholder="Sub-ledger name"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive"
                        onClick={() => onChange(row.subLedgers.filter((_, j) => j !== subIndex))}
                        aria-label="Remove sub-ledger"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      <span className="tnum font-mono">{sub.code}</span>
                      {" · "}
                      {sub.name}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          {canEdit ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => onChange([...row.subLedgers, newSubLedgerRowLocal()])}
            >
              <Plus className="mr-1 h-3 w-3" />
              Add sub-ledger
            </Button>
          ) : null}
        </div>
      </td>
    </tr>
  );

  const localColSpan = canEdit ? (platformConnected ? 6 : 5) : 4;

  return (
    <div className="w-full space-y-6" data-testid="chart-of-accounts-panel">
      <div>
        <h2 className="text-sm font-semibold">Chart of accounts</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Local GL accounts used for posting. Sub-ledgers stay in LedgerLink when Xero is connected.
          When QuickBooks is connected, sub-ledgers are written as QuickBooks subaccounts.
        </p>
      </div>

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-2 py-2 w-8" />
              <th className="px-2 py-2 font-medium">Code</th>
              <th className="px-3 py-2 font-medium">GL Account</th>
              <th className="px-3 py-2 font-medium">Type</th>
              {canEdit && platformConnected ? <th className="px-2 py-2 w-10 font-medium">Push</th> : null}
              {canEdit ? <th className="px-3 py-2 w-10" /> : null}
            </tr>
          </thead>
          <tbody>
            {localRows.length === 0 ? (
              <tr>
                <td colSpan={localColSpan} className="px-3 py-8 text-center text-sm text-muted-foreground">
                  {platformConnected
                    ? `No local-only accounts. Parents that exist in ${platformName} appear in the list below.`
                    : "No accounts yet."}
                </td>
              </tr>
            ) : (
              localRows.map((row, index) => {
                const expanded = expandedKeys.has(row._rowKey);
                const subCount = row.subLedgers.filter((sub) => sub.code.trim() || sub.name.trim()).length;
                return (
                  <Fragment key={row._rowKey}>
                    <tr className="row-band border-b border-border/60">
                      <td className="px-2 py-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground"
                          onClick={() => toggleExpanded(row._rowKey)}
                          aria-label={expanded ? "Collapse sub-ledgers" : "Expand sub-ledgers"}
                        >
                          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </Button>
                      </td>
                      <td className="px-2 py-2">
                        {canEdit ? (
                          <Input
                            value={row.code}
                            onChange={(e) => updateLocal(index, { code: e.target.value })}
                            className="h-8 font-mono text-xs"
                          />
                        ) : (
                          <span className="tnum text-muted-foreground">{row.code}</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          {canEdit ? (
                            <Input
                              value={row.name}
                              onChange={(e) => updateLocal(index, { name: e.target.value })}
                              onBlur={(e) => {
                                if (!row._inferType) return;
                                const name = e.target.value.trim();
                                if (!name) return;
                                updateLocal(index, {
                                  type: inferChartOfAccountTypeFromName(name),
                                  _inferType: false,
                                });
                              }}
                              className="h-8 flex-1 text-xs"
                            />
                          ) : (
                            <span>{row.name}</span>
                          )}
                          {subCount > 0 ? (
                            <Badge variant="secondary" className="shrink-0 text-[10px]">
                              {subCount} sub-ledger{subCount === 1 ? "" : "s"}
                            </Badge>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        {canEdit ? (
                          <Select
                            value={row.type}
                            onValueChange={(type) =>
                              updateLocal(index, {
                                type: normalizeChartOfAccountType(type),
                                _inferType: false,
                              })
                            }
                            options={CHART_OF_ACCOUNT_TYPES.map((type) => ({ value: type, label: type }))}
                            className="w-full min-w-[7rem]"
                          />
                        ) : (
                          <Badge variant="outline" className="text-[10px]">
                            {row.type}
                          </Badge>
                        )}
                      </td>
                      {canEdit && platformConnected ? (
                        <td className="px-2 py-2">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 cursor-pointer text-muted-foreground hover:text-foreground"
                            onClick={() => pushLocal(index)}
                            aria-label={`Push ${row.name || row.code} to ${platformName}`}
                            title={`Push to ${platformName}`}
                            data-testid={`coa-push-${index}`}
                          >
                            <ArrowUpFromLine className="h-4 w-4" />
                          </Button>
                        </td>
                      ) : null}
                      {canEdit ? (
                        <td className="px-3 py-2 text-right">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            onClick={() => {
                              setLocalRows((prev) => prev.filter((_, i) => i !== index));
                              setDirty(true);
                            }}
                            disabled={!platformConnected && localRows.length <= 1}
                            aria-label="Remove account"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </td>
                      ) : null}
                    </tr>
                    {expanded
                      ? renderSubLedgers(
                          row,
                          (subs) => updateLocal(index, { subLedgers: subs }),
                          localColSpan
                        )
                      : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </Card>

      {canEdit ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setLocalRows((prev) => [...prev, toLocalRow(newChartOfAccountRow(), true)]);
              setDirty(true);
            }}
          >
            <Plus className="mr-1 h-4 w-4" />
            Add account
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => void handleLocalSave()}
            disabled={!dirty || saveMutation.isPending}
            className={cn(saveMutation.isPending && "opacity-70")}
            data-testid="coa-save"
          >
            {saveMutation.isPending ? (
              <>
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                Saving…
              </>
            ) : (
              "Save chart of accounts"
            )}
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Only admins can edit the chart of accounts.</p>
      )}

      {platformConnected ? (
        <div className="space-y-3" data-testid="platform-chart-of-accounts">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-sm font-semibold">{platformName} chart of accounts</h2>
            {canEdit ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 cursor-pointer text-muted-foreground"
                onClick={() => {
                  void syncMutation.mutateAsync().then(
                    () => toast({ title: `Synced accounts from ${platformName}` }),
                    (err: unknown) =>
                      toast({
                        title: err instanceof Error ? err.message : `Could not sync from ${platformName}`,
                        variant: "destructive",
                      })
                  );
                }}
                disabled={syncMutation.isPending}
                aria-label={`Sync chart of accounts from ${platformName}`}
                data-testid="button-sync-chart-of-accounts"
              >
                <RefreshCw className={syncMutation.isPending ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
              </Button>
            ) : null}
            <BillProcessingConnectionChip
              brandId={isQbo ? "qbo" : "xero"}
              providerName={platformName}
              organisationName={data?.provider?.organisation_name}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            {isQbo
              ? "Exact copy of GL accounts in the connected QuickBooks company. Sub-ledgers are QuickBooks subaccounts. Assign a type, then Save to write to QuickBooks."
              : "Exact copy of GL accounts in the connected Xero organisation. Assign a sub type, then Save to write to Xero."}
          </p>
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="px-2 py-2 w-8" />
                  <th className="px-2 py-2 font-medium">Code</th>
                  <th className="px-3 py-2 font-medium">GL Account</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Sub type</th>
                  {canEdit ? <th className="px-2 py-2 w-10 font-medium">Pull</th> : null}
                  {canEdit ? <th className="px-2 py-2 w-10 font-medium">Save</th> : null}
                  {canEdit ? <th className="px-2 py-2 w-10" /> : null}
                </tr>
              </thead>
              <tbody>
                {platformRows.length === 0 ? (
                  <tr>
                    <td colSpan={canEdit ? 8 : 5} className="px-3 py-8 text-center text-sm text-muted-foreground">
                      No {platformName} accounts yet. Use sync, or push a local account.
                    </td>
                  </tr>
                ) : (
                  platformRows.map((row, index) => {
                    const expanded = expandedKeys.has(row._rowKey);
                    const locked = row.can_edit === false;
                    return (
                      <Fragment key={row._rowKey}>
                        <tr className="row-band border-b border-border/60">
                          <td className="px-2 py-2">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground"
                              onClick={() => toggleExpanded(row._rowKey)}
                            >
                              {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                            </Button>
                          </td>
                          <td className="px-2 py-2">
                            {canEdit && !locked ? (
                              <Input
                                value={row.code}
                                maxLength={10}
                                onChange={(e) =>
                                  setPlatformRows((prev) =>
                                    prev.map((item, i) =>
                                      i === index ? { ...item, code: e.target.value, dirty: true } : item
                                    )
                                  )
                                }
                                className="h-8 font-mono text-xs"
                              />
                            ) : (
                              <span className="tnum text-muted-foreground">{row.code}</span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            {canEdit && !locked ? (
                              <Input
                                value={row.name}
                                maxLength={150}
                                onChange={(e) =>
                                  setPlatformRows((prev) =>
                                    prev.map((item, i) =>
                                      i === index ? { ...item, name: e.target.value, dirty: true } : item
                                    )
                                  )
                                }
                                className="h-8 text-xs"
                              />
                            ) : (
                              <span>{row.name}</span>
                            )}
                            {row.staged ? (
                              <Badge variant="outline" className="ml-2 text-[10px]">
                                New
                              </Badge>
                            ) : null}
                          </td>
                          <td className="px-3 py-2">
                            {canEdit && !locked ? (
                              <Select
                                value={row.type}
                                onValueChange={(type) => {
                                  const next = normalizeChartOfAccountType(type);
                                  setPlatformRows((prev) =>
                                    prev.map((item, i) =>
                                      i === index
                                        ? {
                                            ...item,
                                            type: next,
                                            sub_type: isQbo
                                              ? defaultQboAccountType(next)
                                              : defaultXeroSubtype(next),
                                            dirty: true,
                                          }
                                        : item
                                    )
                                  );
                                }}
                                options={CHART_OF_ACCOUNT_TYPES.map((type) => ({ value: type, label: type }))}
                                className="w-full min-w-[7rem]"
                              />
                            ) : (
                              <Badge variant="outline" className="text-[10px]">
                                {row.type}
                              </Badge>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            {canEdit && !locked ? (
                              <Select
                                value={
                                  isQbo
                                    ? normalizeQboAccountType(row.type, row.sub_type)
                                    : normalizeXeroSubtype(row.type, row.sub_type)
                                }
                                onValueChange={(sub_type) =>
                                  setPlatformRows((prev) =>
                                    prev.map((item, i) =>
                                      i === index ? { ...item, sub_type, dirty: true } : item
                                    )
                                  )
                                }
                                options={
                                  isQbo ? qboAccountTypeOptions(row.type) : xeroSubtypeOptions(row.type)
                                }
                                className="w-full min-w-[8rem]"
                              />
                            ) : (
                              <Badge variant="outline" className="text-[10px]">
                                {row.sub_type}
                              </Badge>
                            )}
                          </td>
                          {canEdit ? (
                            <td className="px-2 py-2">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 cursor-pointer text-muted-foreground disabled:opacity-40"
                                disabled={
                                  row.staged ||
                                  row.can_pull === false ||
                                  pullXero.isPending ||
                                  pullQbo.isPending
                                }
                                onClick={() => {
                                  const pull = isQbo ? pullQbo : pullXero;
                                  void pull.mutateAsync(row.xero_account_id).then(
                                    () => toast({ title: "Account pulled into local chart of accounts" }),
                                    (err: unknown) =>
                                      toast({
                                        title: err instanceof Error ? err.message : "Could not pull account",
                                        variant: "destructive",
                                      })
                                  );
                                }}
                                aria-label="Pull into local chart of accounts"
                                title={
                                  row.can_pull === false
                                    ? "Already in the local chart of accounts"
                                    : "Pull into local chart of accounts"
                                }
                              >
                                <ArrowDownToLine className="h-4 w-4" />
                              </Button>
                            </td>
                          ) : null}
                          {canEdit ? (
                            <td className="px-2 py-2">
                              {row.dirty ? (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 cursor-pointer"
                                  disabled={
                                    createXero.isPending ||
                                    updateXero.isPending ||
                                    createQbo.isPending ||
                                    updateQbo.isPending
                                  }
                                  onClick={() => void savePlatformRow(index)}
                                  aria-label={`Save to ${platformName}`}
                                  data-testid={`coa-xero-save-${index}`}
                                >
                                  <Save className="h-4 w-4" />
                                </Button>
                              ) : null}
                            </td>
                          ) : null}
                          {canEdit ? (
                            <td className="px-2 py-2 text-right">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-muted-foreground hover:text-destructive"
                                disabled={
                                  (!row.staged && row.can_delete === false) ||
                                  deleteXero.isPending ||
                                  deleteQbo.isPending
                                }
                                onClick={() => {
                                  if (row.staged) {
                                    cancelStaged(index);
                                    return;
                                  }
                                  if (row.can_delete === false) {
                                    toast({ title: lockedMessage });
                                    return;
                                  }
                                  const remove = isQbo ? deleteQbo : deleteXero;
                                  void remove.mutateAsync(row.xero_account_id).then(
                                    () =>
                                      toast({
                                        title: `Account deleted in ${platformName} and moved to local`,
                                      }),
                                    (err: unknown) =>
                                      toast({
                                        title:
                                          err instanceof Error
                                            ? err.message
                                            : `Could not delete in ${platformName}`,
                                        variant: "destructive",
                                      })
                                  );
                                }}
                                aria-label="Delete account"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </td>
                          ) : null}
                        </tr>
                        {expanded
                          ? renderSubLedgers(
                              row,
                              (subs) =>
                                setPlatformRows((prev) =>
                                  prev.map((item, i) =>
                                    i === index ? { ...item, subLedgers: subs, dirty: true } : item
                                  )
                                ),
                              canEdit ? 8 : 5
                            )
                          : null}
                      </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
