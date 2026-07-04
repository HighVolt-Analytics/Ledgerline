import { useEffect, useMemo, useState } from "react";
import { Sparkles } from "lucide-react";

import type { InvoiceDetails, LineItem } from "@/api/types";
import { Select } from "@/components/ui/select";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { coaTypesForRouteTarget } from "@/lib/coaAccountOptions";
import {
  lineAccountReason,
  mergeGlAccountOptions,
  suggestLineAccount,
} from "@/lib/lineGlAccount";

type LineGlAccountCellProps = {
  inv: InvoiceDetails;
  line: LineItem;
  postingApplies: boolean;
};

export function LineGlAccountCell({ inv, line, postingApplies }: LineGlAccountCellProps) {
  const { options: coaOptions } = useCoaAccountOptions({
    types: coaTypesForRouteTarget(inv.route_target ?? ""),
    includeEmpty: false,
  });

  const defaultAccount = suggestLineAccount(inv, line, postingApplies);
  const [account, setAccount] = useState(defaultAccount);

  useEffect(() => {
    setAccount(suggestLineAccount(inv, line, postingApplies));
  }, [inv, line, postingApplies]);

  const selectOptions = useMemo(() => {
    const coaNames = coaOptions.map((option) => option.value).filter(Boolean);
    return mergeGlAccountOptions(defaultAccount, inv.account_name, coaNames).map((opt) => ({
      value: opt,
      label: opt,
    }));
  }, [coaOptions, defaultAccount, inv.account_name]);

  if (!postingApplies) {
    return (
      <span className="text-xs text-muted-foreground">Not posted — reference document</span>
    );
  }

  const reason = lineAccountReason(account, inv.vendor);

  return (
    <>
      <Select
        value={account}
        onValueChange={setAccount}
        className="invoice-drawer-gl-select w-full"
        options={selectOptions}
        data-testid="invoice-gl-select"
      />
      <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
        <Sparkles className="h-3 w-3 text-primary shrink-0" />
        <span className="truncate">
          AI: {account} · {reason}
        </span>
      </div>
    </>
  );
}
