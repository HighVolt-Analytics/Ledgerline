import { BookOpen, ChevronDown, FolderOpen, Mail, UserCircle, Users } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ROUTING_STEPS } from "@/lib/v4RuleBookTypes";

const STEP_ICONS = [Mail, Users, FolderOpen, UserCircle, BookOpen] as const;

export function RoutingDiagram() {
  return (
    <Card className="p-4 mb-5" data-testid="routing-diagram">
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <h3 className="text-sm font-semibold">Rule Book selection order</h3>
        <span className="text-xs text-muted-foreground">
          Evaluation order when an inbound document arrives
        </span>
      </div>
      <div className="text-xs font-medium text-muted-foreground mb-2 inline-flex items-center gap-1.5">
        <span className="inline-flex h-5 items-center rounded-md bg-muted px-2">
          Inbound document
        </span>
      </div>
      <div className="grid gap-2.5 lg:grid-cols-5">
        {ROUTING_STEPS.map((step, idx) => {
          const Icon = STEP_ICONS[idx] ?? Mail;
          return (
            <div key={step.n} className="relative flex">
              <div className="flex-1 rounded-lg border border-primary/20 bg-primary/5 p-3 min-w-0">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground text-xs font-semibold tnum">
                    {step.n}
                  </span>
                  <Icon className="h-4 w-4 text-primary shrink-0" />
                </div>
                <div className="text-xs font-semibold leading-tight mb-1">{step.title}</div>
                <div className="text-[11px] text-muted-foreground leading-snug">{step.desc}</div>
              </div>
              {idx < ROUTING_STEPS.length - 1 && (
                <div
                  className="hidden lg:flex items-center text-primary/50 px-0.5"
                  aria-hidden
                >
                  <ChevronDown className="h-4 w-4 -rotate-90" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
