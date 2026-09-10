import { useEffect } from 'react';
import Header from '../components/layout/Header';
import Logo from '../components/ui/Logo';
import SupademoEmbed from '../components/ui/SupademoEmbed';
import { tourPath } from '../data/navigation';

export default function InteractiveTourPage() {
  useEffect(() => {
    document.body.classList.remove('qll-page');
    window.scrollTo(0, 0);
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Header />
      <main className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-28 sm:px-6 sm:pt-32">
        <div className="mb-6">
          <p className="font-mono text-[12px] uppercase tracking-[0.28em] text-muted-foreground">
            Product walkthrough
          </p>
          <h1 className="mt-2 text-2xl font-medium tracking-tight text-foreground sm:text-3xl">
            Interactive Tour
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground sm:text-base">
            Explore Ledgerline step by step. Share this page anytime — the tour stays at{' '}
            <span className="text-foreground">{tourPath}</span>.
          </p>
        </div>

        <div className="overflow-hidden rounded-2xl border border-border bg-black shadow-lg">
          <SupademoEmbed />
        </div>

        <div className="mt-8 flex items-center gap-3 text-sm text-muted-foreground">
          <Logo className="h-7 sm:h-8" />
          <span>Ledgerline interactive demo</span>
        </div>
      </main>
    </div>
  );
}
