import * as Accordion from '@radix-ui/react-accordion';
import { ChevronDown } from 'lucide-react';
import SectionLabel from '../ui/SectionLabel';
import SectionTitle from '../ui/SectionTitle';
import { faqItems } from '../../data/faq';

const leftFaqs = faqItems.slice(0, 5);
const rightFaqs = faqItems.slice(5, 10);

function FaqHeadline() {
  return (
    <>
      <SectionLabel>Questions</SectionLabel>
      <SectionTitle className="mt-4">Answers, not asterisks.</SectionTitle>
      <p className="mt-5 max-w-sm text-base leading-relaxed text-muted-foreground">
        Straight answers on payments, controls, security, and how Ledgerline fits your stack.
      </p>
    </>
  );
}

function FaqColumn({ items, offset }) {
  return (
    <div>
      {items.map((item, i) => {
        const index = offset + i;
        return (
          <Accordion.Item key={item.q} value={`item-${index}`} className="border-b border-border">
            <Accordion.Header>
              <Accordion.Trigger className="group flex w-full flex-1 items-center justify-between gap-4 py-5 text-left text-base font-medium text-foreground hover:no-underline">
                {item.q}
                <ChevronDown className="h-4 w-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-180" />
              </Accordion.Trigger>
            </Accordion.Header>
            <Accordion.Content className="overflow-hidden text-sm data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down">
              <div className="pb-4 pt-0 text-[15px] leading-relaxed text-muted-foreground">{item.a}</div>
            </Accordion.Content>
          </Accordion.Item>
        );
      })}
    </div>
  );
}

export default function FaqSection() {
  return (
    <section id="faq" className="mx-auto max-w-[1200px] px-5 py-20 sm:px-8 sm:py-28">
      <div className="faq-layout grid grid-cols-1 gap-12 lg:grid-cols-[22rem_minmax(0,1fr)] lg:gap-16">
        <aside className="faq-headline-panel hidden lg:block">
          <FaqHeadline />
        </aside>

        <div className="min-w-0 lg:col-start-2 lg:row-start-1">
          <aside className="mb-10 lg:hidden">
            <FaqHeadline />
          </aside>

          <Accordion.Root type="single" collapsible>
            <div className="grid grid-cols-1 gap-x-10 sm:grid-cols-2">
              <FaqColumn items={leftFaqs} offset={0} />
              <FaqColumn items={rightFaqs} offset={5} />
            </div>
          </Accordion.Root>
        </div>
      </div>
    </section>
  );
}
