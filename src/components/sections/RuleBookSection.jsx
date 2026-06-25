import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { ruleBookBentoCards } from './RuleBookBento';

export default function RuleBookSection() {
  return (
    <section id="rulebook" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Deterministic by design</SectionLabel>
        <SectionTitle className="mt-4">The Rule Book is why we win.</SectionTitle>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Five priority bands. Deterministic. Auditable. No black-box ML deciding where your money goes.
        </p>
      </FadeIn>

      <FadeIn delay={0.06}>
        <div className="rulebook-bento-grid mt-14 grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-3 lg:grid-rows-2 lg:gap-4">
          {ruleBookBentoCards.map(({ component: Card, layout }, i) => (
            <FadeIn key={i} delay={i * 0.05} className={`h-full min-h-0 ${layout}`}>
              <div className="rulebook-bento-card h-full">
                <Card />
              </div>
            </FadeIn>
          ))}
        </div>
      </FadeIn>
    </section>
  );
}
