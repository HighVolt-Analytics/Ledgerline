import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useToast } from "@/context/ToastContext";
import { useAuth } from "@/context/AuthContext";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";
import {
  emailCaptureRulesToApi,
  emailIngestionRulesLoadFromApi,
} from "@/lib/emailIngestionRulesApi";
import { validateEmailCaptureRulesWarningsById } from "@/lib/emailIngestionRuleValidation";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";

const SAVE_DEBOUNCE_MS = 800;

function useEmailIngestionStats(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.emailIngestionStats(),
    queryFn: async () => {
      const raw = await api.getEmailIngestionStats();
      return raw.ingest_stats ?? {};
    },
    enabled,
  });
}

export function useEmailIngestionRulesDraft(enabled = true) {
  const { user } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [rules, setRules] = useState<EmailCaptureRule[]>([]);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saved" | "error">("idle");
  const hydratedRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<EmailCaptureRule[] | null>(null);
  const saveGenerationRef = useRef(0);
  const saveInFlightRef = useRef(false);
  const executeSaveRef = useRef<() => void>(() => {});

  const tenantId = user?.tenant_id ?? null;
  const canEdit = user?.role === "admin";

  const {
    data: loaded,
    isLoading,
    isError,
    blocked,
    refetch,
  } = useTenantQuery({
    queryKey: queryKeys.emailIngestionRules(),
    queryFn: async () => emailIngestionRulesLoadFromApi(await api.getEmailIngestionRules()),
    enabled: Boolean(user) && enabled,
  });

  const { data: ingestStats } = useEmailIngestionStats(enabled);

  const saveMutation = useMutation({
    mutationFn: async (nextRules: EmailCaptureRule[]) => {
      const saved = await api.putEmailIngestionRules(emailCaptureRulesToApi(nextRules));
      return emailIngestionRulesLoadFromApi(saved);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.emailIngestionRules(), saved);
    },
  });

  useEffect(() => {
    hydratedRef.current = false;
    setRules([]);
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    pendingSaveRef.current = null;
    setSaveState("idle");
  }, [tenantId]);

  useEffect(() => {
    if (!loaded || hydratedRef.current) return;
    setRules(loaded.rules);
    hydratedRef.current = true;
  }, [loaded, tenantId]);

  useEffect(() => {
    if (blocked && !isLoading && enabled) {
      void refetch();
    }
  }, [blocked, enabled, isLoading, refetch]);

  const rulesWithStats = ingestStats
    ? rules.map((rule) => {
        const row = ingestStats[rule.id];
        if (!row) return rule;
        return {
          ...rule,
          matchedCount: row.matched_count,
          lastMatched: row.last_matched,
        };
      })
    : rules;

  const ruleWarnings = useMemo(
    () => validateEmailCaptureRulesWarningsById(rulesWithStats),
    [rulesWithStats]
  );

  const runSave = () => {
    const payload = pendingSaveRef.current;
    if (!payload || saveInFlightRef.current) return;
    const generation = saveGenerationRef.current;
    saveInFlightRef.current = true;
    saveMutation.mutate(payload, {
      onSuccess: (saved) => {
        if (generation !== saveGenerationRef.current) return;
        setRules(saved.rules);
        if (saved.warnings?.length) {
          toast({
            title: "Ingestion rules saved with warnings",
            description: saved.warnings.join(" "),
          });
        }
        setSaveState("saved");
      },
      onError: (err) => {
        setSaveState("error");
        toast({
          title: "Could not save ingestion rules",
          description: err instanceof Error ? err.message : "Save failed",
          variant: "destructive",
        });
      },
      onSettled: () => {
        saveInFlightRef.current = false;
        if (saveGenerationRef.current > generation) {
          runSave();
        }
      },
    });
  };

  executeSaveRef.current = runSave;

  const flushSave = (next: EmailCaptureRule[]) => {
    pendingSaveRef.current = next;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setSaveState("pending");
    saveGenerationRef.current += 1;
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null;
      runSave();
    }, SAVE_DEBOUNCE_MS);
  };

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      if (pendingSaveRef.current) {
        executeSaveRef.current();
      }
    };
  }, []);

  const onChange = (nextRules: EmailCaptureRule[]) => {
    if (!canEdit) return;
    setRules(nextRules);
    flushSave(nextRules);
  };

  return {
    rules: rulesWithStats,
    ruleWarnings,
    isLoading,
    isError,
    blocked,
    canEdit,
    onChange,
    isSaving: saveState === "pending" || saveMutation.isPending,
  };
}
