import { useId, useRef } from 'react';
import { motion, useInView } from 'framer-motion';

const EASE = [0.16, 1, 0.3, 1];

export default function SectionDivider() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-15% 0px' });
  const gradientId = useId();

  return (
    <div ref={ref} className="mx-auto max-w-[1200px] px-5 sm:px-8" aria-hidden="true">
      <svg viewBox="0 0 1200 2" preserveAspectRatio="none" className="h-px w-full overflow-visible">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1200" y2="0" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="hsl(var(--primary))" stopOpacity="0" />
            <stop offset="0.5" stopColor="hsl(var(--primary))" stopOpacity="0.85" />
            <stop offset="0.5" stopColor="hsl(var(--accent-glow))" stopOpacity="0.85" />
            <stop offset="1" stopColor="hsl(var(--accent-glow))" stopOpacity="0" />
          </linearGradient>
        </defs>
        <motion.line
          x1="0"
          y1="1"
          x2="1200"
          y2="1"
          stroke={`url(#${gradientId})`}
          strokeWidth="1.5"
          initial={{ pathLength: 0, opacity: 0 }}
          animate={inView ? { pathLength: 1, opacity: 1 } : {}}
          transition={{ duration: 1.2, ease: EASE }}
        />
      </svg>
    </div>
  );
}
