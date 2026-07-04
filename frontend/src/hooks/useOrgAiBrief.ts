import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";

import type { OrgAiBrief } from "@/api/types";

import { useTenantQuery } from "@/hooks/useTenantQuery";

import { queryKeys } from "@/lib/queryClient";

import {

  emptyOrgContextConfig,

  type OrgContextConfig,

} from "@/lib/v4RuleBookTypes";



type OrgAiBriefWire = OrgAiBrief & {

  legalName?: string;

  default_perspective?: string;

  defaultPerspective?: string;

  intake_summary?: string;

  intakeSummary?: string;

  classification_hints?: string;

  classificationHints?: string;

};



function mapOrgAiBriefFromApi(raw: OrgAiBriefWire): OrgContextConfig {

  const perspective = String(

    raw.default_perspective ?? raw.defaultPerspective ?? "buyer"

  )

    .trim()

    .toLowerCase();

  return {

    legalName: (raw.legal_name ?? raw.legalName ?? "").trim(),

    abn: (raw.abn ?? "").trim(),

    aliases: [...(raw.aliases ?? [])],

    defaultPerspective:

      perspective === "seller" || perspective === "mixed" ? perspective : "buyer",

    intakeSummary: (raw.intake_summary ?? raw.intakeSummary ?? "").trim(),

    classificationHints: (raw.classification_hints ?? raw.classificationHints ?? "").trim(),

  };

}



function orgAiBriefToApi(org: OrgContextConfig): OrgAiBrief {

  return {

    legal_name: org.legalName.trim(),

    abn: org.abn.trim(),

    aliases: [...org.aliases],

    default_perspective: org.defaultPerspective,

    intake_summary: org.intakeSummary.trim(),

    classification_hints: org.classificationHints.trim(),

  };

}



export function hasOrgAiBriefContent(org: OrgContextConfig | undefined): boolean {

  if (!org) return false;

  return Boolean(

    org.legalName.trim() ||

      org.abn.trim() ||

      org.aliases.length ||

      org.intakeSummary.trim() ||

      org.classificationHints.trim()

  );

}



export function useOrgAiBrief(enabled = true) {

  return useTenantQuery({

    queryKey: queryKeys.orgAiBrief(),

    queryFn: async () => mapOrgAiBriefFromApi(await api.getOrgAiBrief()),

    enabled,

    staleTime: 0,

    refetchOnMount: "always",

  });

}



export function useSaveOrgAiBrief() {

  const queryClient = useQueryClient();

  return useMutation({

    mutationFn: async (org: OrgContextConfig) =>

      mapOrgAiBriefFromApi(await api.updateOrgAiBrief(orgAiBriefToApi(org))),

    onSuccess: async (org) => {

      queryClient.setQueryData(queryKeys.orgAiBrief(), org);

      await queryClient.refetchQueries({ queryKey: queryKeys.orgAiBrief() });

      void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookConfig() });

    },

  });

}



export function orgAiBriefWithTenantName(

  org: OrgContextConfig | undefined,

  tenantName: string

): OrgContextConfig {

  const base = org ?? emptyOrgContextConfig();

  return {

    ...base,

    legalName: base.legalName.trim() || tenantName.trim(),

  };

}


