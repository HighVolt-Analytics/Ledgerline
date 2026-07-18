import { StatusPill, pillTones } from "@/components/StatusPill";
import { DocumentTypeChip } from "@/components/inbox/DocumentTypeChip";
import type { DossierOutcome } from "@/lib/dossiers";
import { dossierOutcomeLabel } from "@/lib/dossiers";
import { cn } from "@/lib/cn";

const POSTING_TONE: Record<DossierOutcome, string> = {
  auto_posted: pillTones.ok,
  manual_posted:
    "border-primary/20 bg-primary/10 text-primary",
  blocked: pillTones.bad,
  parked: pillTones.amber,
  vaulted: pillTones.ok,
  in_progress: pillTones.muted,
};

export function DossierOutcomeBadge({
  outcome,
  className,
}: {
  outcome: DossierOutcome;
  className?: string;
}) {
  return (
    <StatusPill className={cn(POSTING_TONE[outcome], className)}>
      {dossierOutcomeLabel(outcome)}
    </StatusPill>
  );
}

export function DossierTypeBadge({
  code,
  title,
  className,
}: {
  code: string;
  title?: string;
  className?: string;
}) {
  const label = (title || "").trim() || undefined;
  return (
    <DocumentTypeChip
      code={code}
      label={label}
      display={label}
      title={label}
      className={className}
    />
  );
}
