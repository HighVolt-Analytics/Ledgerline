import { Check, CircleDashed, Lock, Minus, Shield, X } from "lucide-react";
import { SectionBlock } from "@/components/SectionBlock";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type { DossierApprovalChain, DossierApprovalStepState } from "@/lib/dossierApproval";
import { approvalStepStateLabel } from "@/lib/dossierApproval";
import { cn } from "@/lib/cn";

function stepIcon(state: DossierApprovalStepState) {
  if (state === "done") return <Check className="h-4 w-4 dossier-row__icon--ok shrink-0" />;
  if (state === "fail") return <X className="h-4 w-4 dossier-row__icon--bad shrink-0" />;
  if (state === "waived" || state === "not_required" || state === "skipped") {
    return <Minus className="h-4 w-4 dossier-row__icon--muted shrink-0" />;
  }
  if (state === "blocked") return <Lock className="h-4 w-4 dossier-row__icon--muted shrink-0" />;
  return <CircleDashed className="h-4 w-4 dossier-row__icon--pending shrink-0" />;
}

function stepTone(state: DossierApprovalStepState): string {
  if (state === "done") return pillTones.ok;
  if (state === "fail" || state === "blocked") return pillTones.bad;
  if (state === "pending") return pillTones.amber;
  return pillTones.muted;
}

export function DossierApprovalPanel({ chain }: { chain: DossierApprovalChain }) {
  return (
    <SectionBlock
      label="Approval chain"
      description="Playbook policy → DOA / exception queue → publish → payment (SoD enforced)."
    >
      <div className="dossier-panel">
        <div className="dossier-approval-policy">
          <Shield className="h-3.5 w-3.5 text-primary shrink-0" aria-hidden />
          <span className="dossier-approval-policy__label">Playbook policy</span>
          <StatusPill className={pillTones.muted}>{chain.policyLabel}</StatusPill>
        </div>

        <ol className="dossier-approval-chain">
          {chain.steps.map((step, index) => (
            <li
              key={step.id}
              className={cn(
                "dossier-approval-chain__item",
                (step.state === "blocked" || step.state === "fail") &&
                  "dossier-approval-chain__item--blocked",
                step.state === "pending" && "dossier-approval-chain__item--pending"
              )}
              data-testid={`approval-step-${step.id}`}
            >
              {index < chain.steps.length - 1 ? (
                <span className="dossier-approval-chain__connector" aria-hidden />
              ) : null}
              <span className="dossier-approval-chain__node">{stepIcon(step.state)}</span>
              <div className="dossier-approval-chain__body">
                <div className="dossier-approval-chain__head">
                  <span className="dossier-approval-chain__title">{step.label}</span>
                  <StatusPill className={stepTone(step.state)}>
                    {approvalStepStateLabel(step.state)}
                  </StatusPill>
                </div>
                <div className="dossier-approval-chain__meta">
                  <span className="dossier-approval-chain__role">{step.role}</span>
                  {step.actor !== "—" ? (
                    <>
                      <span className="dossier-approval-chain__sep">·</span>
                      <span className="dossier-approval-chain__actor">{step.actor}</span>
                    </>
                  ) : null}
                  {step.at ? (
                    <>
                      <span className="dossier-approval-chain__sep">·</span>
                      <span className="dossier-approval-chain__at tnum">{step.at}</span>
                    </>
                  ) : null}
                </div>
                {step.detail ? (
                  <p className="dossier-approval-chain__detail">{step.detail}</p>
                ) : null}
                {step.policyRef ? (
                  <span className="dossier-approval-chain__ref tnum">{step.policyRef}</span>
                ) : null}
                {step.sodNote ? (
                  <p className="dossier-approval-chain__sod">{step.sodNote}</p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </SectionBlock>
  );
}
