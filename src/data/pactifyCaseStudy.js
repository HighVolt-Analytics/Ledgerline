export const pactifyCaseStudy = {
  slug: 'pactify',
  company: 'Pactify',
  sector: 'Bookkeeping & BAS',
  heroImage: '/qll/industries/accounting.png',
  heroPrimary: 'How Invoice to Pay took a quarterly BAS crunch',
  heroSecondary: 'from 6–7 hours down to 1',
  resultMetric: '1 hour',
  resultRest:
    'for the quarterly review that used to take six to seven hours. Consultancy fees for this work dropped by 50%.',
  about:
    'Every quarter, Pactify’s client sends 120 to 150 invoices for BAS lodgement. They arrive in a couple of days, by email and Slack, in whatever format the supplier used. Ledgerline’s Invoice to Pay flow now does the pull-and-draft work, and the consultant reviews and posts.',
  storySections: [
    {
      label: 'What the process used to look like',
      paragraphs: [
        'Every quarter, one of our clients sends us their invoices for BAS lodgement. Not a trickle. A flood. Somewhere between 120 and 150 invoices, landing in a couple of days, through email and Slack, in whatever format the supplier happened to use.',
        'If you have ever worked in accounting or bookkeeping, you know what comes next.',
        'A consultant would sit down and work through the pile. Done in one stretch, without breaks, this took six to seven hours. It was not hard work, exactly. It was repetitive, tedious, and honestly a bit boring. The kind of work where the risk is not that people cannot do it. It is that attention drifts, and a small mistake slips in.',
        'And the cost was not just the consultant’s time. It was the client’s consultancy fees, spent on data entry instead of on the things a consultant is actually good at.',
      ],
      bullets: [
        'Open each email or Slack message',
        'Download the invoice',
        'Save it in the right storage folder',
        'Create the entry in the accounting software',
        'Pay the bill, where payment was due',
        'Finish the accounting with payment posting',
        'Only then, start preparing the BAS report',
      ],
    },
    {
      label: 'What we changed',
      paragraphs: [
        'We implemented Ledgerline, our AI-powered finance automation system, with a flow we call Invoice to Pay. In plain terms, it does what the consultant used to do by hand.',
        'Invoices arriving by email are picked up automatically through Ledgerline’s email fetch. Slack can be connected too, so invoices shared there get pulled in as well.',
        'Format does not matter. PDF, Word, Excel, .eml, .json — all of it is read.',
        'Ledgerline extracts the data, creates a summary, and pushes a draft accounting entry into the accounting software.',
        'Each invoice is left ready for payment or bank reconciliation.',
      ],
    },
    {
      label: 'What the consultant does now',
      paragraphs: [
        'The consultant’s role shifted from typing to reviewing. They open the drafts, check what needs checking, and approve. One click, and it is posted.',
      ],
    },
    {
      label: 'The result',
      paragraphs: [
        'The quarterly cycle that took six to seven hours now takes about one hour, which is essentially the final review.',
        'The client’s consultancy fees for this work dropped by 50%.',
        'Same client, same volume, same quarterly deadline.',
        'For our consultants, it means time back for work that needs judgment rather than patience.',
      ],
    },
    {
      label: 'What we’d say honestly',
      paragraphs: [
        'It is not magic, and a human still signs off. We think that is the right design: automation does the repetitive pull-and-draft work, and an accountant stays accountable for the final call.',
        'The win is not removing people from finance. It is removing the part of the job nobody enjoys, so people can focus on the part that matters.',
        'If your team has a quarterly invoice pile that eats a full day, we are happy to talk about how Invoice to Pay could work for you.',
      ],
    },
  ],
};

export function pactifyStoryTitle() {
  return `${pactifyCaseStudy.company} case study — Quantum Ledger Line`;
}

export function pactifyStoryDescription() {
  return pactifyCaseStudy.resultRest;
}
