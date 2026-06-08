import { useTheme } from '../../context/ThemeContext';
import { themeAssets } from '../../data/assets';

export default function Logo({ className = '' }) {
  const { theme } = useTheme();

  return (
    <img
      src={themeAssets[theme].logo}
      alt="Ledgerline"
      className={`h-9 w-auto object-contain sm:h-10 ${className}`}
    />
  );
}
