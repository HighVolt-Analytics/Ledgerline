import { useMemo } from "react";

import type { ChartOfAccountType } from "@/api/types";
import {
  coaAccountsToSelectOptions,
  excludeCoaAccountNames,
  filterCoaAccountsByTypes,
  filterCoaAccountsForLedgerPurpose,
  filterCoaAccountsForPostingRole,
  type CoaLedgerPurpose,
  type CoaPostingRole,
  type CoaSelectOption,
} from "@/lib/coaAccountOptions";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";

type UseCoaAccountOptionsArgs = {
  types?: ChartOfAccountType[];
  postingRole?: CoaPostingRole;
  ledgerPurpose?: CoaLedgerPurpose;
  excludeNames?: string[];
  includeEmpty?: boolean;
  emptyLabel?: string;
  enabled?: boolean;
};

export function useCoaAccountOptions({
  types,
  postingRole,
  ledgerPurpose,
  excludeNames = [],
  includeEmpty = true,
  emptyLabel = "— Select account —",
  enabled = true,
}: UseCoaAccountOptionsArgs = {}) {
  const { data: accounts = [], isLoading, isError } = useChartOfAccounts(enabled);

  const filtered = useMemo(() => {
    if (ledgerPurpose) {
      let rows = filterCoaAccountsForLedgerPurpose(accounts, ledgerPurpose);
      rows = excludeCoaAccountNames(rows, excludeNames);
      return rows;
    }
    let rows = filterCoaAccountsByTypes(accounts, types);
    rows = filterCoaAccountsForPostingRole(rows, postingRole);
    rows = excludeCoaAccountNames(rows, excludeNames);
    return rows;
  }, [accounts, excludeNames, ledgerPurpose, postingRole, types]);

  const options: CoaSelectOption[] = useMemo(
    () => coaAccountsToSelectOptions(filtered, { includeEmpty, emptyLabel }),
    [filtered, includeEmpty, emptyLabel]
  );

  const hasRealAccounts = filtered.length > 0;

  return { accounts: filtered, allAccounts: accounts, options, hasRealAccounts, isLoading, isError };
}
