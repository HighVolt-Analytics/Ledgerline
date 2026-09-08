import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Landmark, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import type { BankAccount, PendingBankAccount } from "@/api/types";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Select } from "@/components/ui/select";
import {
  useBankAccounts,
  useBankFeedMutations,
  usePendingBankAccounts,
} from "@/hooks/useBankFeeds";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { useInstitutionSettings } from "@/hooks/useInstitutionSettings";
import { useSetupCatalogs } from "@/hooks/useSetupCatalogs";
import { useToast } from "@/context/ToastContext";
import { ApiError } from "@/api/client";
import { normalizeCurrencyCode } from "@/lib/format";

const BANK_SECTIONS = [
  { value: "pending", label: "Pending", testid: "tab-banks-pending" },
  { value: "list", label: "Bank list", testid: "tab-banks-list" },
] as const;

type BankSection = (typeof BANK_SECTIONS)[number]["value"];

type AccountFormState = {
  name: string;
  accountNumber: string;
  currency: string;
  ledger: string;
};

const emptyForm = (currency = ""): AccountFormState => ({
  name: "",
  accountNumber: "",
  currency,
  ledger: "",
});

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ExtractedChip({
  label,
  value,
  missing,
}: {
  label: string;
  value: string | null | undefined;
  missing?: boolean;
}) {
  const empty = missing || !value?.trim();
  return (
    <span
      className={
        empty
          ? "inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-800 dark:text-amber-200"
          : "inline-flex items-center gap-1 rounded border border-border bg-background/80 px-2 py-0.5 text-[11px] text-muted-foreground"
      }
    >
      <span className="font-medium">{label}</span>
      <span className="tnum">{empty ? "not found — enter below" : value}</span>
    </span>
  );
}

