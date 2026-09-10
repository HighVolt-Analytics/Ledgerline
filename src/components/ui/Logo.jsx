import { assets } from '../../data/assets';

export default function Logo({ className = '' }) {
  return (
    <img
      src={assets.logo}
      alt="Ledgerline"
      className={`h-9 w-auto max-w-none object-contain sm:h-10 ${className}`}
    />
  );
}
