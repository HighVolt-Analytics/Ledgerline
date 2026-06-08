import { useEffect, useState } from 'react';
import { Menu, X } from 'lucide-react';
import Logo from '../ui/Logo';
import ThemeToggle from '../ui/ThemeToggle';
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
    <header className="fixed inset-x-0 top-0 z-50">
      <div
        className={`border-b transition-colors duration-300 ${
          scrolled ? 'border-border bg-background/70 backdrop-blur-xl' : 'border-transparent bg-transparent'
        }`}
      >
        <nav className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-5 sm:px-8">
          <button
            onClick={() => goTo('top')}
            className="hover-elevate rounded-md px-1 -mx-1"
            aria-label="Ledgerline home"
          >
            <Logo />
          </button>

          <div className="hidden items-center gap-8 md:flex">
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

          <div className="flex items-center gap-2">
            <ThemeToggle />
            <button
              onClick={() => goTo('pricing')}
              className="hidden rounded-lg px-3.5 py-2 text-sm text-muted-foreground hover-elevate active-elevate-2 sm:inline-flex"
            >
              Sign in
            </button>
            <button
              onClick={() => goTo('pricing')}
              className="hidden rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-transform duration-200 hover:scale-[1.02] active:scale-100 sm:inline-flex"
            >
              Start free
            </button>
            <button
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle menu"
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border text-foreground hover-elevate md:hidden"
            >
              {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </nav>
      </div>

      {menuOpen && (
        <div className="border-b border-border bg-background/95 backdrop-blur-xl md:hidden">
          <div className="mx-auto flex max-w-[1200px] flex-col gap-1 px-5 py-4">
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
              className="mt-1 rounded-lg bg-primary px-4 py-2.5 text-center text-sm font-medium text-primary-foreground"
            >
              Start free
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
