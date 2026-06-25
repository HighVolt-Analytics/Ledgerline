import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";
import {
  recognitionSignalCatalogFromApi,
  setRecognitionSignalCatalog,
  type RecognitionSignalCatalog,
} from "@/lib/recognitionSignalCatalog";

export function useRecognitionSignalCatalog(enabled = true) {
  const query = useQuery({
    queryKey: queryKeys.recognitionSignals(),
    queryFn: async (): Promise<RecognitionSignalCatalog> => {
      const raw = await api.getRecognitionSignalCatalog();
      const catalog = recognitionSignalCatalogFromApi(raw);
      setRecognitionSignalCatalog(catalog);
      return catalog;
    },
    enabled,
    staleTime: 60 * 60 * 1000,
  });

  useEffect(() => {
    if (query.data) {
      setRecognitionSignalCatalog(query.data);
    }
  }, [query.data]);

  return query;
}
