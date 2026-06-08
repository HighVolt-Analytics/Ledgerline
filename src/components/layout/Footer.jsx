import Logo from '../ui/Logo';
import SectionDivider from './SectionDivider';
import { footerCompanyLinks, footerProductLinks } from '../../data/navigation';

export default function Footer() {
  return (
    <footer className="mx-auto max-w-[1200px] px-5 pb-12 pt-8 sm:px-8">
      <div className="grid grid-cols-1 gap-10 sm:grid-cols-3">
        <div>
          <Logo />
          <p className="mt-4 max-w-xs text-sm text-muted-foreground">
            Invoices in. Ledgers out. Payments through. Zero touch.
          </p>
          <p className="mt-6 font-mono text-[12px] text-muted-foreground">© 2026 Ledgerline</p>
        </div>

        <nav className="flex flex-col gap-3">
          {footerProductLinks.map((link) => (
            <a key={link} href="#pricing" className="w-fit text-sm text-muted-foreground transition-colors hover:text-foreground">
              {link}
            </a>
          ))}
        </nav>

        <nav className="flex flex-col gap-3">
          {footerCompanyLinks.map((link) => (
            <a key={link} href="#faq" className="w-fit text-sm text-muted-foreground transition-colors hover:text-foreground">
              {link}
            </a>
          ))}
        </nav>
      </div>

      <div className="mt-12">
        <SectionDivider />
      </div>

      <p className="mt-6 text-center font-mono text-[12px] text-muted-foreground">
        Built in Sydney. Posted to ledgers worldwide.
      </p>
    </footer>
  );
}
