import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { captureChannelIcons } from '../icons/CaptureChannelIcons';
import { captureChannels } from '../../data/sections';

function CaptureCard({ channel, delay }) {
  const Icon = captureChannelIcons[channel.name];

  return (
    <FadeIn delay={delay}>
      <article className="capture-ref-card group flex h-full flex-col">
        <div className="capture-ref-body flex h-full flex-col">
          <div className="flex items-center justify-between gap-3">
            <div className="capture-brand-logo">
              <Icon />
            </div>
            <span className="font-mono text-[11px] font-medium text-muted-foreground">{channel.share}</span>
          </div>

          <h3 className="mt-5 text-lg font-medium tracking-[-0.02em] text-foreground">{channel.name}</h3>
          <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">
            &ldquo;{channel.action}&rdquo;
          </p>

          <p className="capture-channel-meta mt-4 whitespace-nowrap font-mono text-[9px] uppercase tracking-[0.14em]">
            OCR + auto-classify
          </p>
        </div>
      </article>
    </FadeIn>
  );
}

export default function CaptureSection() {
  return (
    <section id="capture" className="relative mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Capture · v4</SectionLabel>
        <SectionTitle className="mt-4">Every channel your team actually uses.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Field staff don&apos;t open accounting apps. They use WhatsApp. Ledgerline meets them there — and pipes the
          receipt into the same controlled pipeline.
        </p>
      </FadeIn>

      <div className="mt-14 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {captureChannels.map((channel, i) => (
          <CaptureCard key={channel.name} channel={channel} delay={i * 0.06} />
        ))}
      </div>
    </section>
  );
}
