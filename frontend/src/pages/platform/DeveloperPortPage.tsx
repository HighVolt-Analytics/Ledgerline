import { useCallback, useEffect, useMemo, useState } from "react";
import { Code2 } from "lucide-react";
import { api } from "@/api/client";
import type { PlatformPromptSummary, PlatformPromptVersionItem } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";

export function DeveloperPortPage() {
  const [prompts, setPrompts] = useState<PlatformPromptSummary[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [notes, setNotes] = useState("");
  const [versions, setVersions] = useState<PlatformPromptVersionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const selected = useMemo(
    () => prompts.find((p) => p.key === selectedKey) ?? null,
    [prompts, selectedKey]
  );

  const groups = useMemo(() => {
    const map = new Map<string, PlatformPromptSummary[]>();
    for (const prompt of prompts) {
      const list = map.get(prompt.group) ?? [];
      list.push(prompt);
      map.set(prompt.group, list);
    }
    return Array.from(map.entries());
  }, [prompts]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await api.getPlatformPrompts();
      setPrompts(items);
      setSelectedKey((prev) => prev ?? items[0]?.key ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load prompts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selected) return;
    setBody(selected.body);
    setNotes(selected.notes ?? "");
    setSaved(false);
    api
      .getPlatformPromptVersions(selected.key)
      .then((res) => setVersions(res.items))
      .catch(() => setVersions([]));
  }, [selected]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 2500);
    return () => clearTimeout(t);
  }, [saved]);

  async function save() {
    if (!selected) return;
    if (
      !window.confirm(
        "Save as a new version and activate it for all tenants immediately?"
      )
    ) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.createPlatformPromptVersion(selected.key, {
        body,
        notes: notes.trim() || undefined,
      });
      setPrompts((prev) => prev.map((p) => (p.key === updated.key ? updated : p)));
      const hist = await api.getPlatformPromptVersions(selected.key);
      setVersions(hist.items);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function activate(version: number) {
    if (!selected) return;
    if (
      !window.confirm(
        `Activate version ${version} for all tenants? Current active prompt will switch immediately.`
      )
    ) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.activatePlatformPromptVersion(selected.key, version);
      setPrompts((prev) => prev.map((p) => (p.key === updated.key ? updated : p)));
      setBody(updated.body);
      setNotes(updated.notes ?? "");
      const hist = await api.getPlatformPromptVersions(selected.key);
      setVersions(hist.items);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Activate failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading && prompts.length === 0) {
    return (
      <div>
        <PageHeader
          title="Developer Port"
          subtitle="Platform LLM system prompts with version history."
        />
        <PageLoader label="Loading prompts…" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Developer Port"
        subtitle="Edit global LLM system prompts. Each save creates a new version; activate any prior version to roll back."
      />

      <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-950 dark:text-amber-100">
        Changes apply to all tenants as soon as a version is saved or activated.
      </div>

      {error && <p className="mb-3 text-sm text-destructive">{error}</p>}
      {saved && (
        <p className="mb-3 text-sm text-[hsl(var(--chart-1))]">Prompt version updated.</p>
      )}

      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium">
            <Code2 className="h-4 w-4" />
            Prompts
          </div>
          <div className="max-h-[70vh] space-y-3 overflow-y-auto">
            {groups.map(([group, items]) => (
              <div key={group}>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {group}
                </div>
                <div className="space-y-1">
                  {items.map((prompt) => (
                    <button
                      key={prompt.key}
                      type="button"
                      className={cn(
                        "w-full rounded-md px-2 py-1.5 text-left text-sm hover-elevate",
                        selectedKey === prompt.key && "bg-muted font-medium"
                      )}
                      onClick={() => setSelectedKey(prompt.key)}
                    >
                      <div>{prompt.label}</div>
                      <div className="text-xs text-muted-foreground">
                        v{prompt.version ?? "—"}
                        {prompt.is_overridden ? " · edited" : " · seeded"}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <div className="space-y-4">
          {!selected ? (
            <Card className="p-4 text-sm text-muted-foreground">Select a prompt.</Card>
          ) : (
            <>
              <Card className="space-y-3 p-4">
                <div>
                  <h2 className="text-base font-semibold">{selected.label}</h2>
                  <p className="text-sm text-muted-foreground">{selected.description}</p>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">{selected.key}</p>
                </div>
                {selected.placeholders.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {selected.placeholders.map((ph) => (
                      <span
                        key={ph}
                        className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs"
                      >
                        {`{${ph}}`}
                      </span>
                    ))}
                  </div>
                )}
                <label className="block text-sm font-medium">
                  Active body
                  <textarea
                    className="mt-1 min-h-[320px] w-full rounded-md border bg-background p-3 font-mono text-xs"
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    spellCheck={false}
                  />
                </label>
                <label className="block text-sm font-medium">
                  Notes (optional)
                  <input
                    className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Why this change?"
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => void save()} disabled={saving || !body.trim()}>
                    {saving ? "Saving…" : "Save as new version"}
                  </Button>
                </div>
              </Card>

              <Card className="space-y-2 p-4">
                <h3 className="text-sm font-semibold">Version history</h3>
                <div className="max-h-64 space-y-2 overflow-y-auto">
                  {versions.map((v) => (
                    <div
                      key={v.version}
                      className="flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-sm"
                    >
                      <div>
                        <div className="font-medium">
                          v{v.version}
                          {v.is_active ? " · active" : ""}
                        </div>
                        {v.notes && (
                          <div className="text-xs text-muted-foreground">{v.notes}</div>
                        )}
                        {v.created_at && (
                          <div className="text-xs text-muted-foreground">
                            {new Date(v.created_at).toLocaleString()}
                          </div>
                        )}
                      </div>
                      {!v.is_active && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={saving}
                          onClick={() => void activate(v.version)}
                        >
                          Activate
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </Card>

              <details className="rounded-lg border p-4 text-sm">
                <summary className="cursor-pointer font-medium">Code default (seed source)</summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs">
                  {selected.default_body}
                </pre>
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
