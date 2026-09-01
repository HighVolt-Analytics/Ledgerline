import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  Building2,
  CheckCircle2,
  CircleDashed,
  FileSpreadsheet,
  Landmark,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/context/ToastContext";
import { api } from "@/api/client";
import type { BankFileSettings } from "@/api/types";
import { cn } from "@/lib/cn";

const EMPTY_SETTINGS: BankFileSettings = {
  format: "",
  remitter: {
    bank_name: "",
    account_name: "",
    routing_code: "",
    account_number: "",
    remittance_display_name: "",
  },
  aba_user_id_number: "",
  aba_financial_institution_code: "",
  aba_description: "SUPPLIER PAY",
};

const FORMAT_OPTIONS = [
  {
    value: "",
    label: "Not configured",
    description: "Skip batch bank files for now",
    badge: "Off",
  },
  {
    value: "AU_ABA",
    label: "Australia — ABA",
    description: "Standard bulk payment file for AU banks",
    badge: "AU",
  },
] as const;

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  maxLength,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  maxLength?: number;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 bg-background/80"
      />
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  description,
  children,
  complete,
}: {
  icon: typeof Landmark;
  title: string;
  description: string;
  children: ReactNode;
  complete?: boolean;
}) {
  return (
    <section className="bank-file-settings-section">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5 min-w-0">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
            <Icon className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-semibold">{title}</h4>
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          </div>
        </div>
        {complete != null ? (
          <span
            className={cn(
              "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
              complete
                ? "border border-primary/20 bg-primary/10 text-primary"
                : "border border-border bg-muted/50 text-muted-foreground"
            )}
          >
            {complete ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <CircleDashed className="h-3 w-3" />
            )}
            {complete ? "Ready" : "Incomplete"}
          </span>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function remitterComplete(remitter: BankFileSettings["remitter"]): boolean {
  return Boolean(
    remitter.bank_name.trim() &&
      remitter.account_name.trim() &&
      remitter.routing_code.trim() &&
      remitter.account_number.trim()
  );
}

function abaComplete(settings: BankFileSettings): boolean {
  return Boolean(
    settings.aba_financial_institution_code.trim() &&
      settings.aba_user_id_number.trim() &&
      settings.aba_description.trim()
  );
}

/** Tenant's own remitting bank account + format used to generate batch payment
 * files (e.g. an AU ABA export) from Scheduled payments. Kept separate from
 * useRuleBookDraft since bank_file_settings isn't part of that draft payload. */
export function BankFileSettingsPanel({
  embedded = false,
  hideChrome = false,
  formId,
  onSaved,
  onSavingChange,
}: {
  embedded?: boolean;
  hideChrome?: boolean;
  formId?: string;
  onSaved?: () => void;
  onSavingChange?: (saving: boolean) => void;
} = {}) {
  const { toast } = useToast();
  const [settings, setSettings] = useState<BankFileSettings>(EMPTY_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    api
      .getRuleBookConfig({ fields: "bank_file_settings" })
      .then((data) => {
        if (cancelled) return;
        setSettings(data.bank_file_settings ?? EMPTY_SETTINGS);
        setLoadError(false);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const remitter = settings.remitter;
  const patchRemitter = (patch: Partial<BankFileSettings["remitter"]>) =>
    setSettings((prev) => ({ ...prev, remitter: { ...prev.remitter, ...patch } }));

  const handleSave = async (event?: FormEvent) => {
    event?.preventDefault();
    setIsSaving(true);
    onSavingChange?.(true);
    try {
      const saved = await api.putRuleBookBankFileSettings(settings);
      if (saved.bank_file_settings) setSettings(saved.bank_file_settings);
      toast({ title: "Bank file settings saved" });
      onSaved?.();
    } catch (err) {
      toast({
        title: "Couldn't save bank file settings",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setIsSaving(false);
      onSavingChange?.(false);
    }
  };

  const wrap = (content: ReactNode, className?: string) =>
    embedded ? (
      <div className={className} data-testid="bank-file-settings-panel">
        {content}
      </div>
    ) : (
      <Card className={`p-4 mb-0 ${className ?? ""}`.trim()} data-testid="bank-file-settings-panel">
        {content}
      </Card>
    );

  if (isLoading) {
    return wrap(
      <div className="flex min-h-[12rem] items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading bank file settings…
      </div>
    );
  }

  if (loadError) {
    return wrap(
      <p className="text-sm text-destructive">
        Could not load bank file settings. Try refreshing the page.
      </p>
    );
  }

  const isAba = settings.format === "AU_ABA";
  const formatReady = Boolean(settings.format);
  const accountReady = formatReady && remitterComplete(remitter);
  const exportReady = isAba ? accountReady && abaComplete(settings) : accountReady;

  const formContent = (
    <form
      id={formId}
      className="space-y-5"
      onSubmit={(event) => void handleSave(event)}
    >
      {!hideChrome ? (
        <>
          <h3 className="text-sm font-semibold mb-1">Bank file settings</h3>
          <p className="text-xs text-muted-foreground mb-4">
            Configure your own remitting bank account so Scheduled payments can be bundled into a
            batch payment file (e.g. an AU ABA file) and downloaded from the Payments page for
            upload to your bank. LedgerLink never moves money itself — this only builds the file.
          </p>
        </>
      ) : null}

      <div className={cn(embedded && "grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,0.85fr)]")}>
        <div className="space-y-5">
          <Section
            icon={FileSpreadsheet}
            title="Export format"
            description="Choose the batch payment file your bank accepts."
            complete={formatReady}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {FORMAT_OPTIONS.map((option) => {
                const selected = settings.format === option.value;
                return (
                  <button
                    key={option.value || "none"}
                    type="button"
                    data-selected={selected}
                    className="bank-file-settings-format-card"
                    onClick={() => setSettings((prev) => ({ ...prev, format: option.value }))}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{option.label}</span>
                      <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {option.badge}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">{option.description}</span>
                  </button>
                );
              })}
            </div>
          </Section>

          {settings.format ? (
            <>
              <Section
                icon={Building2}
                title="Remitting account"
                description="Your company bank account that funds the batch payment."
                complete={accountReady}
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field
                    id="remitter-bank-name"
                    label="Bank name"
                    value={remitter.bank_name}
                    onChange={(v) => patchRemitter({ bank_name: v })}
                    placeholder="Commonwealth Bank"
                  />
                  <Field
                    id="remitter-account-name"
                    label="Account name (legal name)"
                    value={remitter.account_name}
                    onChange={(v) => patchRemitter({ account_name: v })}
                    placeholder="Acme Pty Ltd"
                  />
                  <Field
                    id="remitter-display-name"
                    label="Name on recipients' statements"
                    value={remitter.remittance_display_name}
                    onChange={(v) => patchRemitter({ remittance_display_name: v })}
                    placeholder="ACME PTY LTD"
                    maxLength={16}
                    hint="Up to 16 characters shown on supplier bank statements."
                  />
                  <Field
                    id="remitter-routing-code"
                    label="BSB"
                    value={remitter.routing_code}
                    onChange={(v) => patchRemitter({ routing_code: v })}
                    placeholder="062-000"
                  />
                  <Field
                    id="remitter-account-number"
                    label="Account number"
                    value={remitter.account_number}
                    onChange={(v) => patchRemitter({ account_number: v })}
                    placeholder="12345678"
                  />
                </div>
              </Section>

              {isAba ? (
                <Section
                  icon={Landmark}
                  title="ABA file details"
                  description="Identifiers your bank issued for bulk lodgement."
                  complete={abaComplete(settings)}
                >
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field
                      id="aba-financial-institution-code"
                      label="Bank APCA code"
                      value={settings.aba_financial_institution_code}
                      onChange={(v) =>
                        setSettings((prev) => ({
                          ...prev,
                          aba_financial_institution_code: v.toUpperCase(),
                        }))
                      }
                      placeholder="CBA"
                      maxLength={3}
                      hint="e.g. CBA, WBC, ANZ, NAB"
                    />
                    <Field
                      id="aba-user-id-number"
                      label="APCA User ID Number"
                      value={settings.aba_user_id_number}
                      onChange={(v) => setSettings((prev) => ({ ...prev, aba_user_id_number: v }))}
                      placeholder="123456"
                      maxLength={6}
                      hint="Provided by your bank for ABA lodgement."
                    />
                    <Field
                      id="aba-description"
                      label="Description of entries"
                      value={settings.aba_description}
                      onChange={(v) => setSettings((prev) => ({ ...prev, aba_description: v }))}
                      placeholder="SUPPLIER PAY"
                      maxLength={12}
                    />
                  </div>
                </Section>
              ) : null}
            </>
          ) : null}
        </div>

        {embedded ? (
          <aside className="bank-file-settings-preview h-fit lg:sticky lg:top-0">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Export readiness
            </p>
            <div className="mt-3 space-y-2.5">
              {[
                { label: "Format selected", done: formatReady },
                { label: "Remitter account complete", done: accountReady },
                ...(isAba ? [{ label: "ABA identifiers complete", done: abaComplete(settings) }] : []),
              ].map((item) => (
                <div
                  key={item.label}
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs",
                    item.done
                      ? "border-primary/20 bg-primary/5 text-foreground"
                      : "border-border bg-background/70 text-muted-foreground"
                  )}
                >
                  {item.done ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-primary" />
                  ) : (
                    <CircleDashed className="h-3.5 w-3.5 shrink-0" />
                  )}
                  {item.label}
                </div>
              ))}
            </div>

            <div className="mt-4 rounded-lg border border-border/70 bg-background/80 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                What happens next
              </p>
              <ol className="mt-2 space-y-2 text-xs text-muted-foreground">
                <li>1. Save these settings once for your tenant.</li>
                <li>2. On Scheduled, select approved payments.</li>
                <li>3. Download the bank file and upload it to your bank.</li>
              </ol>
            </div>

            <div
              className={cn(
                "mt-4 rounded-lg border px-3 py-2.5 text-xs",
                exportReady
                  ? "border-primary/25 bg-primary/10 text-primary"
                  : "border-border bg-muted/30 text-muted-foreground"
              )}
            >
              {exportReady
                ? "Ready to generate batch bank files from Scheduled payments."
                : "Complete the sections on the left to unlock batch export."}
            </div>
          </aside>
        ) : null}
      </div>

      {!hideChrome ? (
        <div className="flex justify-end mt-5">
          <Button type="submit" disabled={isSaving} data-testid="bank-file-settings-save">
            {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : null}
            Save
          </Button>
        </div>
      ) : null}
    </form>
  );

  return wrap(formContent);
}
