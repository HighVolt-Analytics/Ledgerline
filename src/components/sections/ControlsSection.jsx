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

function ControlCard({ ctrl, delay }) {
  const Icon = icons[ctrl.code];

  return (
    <FadeIn delay={delay}>
      <article className="control-glass-card group relative flex h-full flex-col p-6">
        <div className="relative z-10 flex h-full flex-col">
          <div className="flex items-center justify-between gap-3">
            <div className="control-icon-box">
              <Icon className="control-icon-symbol h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
            </div>
            <span className="font-mono text-[11px] font-medium text-muted-foreground">{ctrl.code}</span>
          </div>

          <h3 className="mt-5 text-lg font-medium tracking-[-0.02em] text-foreground">{ctrl.title}</h3>
          <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">{ctrl.desc}</p>

          <p className="control-blocks-badge mt-4 whitespace-nowrap font-mono text-[9px] uppercase tracking-[0.14em]">
            {ctrl.blocks}
          </p>
        </div>
      </article>
    </FadeIn>
  );
}

export default function ControlsSection() {
  return (
    <section id="controls" className="relative mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 -z-10 h-[420px]"
        style={{
          background:
            'radial-gradient(ellipse 80% 55% at 50% 100%, hsl(14 70% 38% / 0.14), transparent 68%)',
        }}
        aria-hidden="true"
      />

      <FadeIn>
        <SectionLabel>CFO-grade controls</SectionLabel>
        <SectionTitle className="mt-4">Six gates between the invoice and the wire.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Every control is enforced server-side. The UI may hint; the API rejects. This is the layer CFOs trust enough to sign for.
        </p>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {controls.map((ctrl, i) => (
          <ControlCard key={ctrl.code} ctrl={ctrl} delay={i * 0.06} />
        ))}
      </div>
    </section>
  );
}
