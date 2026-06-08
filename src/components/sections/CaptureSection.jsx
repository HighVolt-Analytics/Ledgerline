import { MessageCircle, Phone, Smartphone, Globe } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { captureChannels } from '../../data/sections';

const icons = {
  WhatsApp: MessageCircle,
  Viber: Phone,
  'Mobile app': Smartphone,
  'Web portal': Globe,
};

export default function CaptureSection() {
  return (
    <section className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Capture · v4</SectionLabel>
        <SectionTitle className="mt-4">Every channel your team actually uses.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Field staff don't open accounting apps. They use WhatsApp. Ledgerline meets them there — and pipes the receipt
          into the same controlled pipeline.
        </p>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {captureChannels.map((channel, i) => {
          const Icon = icons[channel.name];
          return (
            <FadeIn key={channel.name} delay={i * 0.07}>
              <div className="flex h-full flex-col rounded-2xl border border-card-border bg-card p-6 shadow-md">
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-lg bg-primary/12">
                    <Icon className="h-5 w-5 text-primary" />
                  </span>
                  <span className="text-base font-medium text-foreground">{channel.name}</span>
                </div>
                <p className="mt-4 flex-1 text-sm leading-relaxed text-muted-foreground">
                  &ldquo;{channel.action}&rdquo;
                </p>
                <div className="mt-5 h-px w-full ledgerline-gradient opacity-40" />
                <div className="mt-4 flex items-center justify-between">
                  <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-primary">OCR + auto-classify</span>
                  <span className="font-mono text-[11px] text-muted-foreground">{channel.share}</span>
                </div>
              </div>
            </FadeIn>
          );
        })}
      </div>
    </section>
  );
}
