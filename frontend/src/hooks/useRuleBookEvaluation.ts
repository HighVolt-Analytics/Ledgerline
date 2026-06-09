import { useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type { RuleBookEvaluateResult } from "@/api/types";
import { ruleBookConfigToApi } from "@/lib/ruleBookConfigApi";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";

const EVAL_DEBOUNCE_MS = 450;

export function useRuleBookEvaluation(ruleBook: RuleBookConfigState | null, enabled = true) {
  const [result, setResult] = useState<RuleBookEvaluateResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!enabled || !ruleBook) {
      setResult(null);
      setError(null);
      setIsLoading(false);
      return;
    }

    if (timerRef.current) clearTimeout(timerRef.current);
    setIsLoading(true);
    setError(null);

    timerRef.current = setTimeout(() => {
      const requestId = ++requestIdRef.current;
      api
        .evaluateRuleBook({ config: ruleBookConfigToApi(ruleBook) })
        .then((data) => {
          if (requestId !== requestIdRef.current) return;
          setResult(data);
          setIsLoading(false);
        })
        .catch((err) => {
          if (requestId !== requestIdRef.current) return;
          setError(err instanceof Error ? err.message : "Evaluation failed");
          setResult(null);
          setIsLoading(false);
        });
    }, EVAL_DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [enabled, ruleBook]);

  return { result, isLoading, error };
}
