import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import Logo from '../ui/Logo';
import { navLinks, externalLinks, tourPath } from '../../data/navigation';
import { scrollToSection } from '../../utils/scroll';

export default function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const isHome = location.pathname === '/';

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [menuOpen]);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isHome) return;
    const hash = location.hash?.replace('#', '');
    if (!hash) return;
    const timer = window.setTimeout(() => scrollToSection(hash), 80);
    return () => window.clearTimeout(timer);
  }, [isHome, location.hash]);

  const goHome = () => {
    if (isHome) {
      scrollToSection('hero');
      setMenuOpen(false);
      return;
    }
    navigate('/');
    setMenuOpen(false);
  };

  const goToSection = (id) => {
    setMenuOpen(false);
    if (isHome) {
      scrollToSection(id);
      return;
    }
    navigate(`/#${id}`);
  };

  return (
    <header className="fixed inset-x-0 top-0 z-50 px-3 pt-3 sm:px-6 sm:pt-4">
      <div
        className={`mx-auto max-w-[1200px] overflow-hidden rounded-2xl border transition-all duration-300 ${
          scrolled
            ? 'border-border bg-background/90 shadow-lg backdrop-blur-xl'
            : 'border-border/70 bg-card/75 shadow-md backdrop-blur-md'
        }`}
      >
        <nav className="flex h-14 min-w-0 items-center justify-between gap-3 px-3 sm:h-[3.75rem] sm:gap-4 sm:px-6">
          <button
            type="button"
            onClick={goHome}
            className="hover-elevate inline-flex min-w-0 shrink items-center gap-2 rounded-md px-1"
            aria-label="Quantum Ledgerline home"
          >
            <Logo className="h-7 w-auto shrink-0 sm:h-8" />
            <span className="brand-wordmark">Quantum Ledgerline</span>
          </button>

          <div className="hidden items-center gap-4 xl:flex xl:gap-7">
            {navLinks.map((link, i) => (
              <button
                key={`${link.label}-${i}`}
                type="button"
                onClick={() => goToSection(link.id)}
                className="group relative whitespace-nowrap text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {link.label}
                <span className="absolute -bottom-1.5 left-0 h-px w-0 bg-primary transition-all duration-200 group-hover:w-full" />
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <a
              href={externalLinks.signup}
              className="hidden rounded-full px-4 py-2 text-sm text-muted-foreground hover-elevate active-elevate-2 sm:inline-flex"
            >
              Sign in
            </a>
            <Link
              to={tourPath}
              className="hidden rounded-full px-4 py-2 text-sm font-semibold shadow-sm transition-all duration-200 hover:scale-[1.02] active:scale-100 sm:inline-flex sm:px-5"
              style={{ background: '#2FD4B5', color: '#04161C' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#4FE3C8';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = '#2FD4B5';
              }}
            >
              Demo tour
            </Link>
            <button
              type="button"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle menu"
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-border text-foreground hover-elevate xl:hidden"
            >
              {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </nav>
      </div>

      {menuOpen && (
        <div className="fixed inset-0 z-[60] flex flex-col bg-background xl:hidden">
          <div className="flex h-14 items-center justify-between px-6 sm:h-[3.75rem]">
            <button
              type="button"
              onClick={goHome}
              className="inline-flex min-w-0 items-center gap-2"
              aria-label="Quantum Ledgerline home"
            >
              <Logo className="h-7 w-auto shrink-0 sm:h-8" />
              <span className="brand-wordmark">Quantum Ledgerline</span>
            </button>
            <button
              type="button"
              onClick={() => setMenuOpen(false)}
              aria-label="Close menu"
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-border text-foreground hover-elevate"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="flex flex-1 flex-col gap-1 overflow-y-auto px-6 pb-8 pt-4">
            {navLinks.map((link, i) => (
              <button
                key={`mobile-${link.label}-${i}`}
                type="button"
                onClick={() => goToSection(link.id)}
                className="rounded-xl px-4 py-4 text-left text-lg font-medium text-foreground hover-elevate"
              >
                {link.label}
              </button>
            ))}
            <Link
              to={tourPath}
              onClick={() => setMenuOpen(false)}
              className="mt-auto rounded-full px-4 py-3.5 text-center text-base font-semibold"
              style={{ background: '#2FD4B5', color: '#04161C' }}
            >
              Demo tour
            </Link>
          </div>
        </div>
      )}
    </header>
  );
}
