/**
 * Xero mapping workspace: LedgerLink values ↔ synced Xero reference data.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import type {
  ChartOfAccountRow,
  Vendor,
  XeroAccountRow,
  XeroContactRow,
  XeroMappingRow,
  XeroTaxRateRow,
  XeroTrackingCategoryRow,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

type MapTab = "suppliers" | "gl_accounts" | "tax" | "tracking";

const TABS: { id: MapTab; label: string }[] = [
  { id: "suppliers", label: "Suppliers" },
  { id: "gl_accounts", label: "GL Accounts" },
  { id: "tax", label: "Tax" },
  { id: "tracking", label: "Tracking" },
];

type MappingType = "supplier" | "gl_account" | "tax_code" | "tracking";

type DraftValue = {
  external_id?: string | null;
  external_code?: string | null;
  external_name?: string | null;
  external_option_id?: string | null;
  source_label?: string | null;
};

type LeftRow = {
  source_key: string;
  label: string;
};

function norm(s: string | null | undefined): string {
  return (s || "").trim().toLowerCase();
}

function mappingKey(type: MappingType, sourceKey: string): string {
  return `${type}:${sourceKey}`;
}

function draftFromMapping(row: XeroMappingRow | undefined): DraftValue {
  if (!row) return {};
  return {
    external_id: row.external_id ?? null,
    external_code: row.external_code ?? null,
    external_name: row.external_name ?? null,
    external_option_id: row.external_option_id ?? null,
    source_label: row.source_label ?? null,
  };
}

function isMapped(type: MappingType, draft: DraftValue | undefined): boolean {
  if (!draft) return false;
  if (type === "supplier") return Boolean((draft.external_id || "").trim());
  if (type === "gl_account" || type === "tax_code") {
    return Boolean((draft.external_code || "").trim() || (draft.external_id || "").trim());
  }
  return Boolean((draft.external_option_id || "").trim());
}

function draftsEqual(a: DraftValue, b: DraftValue): boolean {
  return (
    (a.external_id || "") === (b.external_id || "") &&
    (a.external_code || "") === (b.external_code || "") &&
    (a.external_name || "") === (b.external_name || "") &&
    (a.external_option_id || "") === (b.external_option_id || "") &&
    (a.source_label || "") === (b.source_label || "")
  );
}

function buildTaxKeys(existing: XeroMappingRow[]): LeftRow[] {
  const keys = new Map<string, string>();
  keys.set("GST:10", "GST 10%");
  keys.set("GST", "GST (no rate)");
  for (const row of existing) {
    if (row.mapping_type !== "tax_code") continue;
    const key = (row.source_key || "").trim();
    if (!key) continue;
    keys.set(key, row.source_label || key);
  }
  return [...keys.entries()].map(([source_key, label]) => ({ source_key, label }));
}

export function XeroMappingWorkspace({
  enabled,
  onMappingsSaved,
}: {
  enabled: boolean;
  onMappingsSaved: () => void | Promise<void>;
}) {
  const [tab, setTab] = useState<MapTab>("suppliers");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [coa, setCoa] = useState<ChartOfAccountRow[]>([]);
  const [contacts, setContacts] = useState<XeroContactRow[]>([]);
  const [accounts, setAccounts] = useState<XeroAccountRow[]>([]);
  const [taxRates, setTaxRates] = useState<XeroTaxRateRow[]>([]);
  const [tracking, setTracking] = useState<XeroTrackingCategoryRow[]>([]);
  const [mappings, setMappings] = useState<XeroMappingRow[]>([]);
  const [drafts, setDrafts] = useState<Record<string, DraftValue>>({});
  const [extraCostCentres, setExtraCostCentres] = useState<string[]>([]);
  const [newCostCentre, setNewCostCentre] = useState("");

  useResetOnTenantChange(() => {
    setVendors([]);
    setCoa([]);
    setContacts([]);
    setAccounts([]);
    setTaxRates([]);
    setTracking([]);
    setMappings([]);
    setDrafts({});
    setExtraCostCentres([]);
    setError(null);
    setStatus(null);
  });

  const reload = useCallback(async () => {
    if (!enabled) return;
    const scope = captureTenantFetchScope();
    setLoading(true);
    try {
      const [vendorRows, coaPayload, contactRes, accountRes, taxRes, trackRes, mapRes] =
        await Promise.all([
          api.listVendors(),
          api.getChartOfAccounts(),
          api.getXeroReferenceContacts({ limit: 200 }),
          api.getXeroReferenceAccounts({ limit: 200 }),
          api.getXeroReferenceTaxRates({ limit: 200 }),
          api.getXeroReferenceTrackingCategories({ limit: 500 }),
          api.getXeroMappings(),
        ]);
      if (!isTenantFetchScopeCurrent(scope)) return;
      setVendors(vendorRows);
      setCoa(coaPayload.accounts || []);
      setContacts(contactRes.items);
      setAccounts(accountRes.items);
      setTaxRates(taxRes.items);
      setTracking(trackRes.items);
      setMappings(mapRes.items);

      const next: Record<string, DraftValue> = {};
      for (const row of mapRes.items) {
        next[mappingKey(row.mapping_type as MappingType, row.source_key)] = draftFromMapping(row);
      }
      setDrafts(next);
      setError(null);
    } catch (err) {
      if (!isTenantFetchScopeCurrent(scope)) return;
      setError(err instanceof Error ? err.message : "Failed to load mappings");
    } finally {
      if (isTenantFetchScopeCurrent(scope)) setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const mappingByKey = useMemo(() => {
    const map = new Map<string, XeroMappingRow>();
    for (const row of mappings) {
      map.set(mappingKey(row.mapping_type as MappingType, row.source_key), row);
    }
    return map;
  }, [mappings]);

  const supplierRows: LeftRow[] = useMemo(
    () =>
      vendors.map((v) => ({
        source_key: v.vendor_slug,
        label: v.vendor_name || v.vendor_slug,
      })),
    [vendors]
  );

  const glRows: LeftRow[] = useMemo(
    () =>
      coa.map((a) => ({
        source_key: a.code,
        label: `${a.code} — ${a.name}`,
      })),
    [coa]
  );

  const taxRows: LeftRow[] = useMemo(() => buildTaxKeys(mappings), [mappings]);

  const trackingRows: LeftRow[] = useMemo(() => {
    const keys = new Map<string, string>();
    for (const account of coa) {
      for (const sub of account.subLedgers || []) {
        const code = (sub.code || "").trim();
        if (code) keys.set(code, sub.name || code);
      }
    }
    for (const row of mappings) {
      if (row.mapping_type !== "tracking") continue;
      const key = (row.source_key || "").trim();
      if (key) keys.set(key, row.source_label || key);
    }
    for (const key of extraCostCentres) {
      if (key) keys.set(key, key);
    }
    return [...keys.entries()].map(([source_key, label]) => ({ source_key, label }));
  }, [coa, mappings, extraCostCentres]);

  const activeRows =
    tab === "suppliers"
      ? supplierRows
      : tab === "gl_accounts"
        ? glRows
        : tab === "tax"
          ? taxRows
          : trackingRows;

  const activeType: MappingType =
    tab === "suppliers"
      ? "supplier"
      : tab === "gl_accounts"
        ? "gl_account"
        : tab === "tax"
          ? "tax_code"
          : "tracking";

  function setDraft(type: MappingType, sourceKey: string, value: DraftValue) {
    setDrafts((prev) => ({
      ...prev,
      [mappingKey(type, sourceKey)]: value,
    }));
    setStatus(null);
  }

  function autoMapExact() {
    const next = { ...drafts };
    let applied = 0;

    if (tab === "suppliers") {
      const byName = new Map<string, XeroContactRow[]>();
      for (const c of contacts) {
        const key = norm(c.name);
        if (!key) continue;
        const list = byName.get(key) || [];
        list.push(c);
        byName.set(key, list);
      }
      for (const row of supplierRows) {
        const matches = byName.get(norm(row.label)) || [];
        if (matches.length !== 1) continue;
        const contact = matches[0];
        next[mappingKey("supplier", row.source_key)] = {
          external_id: contact.xero_contact_id,
          external_name: contact.name,
          source_label: row.label,
        };
        applied += 1;
      }
    } else if (tab === "gl_accounts") {
      const byCode = new Map<string, XeroAccountRow[]>();
      for (const a of accounts) {
        const code = (a.code || "").trim();
        if (!code) continue;
        const list = byCode.get(code) || [];
        list.push(a);
        byCode.set(code, list);
      }
      for (const row of glRows) {
        const matches = byCode.get(row.source_key.trim()) || [];
        if (matches.length !== 1) continue;
        const account = matches[0];
        next[mappingKey("gl_account", row.source_key)] = {
          external_code: account.code,
          external_id: account.xero_account_id,
          external_name: account.name,
          source_label: row.label,
        };
        applied += 1;
      }
    } else if (tab === "tax") {
      const byType = new Map<string, XeroTaxRateRow[]>();
      const byName = new Map<string, XeroTaxRateRow[]>();
      for (const t of taxRates) {
        const typeKey = norm(t.tax_type);
        if (typeKey) {
          const list = byType.get(typeKey) || [];
          list.push(t);
          byType.set(typeKey, list);
        }
        const nameKey = norm(t.name);
        if (nameKey) {
          const list = byName.get(nameKey) || [];
          list.push(t);
          byName.set(nameKey, list);
        }
      }
      for (const row of taxRows) {
        const typeMatches = byType.get(norm(row.source_key)) || [];
        const nameMatches = byName.get(norm(row.label)) || [];
        const matches = typeMatches.length === 1 ? typeMatches : nameMatches.length === 1 ? nameMatches : [];
        if (matches.length !== 1) continue;
        const tax = matches[0];
        next[mappingKey("tax_code", row.source_key)] = {
          external_code: tax.tax_type,
          external_id: tax.tax_type,
          external_name: tax.name,
          source_label: row.label,
        };
        applied += 1;
      }
    } else {
      const byOption = new Map<string, XeroTrackingCategoryRow[]>();
      for (const t of tracking) {
        const key = norm(t.option_name || t.code);
        if (!key) continue;
        const list = byOption.get(key) || [];
        list.push(t);
        byOption.set(key, list);
      }
      for (const row of trackingRows) {
        const matches = byOption.get(norm(row.source_key)) || byOption.get(norm(row.label)) || [];
        if (matches.length !== 1) continue;
        const opt = matches[0];
        next[mappingKey("tracking", row.source_key)] = {
          external_id: opt.external_id,
          external_option_id: opt.option_external_id,
          external_name: opt.name,
          source_label: row.label,
        };
        applied += 1;
      }
    }

    setDrafts(next);
    setStatus(applied > 0 ? `Auto-mapped ${applied} exact match${applied === 1 ? "" : "es"}` : "No exact matches found");
  }

  async function saveDirty() {
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const payload: Array<Partial<XeroMappingRow> & { mapping_type: string; source_key: string }> = [];
      const types: MappingType[] = ["supplier", "gl_account", "tax_code", "tracking"];
      const leftByType: Record<MappingType, LeftRow[]> = {
        supplier: supplierRows,
        gl_account: glRows,
        tax_code: taxRows,
        tracking: trackingRows,
      };

      for (const type of types) {
        for (const row of leftByType[type]) {
          const key = mappingKey(type, row.source_key);
          const draft = drafts[key];
          if (!draft || !isMapped(type, draft)) continue;
          const existing = mappingByKey.get(key);
          const baseline = draftFromMapping(existing);
          if (existing && draftsEqual(draft, baseline)) continue;
          payload.push({
            mapping_type: type,
            source_key: row.source_key,
            source_label: draft.source_label || row.label,
            external_id: draft.external_id || null,
            external_code: draft.external_code || null,
            external_name: draft.external_name || null,
            external_option_id: draft.external_option_id || null,
            is_active: true,
          });
        }
      }

      if (payload.length === 0) {
        setStatus("Nothing to save");
        return;
      }

      await api.putXeroMappings(payload);
      setStatus(`Saved ${payload.length} mapping${payload.length === 1 ? "" : "s"}`);
      await reload();
      await onMappingsSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save mappings");
    } finally {
      setSaving(false);
    }
  }

  function addCostCentre() {
    const value = newCostCentre.trim();
    if (!value) return;
    setExtraCostCentres((prev) => (prev.includes(value) ? prev : [...prev, value]));
    setNewCostCentre("");
  }

  if (!enabled) return null;

  const unmappedCount = activeRows.filter((row) => {
    const draft = drafts[mappingKey(activeType, row.source_key)];
    return !isMapped(activeType, draft);
  }).length;

  return (
    <div className="space-y-3 text-xs" data-testid="xero-mappings-panel">
      <div className="flex flex-wrap items-center gap-1">
        {TABS.map((item) => (
          <Button
            key={item.id}
            size="sm"
            variant={tab === item.id ? "default" : "outline"}
            className="h-7 text-xs"
            onClick={() => setTab(item.id)}
            data-testid={`mapping-tab-${item.id}`}
          >
            {item.label}
          </Button>
        ))}
        <div className="ml-auto flex flex-wrap gap-1">
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            disabled={loading || saving}
            onClick={() => autoMapExact()}
            data-testid="mapping-auto-map"
          >
            Auto-map exact
          </Button>
          <Button
            size="sm"
            className="h-7 text-xs"
            disabled={loading || saving}
            onClick={() => void saveDirty()}
            data-testid="mapping-save"
          >
            {saving ? "Saving…" : "Save mappings"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            disabled={loading || saving}
            onClick={() => void reload()}
          >
            {loading ? "Loading…" : "Reload"}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
        <span>
          {activeRows.length} LedgerLink value{activeRows.length === 1 ? "" : "s"}
        </span>
        {unmappedCount > 0 ? (
          <span data-testid="mapping-unmapped-count">
            <Badge variant="destructive">
              {unmappedCount} unmapped
            </Badge>
          </span>
        ) : (
          <Badge variant="secondary">All mapped</Badge>
        )}
      </div>

      {error && (
        <p className="text-destructive" data-testid="mapping-error">
          {error}
        </p>
      )}
      {status && !error && (
        <p className="text-muted-foreground" data-testid="mapping-status">
          {status}
        </p>
      )}

      {tab === "tracking" && (
        <div className="flex flex-wrap gap-2 items-center">
          <input
            className="border border-border rounded px-2 py-1 bg-background min-w-[12rem]"
            placeholder="Add cost centre"
            value={newCostCentre}
            onChange={(e) => setNewCostCentre(e.target.value)}
            data-testid="mapping-add-cost-centre"
          />
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={addCostCentre}>
            Add
          </Button>
        </div>
      )}

      <ul className="space-y-2 max-h-[28rem] overflow-auto" data-testid="mapping-rows">
        {activeRows.length === 0 && (
          <li className="text-muted-foreground border border-dashed border-border rounded px-3 py-4">
            No LedgerLink values available for this tab yet.
          </li>
        )}
        {activeRows.map((row) => {
          const key = mappingKey(activeType, row.source_key);
          const draft = drafts[key] || {};
          const mapped = isMapped(activeType, draft);
          return (
            <li
              key={key}
              className={`rounded border px-3 py-2 ${
                mapped ? "border-border" : "border-destructive/50 bg-destructive/5"
              }`}
              data-testid={`mapping-row-${activeType}-${row.source_key}`}
            >
              <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto] md:items-center">
                <div className="min-w-0">
                  <p className="font-medium truncate">{row.label}</p>
                  <p className="text-muted-foreground truncate">Key: {row.source_key}</p>
                </div>
                <div>
                  {tab === "suppliers" && (
                    <select
                      className="w-full border border-border rounded px-2 py-1.5 bg-background"
                      value={draft.external_id || ""}
                      onChange={(e) => {
                        const contact = contacts.find((c) => c.xero_contact_id === e.target.value);
                        setDraft("supplier", row.source_key, {
                          external_id: e.target.value || null,
                          external_name: contact?.name || null,
                          source_label: row.label,
                        });
                      }}
                      data-testid={`mapping-select-supplier-${row.source_key}`}
                    >
                      <option value="">Select Xero contact…</option>
                      {contacts.map((c) => (
                        <option key={c.xero_contact_id} value={c.xero_contact_id}>
                          {c.name || c.xero_contact_id}
                        </option>
                      ))}
                    </select>
                  )}
                  {tab === "gl_accounts" && (
                    <select
                      className="w-full border border-border rounded px-2 py-1.5 bg-background"
                      value={draft.external_code || ""}
                      onChange={(e) => {
                        const account = accounts.find((a) => (a.code || "") === e.target.value);
                        setDraft("gl_account", row.source_key, {
                          external_code: e.target.value || null,
                          external_id: account?.xero_account_id || null,
                          external_name: account?.name || null,
                          source_label: row.label,
                        });
                      }}
                      data-testid={`mapping-select-gl-${row.source_key}`}
                    >
                      <option value="">Select Xero account…</option>
                      {accounts
                        .filter((a) => a.code)
                        .map((a) => (
                          <option key={a.xero_account_id} value={a.code || ""}>
                            {a.code} — {a.name || a.xero_account_id}
                          </option>
                        ))}
                    </select>
                  )}
                  {tab === "tax" && (
                    <select
                      className="w-full border border-border rounded px-2 py-1.5 bg-background"
                      value={draft.external_code || ""}
                      onChange={(e) => {
                        const tax = taxRates.find((t) => t.tax_type === e.target.value);
                        setDraft("tax_code", row.source_key, {
                          external_code: e.target.value || null,
                          external_id: e.target.value || null,
                          external_name: tax?.name || null,
                          source_label: row.label,
                        });
                      }}
                      data-testid={`mapping-select-tax-${row.source_key}`}
                    >
                      <option value="">Select Xero tax type…</option>
                      {taxRates.map((t) => (
                        <option key={t.tax_type} value={t.tax_type}>
                          {t.tax_type}
                          {t.name ? ` — ${t.name}` : ""}
                        </option>
                      ))}
                    </select>
                  )}
                  {tab === "tracking" && (
                    <select
                      className="w-full border border-border rounded px-2 py-1.5 bg-background"
                      value={draft.external_option_id || ""}
                      onChange={(e) => {
                        const opt = tracking.find((t) => t.option_external_id === e.target.value);
                        setDraft("tracking", row.source_key, {
                          external_id: opt?.external_id || null,
                          external_option_id: e.target.value || null,
                          external_name: opt?.name || null,
                          source_label: row.label,
                        });
                      }}
                      data-testid={`mapping-select-tracking-${row.source_key}`}
                    >
                      <option value="">Select Xero tracking option…</option>
                      {tracking.map((t) => (
                        <option
                          key={`${t.external_id}:${t.option_external_id}`}
                          value={t.option_external_id || ""}
                        >
                          {t.name} / {t.option_name || t.code}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <div className="justify-self-start md:justify-self-end">
                  {mapped ? (
                    <Badge variant="secondary">Mapped</Badge>
                  ) : (
                    <span data-testid={`mapping-unmapped-${row.source_key}`}>
                      <Badge variant="destructive">Unmapped</Badge>
                    </span>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
