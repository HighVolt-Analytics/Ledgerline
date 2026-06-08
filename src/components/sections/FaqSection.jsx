import * as Accordion from '@radix-ui/react-accordion';
import { ChevronDown } from 'lucide-react';
import FadeIn from '../ui/FadeIn';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { faqItems } from '../../data/faq';

export default function FaqSection() {
  return (
    <section id="faq" className="mx-auto max-w-3xl px-5 py-20 sm:px-8 sm:py-28">
      <FadeIn>
        <SectionLabel>Questions</SectionLabel>
        <SectionTitle className="mt-4">Answers, not asterisks.</SectionTitle>
      </FadeIn>

      <FadeIn delay={0.1}>
        <Accordion.Root type="single" collapsible className="mt-10">
          {faqItems.map((item, i) => (
            <Accordion.Item key={item.q} value={`item-${i}`} className="border-b border-border">
              <Accordion.Header>
                <Accordion.Trigger className="group flex w-full flex-1 items-center justify-between py-5 text-left text-base font-medium text-foreground hover:no-underline">
                  {item.q}
                  <ChevronDown className="h-4 w-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180" />
                </Accordion.Trigger>
              </Accordion.Header>
              <Accordion.Content className="overflow-hidden text-sm data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down">
                <div className="pb-4 pt-0 text-[15px] leading-relaxed text-muted-foreground">{item.a}</div>
              </Accordion.Content>
            </Accordion.Item>
          ))}
        </Accordion.Root>
      </FadeIn>
    </section>
  );
}
