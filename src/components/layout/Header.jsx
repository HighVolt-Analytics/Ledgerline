import { useEffect, useState } from 'react';
import { Menu, X } from 'lucide-react';
import Logo from '../ui/Logo';
import { navLinks } from '../../data/navigation';
import { scrollToSection } from '../../utils/scroll';

export default function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const goTo = (id) => {
    scrollToSection(id);
    setMenuOpen(false);
  };

  return (
    <header className="fixed inset-x-0 top-0 z-50 px-4 pt-3 sm:px-6 sm:pt-4">
      <div
        className={`mx-auto max-w-[1200px] overflow-hidden rounded-2xl border transition-all duration-300 ${
          scrolled
            ? 'border-border bg-background/90 shadow-lg backdrop-blur-xl'
            : 'border-border/70 bg-card/75 shadow-md backdrop-blur-md'
        }`}
      >
        <nav className="flex h-14 items-center justify-between gap-4 px-4 sm:h-[3.75rem] sm:px-6">
          <button
            onClick={() => goTo('top')}
            className="hover-elevate inline-flex shrink-0 items-center gap-2 rounded-md px-1"
            aria-label="Ledgerline home"
          >
            <Logo className="h-7 sm:h-8" />
            <span className="hidden text-base font-semibold tracking-tight text-foreground sm:inline-flex">
              Ledgerline
            </span>
          </button>

          <div className="hidden items-center gap-7 lg:flex">
            {navLinks.map((link, i) => (
              <button
                key={`${link.label}-${i}`}
                onClick={() => goTo(link.id)}
                className="group relative text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {link.label}
                <span className="absolute -bottom-1.5 left-0 h-px w-0 bg-primary transition-all duration-200 group-hover:w-full" />
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <button
              onClick={() => goTo('pricing')}
              className="hidden rounded-full px-4 py-2 text-sm text-muted-foreground hover-elevate active-elevate-2 sm:inline-flex"
            >
              Sign in
            </button>
            <button
              onClick={() => goTo('pricing')}
              className="hidden rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-transform duration-200 hover:scale-[1.02] active:scale-100 sm:inline-flex"
            >
              Start free
            </button>
            <button
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle menu"
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-border text-foreground hover-elevate lg:hidden"
            >
              {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </nav>

        {menuOpen && (
          <div className="border-t border-border lg:hidden">
            <div className="flex flex-col gap-1 px-4 py-3">
              {navLinks.map((link, i) => (
                <button
                  key={`mobile-${link.label}-${i}`}
                  onClick={() => goTo(link.id)}
                  className="rounded-lg px-3 py-2.5 text-left text-sm text-muted-foreground hover-elevate"
                >
                  {link.label}
                </button>
              ))}
              <button
                onClick={() => goTo('pricing')}
                className="mt-2 rounded-full bg-primary px-4 py-2.5 text-center text-sm font-medium text-primary-foreground"
              >
                Start free
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
