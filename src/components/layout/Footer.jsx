import Logo from '../ui/Logo';
import { footerCompanyLinks, footerProductLinks } from '../../data/navigation';
import { scrollToSection } from '../../utils/scroll';

const productIds = {
  Product: 'how',
  'How it works': 'how',
  Pricing: 'pricing',
  Changelog: 'how',
  Status: 'faq',
};

const companyIds = {
  Company: 'how',
  Security: 'faq',
  Privacy: 'faq',
  Terms: 'faq',
  Contact: 'pricing',
};

function FooterLink({ label, id }) {
  return (
    <button
      type="button"
      onClick={() => scrollToSection(id)}
      className="w-fit text-left text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      {label}
    </button>
  );
}

export default function Footer() {
  return (
    <footer className="footer-accent border-t border-primary/20 bg-background">
      <div className="mx-auto max-w-[1200px] px-5 py-12 sm:px-8 sm:py-14">
        <div className="grid grid-cols-1 gap-10 sm:grid-cols-3">
          <div>
            <div className="inline-flex items-center">
              <Logo />
            </div>
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-muted-foreground">
              Invoices in. Ledgers out. Payments through. Zero touch.
            </p>
          </div>

          <nav className="flex flex-col gap-3">
            {footerProductLinks.map((link) => (
              <FooterLink key={link} label={link} id={productIds[link] ?? 'how'} />
            ))}
          </nav>

          <nav className="flex flex-col gap-3">
            {footerCompanyLinks.map((link) => (
              <FooterLink key={link} label={link} id={companyIds[link] ?? 'faq'} />
            ))}
          </nav>
        </div>

        <div className="footer-bottom mt-12 flex flex-col gap-4 pt-6 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="flex flex-col gap-1.5">
            <p className="text-sm text-muted-foreground">© 2026 Ledgerline. All Rights Reserved.</p>
            <p className="font-mono text-[12px] text-muted-foreground">
              Built in Sydney. Posted to ledgers worldwide.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-5">
            <FooterLink label="Privacy" id="faq" />
            <FooterLink label="Terms & condition" id="faq" />
          </div>
        </div>
      </div>
    </footer>
  );
}
