import { useState } from "react";

import { EmailIngestionRulesEditor } from "@/components/upload/EmailIngestionRulesEditor";

import { MailboxIngestionRecentSkips } from "@/components/upload/MailboxIngestionRecentSkips";

import {

  filterRulesForMailbox,

  mergeMailboxIngestionRules,

} from "@/lib/emailIngestionRules";

import { earlierRulesFromOtherMailboxes } from "@/lib/emailIngestionRulesPriority";

import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";

import { ChevronDown, ChevronRight } from "lucide-react";

import { cn } from "@/lib/cn";



type MailboxIngestionRulesPanelProps = {

  mailboxEmail: string;

  connectedMailboxEmails: string[];

  rules: EmailCaptureRule[];

  onChange: (rules: EmailCaptureRule[]) => void;

  ruleWarnings?: Record<string, string[]>;

  canEdit?: boolean;

  loading?: boolean;

  compact?: boolean;

};



export function MailboxIngestionRulesPanel({

  mailboxEmail,

  connectedMailboxEmails,

  rules,

  onChange,

  ruleWarnings = {},

  canEdit = true,

  loading = false,

  compact = true,

}: MailboxIngestionRulesPanelProps) {

  const visibleRules = filterRulesForMailbox(rules, mailboxEmail);

  const earlierExternal = earlierRulesFromOtherMailboxes(
    rules,
    mailboxEmail,
    visibleRules,
    connectedMailboxEmails
  );

  const [earlierOpen, setEarlierOpen] = useState(false);



  if (loading && rules.length === 0) {

    return (

      <p className="text-sm text-muted-foreground" data-testid="mailbox-ingestion-loading">

        Loading ingestion rules…

      </p>

    );

  }



  return (

    <div

      className={cn("space-y-2", canEdit ? undefined : "pointer-events-none opacity-90")}

      data-testid={`mailbox-ingestion-panel-${mailboxEmail}`}

    >

      {earlierExternal.length > 0 ? (

        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2.5 py-2">

          <button

            type="button"

            className="flex w-full items-center gap-2 text-left text-xs text-amber-900 dark:text-amber-100"

            onClick={() => setEarlierOpen((value) => !value)}

            data-testid={`earlier-rules-toggle-${mailboxEmail}`}

          >

            {earlierOpen ? (

              <ChevronDown className="h-3.5 w-3.5 shrink-0" />

            ) : (

              <ChevronRight className="h-3.5 w-3.5 shrink-0" />

            )}

            {earlierExternal.length} other rule(s) from different mailboxes run before these

          </button>

          {earlierOpen ? (

            <ul className="mt-2 space-y-1 pl-5 text-[11px] text-muted-foreground">

              {earlierExternal.map((rule) => (

                <li key={rule.id}>

                  <span className="font-medium text-foreground">{rule.name}</span>

                  {" · "}

                  <span className="font-mono">{rule.mailbox}</span>

                  {" · priority "}

                  {rule.priority}

                </li>

              ))}

            </ul>

          ) : null}

        </div>

      ) : null}



      <EmailIngestionRulesEditor

        compact={compact}

        mailboxScope={mailboxEmail}

        connectedMailboxEmails={connectedMailboxEmails}

        allRules={rules}

        rules={visibleRules}

        ruleWarnings={ruleWarnings}

        onChange={(nextVisible) =>

          onChange(mergeMailboxIngestionRules(rules, mailboxEmail, nextVisible))

        }

      />



      <MailboxIngestionRecentSkips mailboxEmail={mailboxEmail} compact={compact} />

    </div>

  );

}

