import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import type {
  MasterConfirmationEmployeeFields,
  MasterConfirmationPreview,
  MasterConfirmationSaveResult,
  MasterConfirmationVendorFields,
} from "@/api/types";
import { AuthCenteredCard } from "@/components/auth/AuthCenteredCard";

function isEmployeeFields(
  kind: string,
  _fields: MasterConfirmationPreview["fields"]
): _fields is MasterConfirmationEmployeeFields {
  return kind === "employee";
}

function isVendorFields(
  kind: string,
  _fields: MasterConfirmationPreview["fields"]
): _fields is MasterConfirmationVendorFields {
  return kind === "vendor";
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  readOnly = false,
}: {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  type?: string;
  readOnly?: boolean;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <input
        className="auth-input"
        type={type}
        value={value}
        readOnly={readOnly}
        onChange={onChange ? (e) => onChange(e.target.value) : undefined}
      />
    </label>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function EmployeeForm({
  fields,
  onChange,
}: {
  fields: MasterConfirmationEmployeeFields;
  onChange: (next: MasterConfirmationEmployeeFields) => void;
}) {
  const bank = fields.bank ?? {};
  const set = (key: keyof MasterConfirmationEmployeeFields, value: string) =>
    onChange({ ...fields, [key]: value });
  const setBank = (key: keyof NonNullable<MasterConfirmationEmployeeFields["bank"]>, value: string) =>
    onChange({ ...fields, bank: { ...bank, [key]: value } });

  return (
    <>
      <Section title="Identity">
        <Field label="Full name" value={fields.name ?? ""} onChange={(v) => set("name", v)} />
        <Field
          label="Email"
          type="email"
          value={fields.email ?? ""}
          onChange={(v) => set("email", v)}
        />
        <Field
          label="WhatsApp / Mobile 1"
          value={fields.whatsapp_number ?? ""}
          onChange={(v) => set("whatsapp_number", v)}
        />
        <Field
          label="WhatsApp / Mobile 2"
          value={fields.whatsapp_number_2 ?? ""}
          onChange={(v) => set("whatsapp_number_2", v)}
        />
        <Field
          label="Viber"
          value={fields.viber_number ?? ""}
          onChange={(v) => set("viber_number", v)}
        />
      </Section>
      <Section title="Organisation">
        <Field
          label="Date of joining"
          value={fields.date_of_joining ?? ""}
          onChange={(v) => set("date_of_joining", v)}
        />
        <Field
          label="Department"
          value={fields.department ?? ""}
          onChange={(v) => set("department", v)}
        />
        <Field label="Designation" value={fields.role ?? ""} onChange={(v) => set("role", v)} />
        <Field
          label="Location"
          value={fields.location ?? ""}
          onChange={(v) => set("location", v)}
        />
        <Field label="Division" value={fields.division ?? ""} onChange={(v) => set("division", v)} />
        <Field
          label="Supervisor 1"
          value={fields.supervisor_1 ?? ""}
          onChange={(v) => set("supervisor_1", v)}
        />
        <Field
          label="Supervisor 2"
          value={fields.supervisor_2 ?? ""}
          onChange={(v) => set("supervisor_2", v)}
        />
      </Section>
      <Section title="Bank details">
        <Field label="BSB" value={bank.bsb ?? ""} onChange={(v) => setBank("bsb", v)} />
        <Field
          label="Account number"
          value={bank.account_number ?? ""}
          onChange={(v) => setBank("account_number", v)}
        />
        <Field
          label="Account name"
          value={bank.account_name ?? ""}
          onChange={(v) => setBank("account_name", v)}
        />
        <Field
          label="Bank name"
          value={bank.bank_name ?? ""}
          onChange={(v) => setBank("bank_name", v)}
        />
      </Section>
    </>
  );
}

function VendorForm({
  fields,
  aliasesText,
  onChange,
  onAliasesChange,
}: {
  fields: MasterConfirmationVendorFields;
  aliasesText: string;
  onChange: (next: MasterConfirmationVendorFields) => void;
  onAliasesChange: (value: string) => void;
}) {
  const bank = fields.bank ?? {};
  const billing = fields.billing_address ?? {};
  const set = (key: keyof MasterConfirmationVendorFields, value: string) =>
    onChange({ ...fields, [key]: value });
  const setBank = (key: keyof NonNullable<MasterConfirmationVendorFields["bank"]>, value: string) =>
    onChange({ ...fields, bank: { ...bank, [key]: value } });
  const setBilling = (
    key: keyof NonNullable<MasterConfirmationVendorFields["billing_address"]>,
    value: string
  ) => onChange({ ...fields, billing_address: { ...billing, [key]: value } });

  return (
    <>
      <Section title="Identity">
        <Field label="Business name" value={fields.name ?? ""} onChange={(v) => set("name", v)} />
        <Field
          label="Contact email"
          type="email"
          value={fields.contact_email ?? ""}
          onChange={(v) => set("contact_email", v)}
        />
        <Field label="Aliases (comma-separated)" value={aliasesText} onChange={onAliasesChange} />
        <Field label="Business registration number" value={fields.abn ?? ""} onChange={(v) => set("abn", v)} />
        <Field
          label="Payment terms"
          value={fields.payment_terms ?? ""}
          onChange={(v) => set("payment_terms", v)}
        />
      </Section>
      <Section title="Billing address">
        <Field label="Street" value={billing.street ?? ""} onChange={(v) => setBilling("street", v)} />
        <Field label="Suburb" value={billing.suburb ?? ""} onChange={(v) => setBilling("suburb", v)} />
        <Field
          label="Postcode"
          value={billing.postcode ?? ""}
          onChange={(v) => setBilling("postcode", v)}
        />
        <Field label="Country" value={billing.country ?? ""} onChange={(v) => setBilling("country", v)} />
      </Section>
      <Section title="Bank details">
        <Field label="BSB" value={bank.bsb ?? ""} onChange={(v) => setBank("bsb", v)} />
        <Field
          label="Account number"
          value={bank.account_number ?? ""}
          onChange={(v) => setBank("account_number", v)}
        />
        <Field
          label="Account name"
          value={bank.account_name ?? ""}
          onChange={(v) => setBank("account_name", v)}
        />
        <Field
          label="Bank name"
          value={bank.bank_name ?? ""}
          onChange={(v) => setBank("bank_name", v)}
        />
      </Section>
    </>
  );
}

export function ConfirmMasterPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";

  const [preview, setPreview] = useState<MasterConfirmationPreview | null>(null);
  const [fields, setFields] = useState<MasterConfirmationPreview["fields"]>({});
  const [aliasesText, setAliasesText] = useState("");
  const [loading, setLoading] = useState(true);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<MasterConfirmationSaveResult | null>(null);

  useEffect(() => {
    if (!token) {
      setFatalError("This confirmation link is missing a token.");
      setLoading(false);
      return;
    }
    void api
      .previewMasterConfirmation(token)
      .then((data) => {
        setPreview(data);
        setFields(data.fields);
        if (isVendorFields(data.kind, data.fields)) {
          setAliasesText((data.fields.aliases ?? []).join(", "));
        }
        if (data.confirmed) {
          setFatalError("These details were already confirmed. You can close this page.");
        } else if (data.expired) {
          setFatalError("This confirmation link has expired. Ask your administrator to resend it.");
        }
      })
      .catch((err) =>
        setFatalError(err instanceof Error ? err.message : "Invalid or expired link")
      )
      .finally(() => setLoading(false));
  }, [token]);

  const save = async () => {
    if (!token || !preview) return;
    setBusy(true);
    setFormError(null);
    try {
      const payload = { ...fields };
      if (isVendorFields(preview.kind, payload)) {
        payload.aliases = aliasesText
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }
      const saved = await api.saveMasterConfirmation({ token, fields: payload });
      setResult(saved);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const kindLabel = preview?.kind === "employee" ? "employee" : "vendor";
  const canShowForm =
    !loading && preview && !result && !fatalError && !preview.expired && !preview.confirmed;

  return (
    <AuthCenteredCard
      title={
        result
          ? "Details confirmed"
          : fatalError
            ? "Confirmation link"
            : `Confirm your ${kindLabel} details`
      }
      subtitle={
        result
          ? `Thank you, ${result.party_name}. Your details are now ${result.status}.`
          : canShowForm
            ? `${preview.tenant_name} — review the information below, edit anything that is wrong, then save.`
            : undefined
      }
    >
      {loading && (
        <div className="auth-form" aria-busy="true" aria-label="Loading">
          <div className="auth-skeleton auth-skeleton-line w-52" />
          <div className="auth-skeleton auth-skeleton-input" />
          <div className="auth-skeleton auth-skeleton-input" />
          <div className="auth-skeleton auth-skeleton-button" />
        </div>
      )}

      {canShowForm && isEmployeeFields(preview.kind, fields) && (
        <div className="auth-form space-y-5">
          <EmployeeForm fields={fields} onChange={setFields} />
          {formError ? <p className="auth-error">{formError}</p> : null}
          <button type="button" className="auth-submit" disabled={busy} onClick={() => void save()}>
            {busy ? "Saving…" : "Save and confirm"}
          </button>
        </div>
      )}

      {canShowForm && isVendorFields(preview.kind, fields) && (
        <div className="auth-form space-y-5">
          <VendorForm
            fields={fields}
            aliasesText={aliasesText}
            onChange={setFields}
            onAliasesChange={setAliasesText}
          />
          {formError ? <p className="auth-error">{formError}</p> : null}
          <button type="button" className="auth-submit" disabled={busy} onClick={() => void save()}>
            {busy ? "Saving…" : "Save and confirm"}
          </button>
        </div>
      )}

      {fatalError ? <p className="auth-error">{fatalError}</p> : null}
    </AuthCenteredCard>
  );
}
