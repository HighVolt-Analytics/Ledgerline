import { useEffect, useRef, useState } from "react";
import { useToast } from "@/context/ToastContext";
import { useAuth } from "@/context/AuthContext";
import {
  useDeleteRuleBookDocumentType,
  useRuleBookEditorConfig,
  useSaveRuleBookConfig,
} from "@/hooks/useRuleBookConfig";
import { removeDocumentTypeFromCatalog } from "@/lib/documentTypeLifecycle";
import {
  mergeDocumentTypePatch,
  shouldApplyRuleBookSaveResponse,
} from "@/lib/ruleBookSave";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

const SAVE_DEBOUNCE_MS = 800;

export function useRuleBookDraft(enabled = true) {
  const { user } = useAuth();
  const { toast } = useToast();
  const [ruleBook, setRuleBook] = useState<RuleBookConfigState | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saved" | "error">("idle");
  const hydratedRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<RuleBookConfigState | null>(null);
  const executeSaveRef = useRef<() => void>(() => {});
  const saveGenerationRef = useRef(0);
  const saveInFlightRef = useRef(false);

  const tenantId = user?.tenant_id ?? null;
  const {
    data,
    isLoading,
    isError,
    blocked,
    refetch,
  } = useRuleBookEditorConfig(Boolean(user) && enabled);
  const saveMutation = useSaveRuleBookConfig();
  const deleteDocumentTypeMutation = useDeleteRuleBookDocumentType();
  const canEdit = user?.role === "admin";

  const cancelPendingSave = () => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    pendingSaveRef.current = null;
  };

  useEffect(() => {
    hydratedRef.current = false;
    setRuleBook(null);
    cancelPendingSave();
    setSaveState("idle");
  }, [tenantId]);

  useEffect(() => {
    if (!data || hydratedRef.current) return;
    setRuleBook(data);
    hydratedRef.current = true;
  }, [data, tenantId]);

  useEffect(() => {
    if (!user) {
      hydratedRef.current = false;
      setRuleBook(null);
    }
  }, [user]);

  useEffect(() => {
    if (blocked && !isLoading && enabled) {
      void refetch();
    }
  }, [blocked, enabled, isLoading, refetch]);

  const runSave = () => {
    const payload = pendingSaveRef.current;
    if (!payload || saveInFlightRef.current) return;
    const generation = saveGenerationRef.current;
    saveInFlightRef.current = true;
    saveMutation.mutate(payload, {
      onSuccess: ({ config }) => {
        if (!shouldApplyRuleBookSaveResponse(generation, saveGenerationRef.current)) {
          return;
        }
        setRuleBook(config);
        setSaveState("saved");
      },
      onError: (err) => {
        setSaveState("error");
        toast({
          title: "Could not save rule book",
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

  const flushSave = (next: RuleBookConfigState, options?: { immediate?: boolean }) => {
    pendingSaveRef.current = next;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setSaveState("pending");
    saveGenerationRef.current += 1;
    if (options?.immediate) {
      runSave();
      return;
    }
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

  const patch = (next: Partial<RuleBookConfigState>, options?: { immediate?: boolean }) => {
    if (!canEdit) return;
    setRuleBook((prev) => {
      if (!prev) return prev;
      const merged = { ...prev, ...next };
      flushSave(merged, options);
      return merged;
    });
  };

  const patchDocumentType = (
    code: string,
    partial: Partial<DocumentTypeDefinition>,
    options?: { immediate?: boolean }
  ) => {
    if (!canEdit) return;
    setRuleBook((prev) => {
      if (!prev) return prev;
      const documentTypes = mergeDocumentTypePatch(prev.documentTypes, code, partial);
      const merged = { ...prev, documentTypes };
      flushSave(merged, options);
      return merged;
    });
  };

  const deleteDocumentType = (code: string) => {
    if (!canEdit) return;
    cancelPendingSave();
    setRuleBook((prev) => (prev ? removeDocumentTypeFromCatalog(prev, code) : prev));
    deleteDocumentTypeMutation.mutate(code, {
      onSuccess: (config) => {
        setRuleBook(config);
        setSaveState("saved");
        toast({ title: "Document type deleted" });
      },
      onError: (err) => {
        if (data) setRuleBook(data);
        setSaveState("error");
        toast({
          title: "Could not delete document type",
          description: err instanceof Error ? err.message : "Delete failed",
          variant: "destructive",
        });
      },
    });
  };

  const saveLabel =
    saveState === "pending" ||
    saveMutation.isPending ||
    deleteDocumentTypeMutation.isPending
      ? "Saving…"
      : saveState === "saved"
        ? "Saved"
        : saveState === "error"
          ? "Save failed"
          : null;

  const isSaving =
    saveState === "pending" ||
    saveMutation.isPending ||
    deleteDocumentTypeMutation.isPending;

  return {
    ruleBook,
    isLoading,
    isError,
    blocked,
    canEdit,
    saveLabel,
    isSaving,
    patch,
    patchDocumentType,
    deleteDocumentType,
  };
}