export function BanksTab({ canEdit = true }: { canEdit?: boolean }) {
  const { toast } = useToast();
  const [searchParams] = useSearchParams();
  const sectionFromUrl = searchParams.get("banksSection");
  const [section, setSection] = useState<BankSection>(() =>
    sectionFromUrl === "list" ? "list" : "pending"
  );

  const accountsQ = useBankAccounts(true);
  const pendingQ = usePendingBankAccounts(true);
  const mutations = useBankFeedMutations();
  const accounts = accountsQ.data ?? [];
  const pending = pendingQ.data ?? [];
  const { currencies } = useSetupCatalogs();
  const institutionQ = useInstitutionSettings(true);
  const booksCurrency =
    normalizeCurrencyCode(institutionQ.data?.currency) ||
    normalizeCurrencyCode(accounts[0]?.currency) ||
    normalizeCurrencyCode(currencies[0]?.code) ||
    "";

  const { options: ledgerOptions, hasRealAccounts: hasCoaLedgers } = useCoaAccountOptions({
    types: ["Asset"],
    includeEmpty: true,
    emptyLabel: "— Select ledger —",
  });
  const currencyOptions = useMemo(() => {
    const opts = currencies.map((c) => ({
      value: c.code,
      label: `${c.code} — ${c.name}`,
    }));
    if (!opts.some((o) => o.value === "")) {
      opts.unshift({ value: "", label: "— Select currency —" });
    }
    return opts;
  }, [currencies]);

  const [registering, setRegistering] = useState<PendingBankAccount | null>(null);
  const [regName, setRegName] = useState("");
  const [regNumber, setRegNumber] = useState("");
  const [regCurrency, setRegCurrency] = useState("");
  const [regLedger, setRegLedger] = useState("");
  const [linkAccountByPendingId, setLinkAccountByPendingId] = useState<Record<number, string>>(
    {}
  );
  const [autoOpenedPendingId, setAutoOpenedPendingId] = useState<number | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<BankAccount | null>(null);
  const [form, setForm] = useState<AccountFormState>(emptyForm);
  const [deleteTarget, setDeleteTarget] = useState<BankAccount | null>(null);

  const busy =
    mutations.promotePendingAccount.isPending ||
    mutations.dismissPendingAccount.isPending ||
    mutations.createAccount.isPending ||
    mutations.updateAccount.isPending ||
    mutations.deleteAccount.isPending;

  const openRegistration = (item: PendingBankAccount) => {
    setRegistering(item);
    setRegName(item.detected_name || item.filename?.replace(/\.[^.]+$/, "") || "");
    setRegNumber(item.detected_account_number || "");
    setRegCurrency(
      normalizeCurrencyCode(item.detected_currency) || booksCurrency
    );
    setRegLedger("");
  };

  useEffect(() => {
    if (!canEdit || section !== "pending" || pending.length === 0) return;
    if (registering) return;
    const first = pending[0];
    if (!first || autoOpenedPendingId === first.id) return;
    openRegistration(first);
    setAutoOpenedPendingId(first.id);
  }, [canEdit, section, pending, registering, autoOpenedPendingId]);

  const fail = (err: unknown) => {
    const msg =
      err instanceof ApiError
        ? err.message
        : err instanceof Error
          ? err.message
          : "Request failed";
    toast({ title: msg, variant: "destructive" });
  };

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm(booksCurrency));
    setFormOpen(true);
    setSection("list");
  };

  const openEdit = (account: BankAccount) => {
    setEditing(account);
    setForm({
      name: account.name,
      accountNumber: account.account_number || "",
      currency: normalizeCurrencyCode(account.currency) || booksCurrency,
      ledger: account.coa_account_name || "",
    });
    setFormOpen(true);
    setSection("list");
  };

  const closeForm = () => {
    setFormOpen(false);
    setEditing(null);
    setForm(emptyForm());
  };

  const onSaveAccount = async () => {
    const name = form.name.trim();
    const accountNumber = form.accountNumber.trim();
    const ledger = form.ledger.trim();
    if (!name) {
      toast({ title: "Account name is required", variant: "destructive" });
      return;
    }
    if (!accountNumber) {
      toast({ title: "Account number is required", variant: "destructive" });
      return;
    }
    if (!ledger) {
      toast({ title: "Ledger is required", variant: "destructive" });
      return;
    }
    if (!form.currency.trim()) {
      toast({ title: "Currency is required", variant: "destructive" });
      return;
    }
    try {
      if (editing) {
        await mutations.updateAccount.mutateAsync({
          accountId: editing.id,
          body: {
            name,
            currency: form.currency,
            account_number: accountNumber,
            coa_account_name: ledger,
          },
        });
        toast({ title: `Updated “${name}”` });
      } else {
        await mutations.createAccount.mutateAsync({
          name,
          currency: form.currency,
          account_number: accountNumber,
          coa_account_name: ledger,
        });
        toast({ title: `Created “${name}”` });
      }
      closeForm();
    } catch (err) {
      fail(err);
    }
  };

  const onConfirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await mutations.deleteAccount.mutateAsync(deleteTarget.id);
      toast({ title: `Removed “${deleteTarget.name}”` });
      if (editing?.id === deleteTarget.id) closeForm();
      setDeleteTarget(null);
    } catch (err) {
      fail(err);
    }
  };

  const onPromote = async (opts?: { bankAccountId?: number }) => {
    if (!registering) return;
    const name = regName.trim();
    const accountNumber = regNumber.trim();
    const ledger = regLedger.trim();
    if (!opts?.bankAccountId) {
      if (!name) {
        toast({ title: "Account name is required", variant: "destructive" });
        return;
      }
      if (!accountNumber) {
        toast({ title: "Account number is required", variant: "destructive" });
        return;
      }
      if (!ledger) {
        toast({ title: "Ledger is required", variant: "destructive" });
        return;
      }
      if (!regCurrency.trim()) {
        toast({ title: "Currency is required", variant: "destructive" });
        return;
      }
    }
    try {
      const result = await mutations.promotePendingAccount.mutateAsync({
        pendingId: registering.id,
        body: {
          name: name || registering.detected_name || "Bank account",
          account_number: accountNumber || registering.detected_account_number || "0000",
          currency: regCurrency,
          coa_account_name:
            ledger ||
            accounts.find((a) => a.id === opts?.bankAccountId)?.coa_account_name ||
            "Bank Account",
          bank_account_id: opts?.bankAccountId ?? null,
        },
      });
      setRegistering(null);
      setSection("list");
      const accepted = result.import_result?.accepted_count;
      toast({
        title: `Accepted “${result.account.name}”`,
        description:
          accepted != null ? `${accepted} statement row(s) imported` : undefined,
      });
    } catch (err) {
      fail(err);
    }
  };

  const onLinkExisting = async (pendingId: number) => {
    const raw = linkAccountByPendingId[pendingId];
    const bankAccountId = raw ? Number(raw) : NaN;
    if (!Number.isFinite(bankAccountId)) {
      toast({ title: "Select an existing bank account", variant: "destructive" });
      return;
    }
    const account = accounts.find((a) => a.id === bankAccountId);
    if (!account) return;
    try {
      const result = await mutations.promotePendingAccount.mutateAsync({
        pendingId,
        body: {
          name: account.name,
          account_number: account.account_number || account.account_mask || "0000",
          currency: account.currency,
          coa_account_name: account.coa_account_name,
          bank_account_id: bankAccountId,
        },
      });
      if (registering?.id === pendingId) setRegistering(null);
      const accepted = result.import_result?.accepted_count;
      toast({
        title: `Linked to “${result.account.name}”`,
        description: accepted != null ? `${accepted} row(s) imported` : undefined,
      });
    } catch (err) {
      fail(err);
    }
  };

  const onDismiss = async (pendingId: number) => {
    try {
      await mutations.dismissPendingAccount.mutateAsync(pendingId);
      if (registering?.id === pendingId) setRegistering(null);
      toast({ title: "Dismissed pending bank statement" });
    } catch (err) {
      fail(err);
    }
  };

  const accountFormFields = (
    formState: AccountFormState,
    setFormState: (next: AccountFormState) => void,
    testPrefix: string
  ) => (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium text-muted-foreground">Account name</span>
        <input
          type="text"
          value={formState.name}
          onChange={(e) => setFormState({ ...formState, name: e.target.value })}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          placeholder="Operating account"
          data-testid={`${testPrefix}-name`}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium text-muted-foreground">Account number</span>
        <input
          type="text"
          value={formState.accountNumber}
          onChange={(e) => setFormState({ ...formState, accountNumber: e.target.value })}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
          placeholder="12345678"
          data-testid={`${testPrefix}-number`}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium text-muted-foreground">Currency</span>
        <Select
          value={formState.currency}
          onValueChange={(currency) => setFormState({ ...formState, currency })}
          options={currencyOptions}
          searchable
          size="sm"
          className="w-full"
          data-testid={`${testPrefix}-currency`}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium text-muted-foreground">Ledger</span>
        <Select
          value={formState.ledger}
          onValueChange={(ledger) => setFormState({ ...formState, ledger })}
          options={ledgerOptions}
          searchable
          size="sm"
          className="w-full"
          data-testid={`${testPrefix}-ledger`}
        />
        {!hasCoaLedgers ? (
          <span className="text-[11px] text-muted-foreground">
            No COA ledgers yet — add them in{" "}
            <Link to="/settings?tab=coa" className="underline">
              Settings → Chart of accounts
            </Link>
            .
          </span>
        ) : null}
      </label>
    </div>
  );

  return (
    <div className="space-y-4" data-testid="banks-tab">
      <PageTabs
        value={section}
        onChange={(v) => setSection(v as BankSection)}
        tabs={BANK_SECTIONS.map((t) => ({
          value: t.value,
          label: t.label,
          testid: t.testid,
        }))}
        data-testid="banks-sections"
      />

      <PageTabPanel value="pending" active={section} className="mt-0 space-y-4">
        <Card
          className="p-4 border-destructive/30 bg-destructive/5"
          data-testid="pending-bank-queue"
        >
          <div className="mb-3 flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-destructive" />
              <h3 className="text-sm font-semibold">Pending registration queue</h3>
            </div>
            <p className="text-xs text-muted-foreground pl-6">
              We extract account name, number, and currency from each statement. Verify the
              fields, pick a ledger, then accept to register the bank and import the statement.
            </p>
          </div>
          {pendingQ.isLoading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
            </p>
          ) : pending.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No bank statements pending registration. Upload without selecting an account in Bank
              Feeds, or capture a statement via email.
            </p>
          ) : (
            <div className="space-y-2">
              {pending.map((item) => (
                <div
                  key={item.id}
                  className="space-y-2 rounded-lg border border-border bg-transparent p-3"
                  data-testid={`pending-bank-${item.id}`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1.5">
                      <p className="text-sm font-medium truncate">
                        {item.filename || item.detected_name || `Pending #${item.id}`}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        <ExtractedChip label="Name" value={item.detected_name} />
                        <ExtractedChip
                          label="Account #"
                          value={item.detected_account_number}
                          missing={!item.detected_account_number}
                        />
                        <ExtractedChip
                          label="Currency"
                          value={item.detected_currency}
                          missing={!item.detected_currency}
                        />
                        {item.extracted_count ? (
                          <ExtractedChip label="Rows" value={String(item.extracted_count)} />
                        ) : null}
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        {formatWhen(item.created_at)}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {accounts.length > 0 ? (
                        <>
                          <Select
                            value={linkAccountByPendingId[item.id] || ""}
                            onValueChange={(v) =>
                              setLinkAccountByPendingId((prev) => ({ ...prev, [item.id]: v }))
                            }
                            options={[
                              { value: "", label: "Link to existing…" },
                              ...accounts.map((a) => ({
                                value: String(a.id),
                                label: `${a.name} (${a.currency})`,
                              })),
                            ]}
                            size="sm"
                            className="min-w-[10rem]"
                            data-testid={`pending-bank-link-select-${item.id}`}
                          />
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy || !linkAccountByPendingId[item.id]}
                            onClick={() => void onLinkExisting(item.id)}
                            data-testid={`pending-bank-link-${item.id}`}
                          >
                            Link
                          </Button>
                        </>
                      ) : null}
                      {canEdit ? (
                        <Button
                          size="sm"
                          disabled={busy}
                          variant={registering?.id === item.id ? "outline" : "default"}
                          onClick={() => openRegistration(item)}
                          data-testid={`pending-bank-register-${item.id}`}
                        >
                          Review & accept
                        </Button>
                      ) : null}
                      {canEdit ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => void onDismiss(item.id)}
                          data-testid={`pending-bank-dismiss-${item.id}`}
                        >
                          Dismiss
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {registering && canEdit ? (
          <Card className="space-y-3 p-4" data-testid="bank-reg-form">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold">Verify extracted bank details</h3>
              <p className="text-xs text-muted-foreground">
                From “{registering.filename || registering.detected_name || registering.id}”.
                Correct anything that looks wrong, choose the ledger, then accept to register and
                import.
              </p>
            </div>
            {accountFormFields(
              {
                name: regName,
                accountNumber: regNumber,
                currency: regCurrency,
                ledger: regLedger,
              },
              (next) => {
                setRegName(next.name);
                setRegNumber(next.accountNumber);
                setRegCurrency(next.currency);
                setRegLedger(next.ledger);
              },
              "bank-reg"
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={
                  busy ||
                  !regName.trim() ||
                  !regNumber.trim() ||
                  !regCurrency.trim() ||
                  !regLedger.trim()
                }
                onClick={() => void onPromote()}
                data-testid="bank-reg-submit"
              >
                {mutations.promotePendingAccount.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Accept & import statement"
                )}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => setRegistering(null)}
              >
                Cancel
              </Button>
            </div>
          </Card>
        ) : null}
      </PageTabPanel>

      <PageTabPanel value="list" active={section} className="mt-0 space-y-4">
        <Card className="overflow-hidden" data-testid="bank-account-list">
          <div className="flex items-center justify-between gap-2 border-b border-border p-3 flex-wrap">
            <h3 className="text-sm font-semibold">Bank accounts ({accounts.length})</h3>
            {canEdit ? (
              <Button
                size="sm"
                disabled={busy}
                onClick={openCreate}
                data-testid="button-add-bank-account"
              >
                <Plus className="h-4 w-4 mr-1" /> Add account
              </Button>
            ) : null}
          </div>

          {formOpen && canEdit ? (
            <div
              className="space-y-3 border-b border-border bg-muted/20 p-4"
              data-testid="bank-account-form"
            >
              <h4 className="text-sm font-medium">
                {editing ? `Edit “${editing.name}”` : "New bank account"}
              </h4>
              {accountFormFields(form, setForm, editing ? "bank-edit" : "bank-create")}
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={
                    busy ||
                    !form.name.trim() ||
                    !form.accountNumber.trim() ||
                    !form.currency.trim() ||
                    !form.ledger.trim()
                  }
                  onClick={() => void onSaveAccount()}
                  data-testid="bank-account-save"
                >
                  {mutations.createAccount.isPending || mutations.updateAccount.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : editing ? (
                    "Save changes"
                  ) : (
                    "Create account"
                  )}
                </Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={closeForm}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}

          {accountsQ.isLoading ? (
            <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading bank accounts…
            </div>
          ) : accounts.length === 0 ? (
            <div className="space-y-2 p-6 text-center text-sm text-muted-foreground">
              <Landmark className="mx-auto h-8 w-8 opacity-40" />
              <p>No registered bank accounts yet.</p>
              <p className="text-xs">
                {canEdit
                  ? "Use Add account above, or complete a pending registration."
                  : "Ask someone with edit access to register a bank account."}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/30 text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2 font-medium">Bank account</th>
                    <th className="px-4 py-2 font-medium">Account number</th>
                    <th className="px-4 py-2 font-medium">Currency</th>
                    <th className="px-4 py-2 font-medium">Ledger</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    {canEdit ? (
                      <th className="px-4 py-2 font-medium text-right">Actions</th>
                    ) : null}
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((a) => (
                    <tr key={a.id} className="border-b border-border/60 last:border-0">
                      <td className="px-4 py-2.5 font-medium">{a.name}</td>
                      <td className="px-4 py-2.5 tnum text-muted-foreground">
                        {a.account_number || a.account_mask || "—"}
                      </td>
                      <td className="px-4 py-2.5">{a.currency}</td>
                      <td className="px-4 py-2.5 text-muted-foreground">{a.coa_account_name}</td>
                      <td className="px-4 py-2.5 capitalize">{a.status}</td>
                      {canEdit ? (
                        <td className="px-4 py-2.5">
                          <div className="flex justify-end gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy}
                              onClick={() => openEdit(a)}
                              data-testid={`edit-bank-${a.id}`}
                            >
                              <Pencil className="h-3.5 w-3.5 mr-1" />
                              Edit
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="text-destructive"
                              disabled={busy}
                              onClick={() => setDeleteTarget(a)}
                              data-testid={`delete-bank-${a.id}`}
                            >
                              <Trash2 className="h-3.5 w-3.5 mr-1" />
                              Delete
                            </Button>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </PageTabPanel>

      <ConfirmDialog
        open={deleteTarget != null}
        title="Remove this bank account?"
        description={
          deleteTarget
            ? `“${deleteTarget.name}” will be archived and removed from active lists. Existing statement history is kept.`
            : undefined
        }
        confirmLabel="Remove account"
        destructive
        busy={mutations.deleteAccount.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void onConfirmDelete()}
      />
    </div>
  );
}
