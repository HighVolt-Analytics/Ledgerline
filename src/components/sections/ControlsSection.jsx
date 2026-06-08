import { Fingerprint, FileCheck, GitCompare, Users, Shield, Lock } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { controls } from '../../data/sections';

const icons = {
  C1: Fingerprint,
  C2: FileCheck,
  C3: GitCompare,
  C4: Users,
  C5: Shield,
  C6: Lock,
};

export default function ControlsSection() {
  return (
    <section id="controls" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>CFO-grade controls</SectionLabel>
        <SectionTitle className="mt-4">Six gates between the invoice and the wire.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Every control is enforced server-side. The UI may hint; the API rejects. This is the layer CFOs trust enough to sign for.
        </p>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-px overflow-hidden rounded-2xl border border-card-border bg-card-border sm:grid-cols-2 lg:grid-cols-3">
        {controls.map((ctrl, i) => {
          const Icon = icons[ctrl.code];
          return (
            <FadeIn key={ctrl.code} delay={i * 0.06}>
              <div className="group flex flex-col bg-card p-6 hover-elevate">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-lg font-medium text-primary">{ctrl.code}</span>
                  <Icon className="h-5 w-5 text-muted-foreground transition-colors group-hover:text-primary" />
                </div>
                <h3 className="mt-4 text-lg font-medium text-foreground">{ctrl.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{ctrl.desc}</p>
                <div className="mt-5 inline-flex w-fit items-center gap-1.5 rounded-full bg-destructive/10 px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.12em] text-destructive">
                  {ctrl.blocks}
                </div>
              </div>
            </FadeIn>
          );
        })}
      </div>
    </section>
  );
}
