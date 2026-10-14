import React, { useRef, useMemo, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import DottedMap from 'dotted-map';

const STATIC_MAP = new DottedMap({ height: 100, grid: 'diagonal' });

export function WorldMap({
  dots = [],
  lineColor = '#2FD4B5',
  showLabels = true,
  animationDuration = 2,
  loop = true,
}) {
  const svgRef = useRef(null);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 768);
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  const svgMap = useMemo(
    () =>
      STATIC_MAP.getSVG({
        radius: 0.22,
        color: '#FFFFFF40',
        shape: 'circle',
        backgroundColor: 'transparent',
      }),
    [],
  );

  const svgMapMobile = useMemo(
    () =>
      STATIC_MAP.getSVG({
        radius: 0.22,
        color: '#FB923C80',
        shape: 'circle',
        backgroundColor: 'transparent',
      }),
    [],
  );

  const projectPoint = (lat, lng) => {
    const x = (lng + 180) * (800 / 360);
    const y = (90 - lat) * (400 / 180);
    return { x, y };
  };

  const createCurvedPath = (start, end) => {
    const dist = Math.hypot(end.x - start.x, end.y - start.y);
    const lift = Math.min(46, Math.max(16, dist * 0.16));
    const midX = (start.x + end.x) / 2;
    const midY = Math.min(start.y, end.y) - lift;
    return `M ${start.x} ${start.y} Q ${midX} ${midY} ${end.x} ${end.y}`;
  };

  // Same positions as before — only box size grows on mobile so larger type fits.
  const getLabelPosition = (point, side) => {
    switch (side) {
      case 'left-above':
        return isMobile
          ? { x: point.x - 40, y: point.y - 34, align: 'justify-center', width: 80, height: 30 }
          : { x: point.x - 36, y: point.y - 28, align: 'justify-center', width: 72, height: 26 };
      case 'singapore':
        return isMobile
          ? { x: point.x - 120, y: point.y - 15, align: 'justify-center' }
          : { x: point.x - 120, y: point.y - 22, align: 'justify-center' };
      case 'myanmar':
        return isMobile
          ? { x: point.x + 8, y: point.y - 32, align: 'justify-start', width: 100, height: 30 }
          : { x: point.x + 10, y: point.y - 28, align: 'justify-start', width: 92, height: 26 };
      case 'australia':
        return { x: point.x - 120, y: point.y - (isMobile ? 3 : 80), align: 'justify-center' };
      case 'canada':
        return isMobile
          ? { x: point.x - 56, y: point.y + 8, align: 'justify-center', width: 112, height: 30 }
          : { x: point.x - 56, y: point.y + 10, align: 'justify-center', width: 112, height: 28 };
      case 'dubai':
        return isMobile
          ? { x: point.x - 72, y: point.y + 8, align: 'justify-center', width: 84, height: 28 }
          : { x: point.x - 72, y: point.y + 10, align: 'justify-center', width: 84, height: 24 };
      case 'usa':
        return isMobile
          ? { x: point.x - 30, y: point.y - 30, align: 'justify-center', width: 64, height: 28 }
          : { x: point.x - 30, y: point.y - 26, align: 'justify-center', width: 60, height: 22 };
      default:
        return { x: point.x - 120, y: point.y - 80, align: 'justify-center' };
    }
  };

  const staggerDelay = 0.5;
  const totalAnimationTime = dots.length * staggerDelay + animationDuration;
  const pauseTime = 2;
  const fullCycleDuration = totalAnimationTime + pauseTime;

  // foreignObject CSS px = SVG user units. Bump mobile type so it stays ~11–12px on screen.
  const labelClass = isMobile
    ? 'rounded border border-white/25 bg-black/95 px-2.5 py-1.5 text-[22px] font-bold leading-none text-white'
    : 'rounded border border-white/20 bg-black/90 px-2 py-1 text-xs font-bold text-white backdrop-blur-md';

  return (
    <div className="relative aspect-[1.5/1] min-h-[350px] w-full overflow-hidden rounded-lg bg-black/40 font-sans will-change-transform md:aspect-[2/1] md:bg-transparent">
      <img
        src={`data:image/svg+xml;utf8,${encodeURIComponent(isMobile ? svgMapMobile : svgMap)}`}
        className="pointer-events-none h-full w-full select-none object-contain opacity-60 transition-opacity duration-500"
        alt="world map"
        draggable={false}
      />

      <svg
        ref={svgRef}
        viewBox="0 0 800 400"
        className="pointer-events-auto absolute inset-0 z-20 h-full w-full select-none overflow-visible will-change-transform"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <linearGradient id="qll-path-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="white" stopOpacity="0" />
            <stop offset="4%" stopColor={lineColor} stopOpacity="1" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="1" />
          </linearGradient>

          <filter id="qll-map-glow">
            <feGaussianBlur stdDeviation="1" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {showLabels &&
          dots.map((dot, i) => {
            const startPoint = projectPoint(dot.start.lat, dot.start.lng);
            const endPoint = projectPoint(dot.end.lat, dot.end.lng);
            const labels = [];

            if (dot.end.label) {
              const pos = getLabelPosition(endPoint, dot.end.side);
              labels.push(
                <foreignObject
                  key={`end-label-${i}`}
                  x={pos.x}
                  y={pos.y}
                  width={pos.width ?? 240}
                  height={pos.height ?? 80}
                  className="pointer-events-none overflow-visible"
                >
                  <div className={`flex h-full w-full items-center ${pos.align}`}>
                    <span className={labelClass}>{dot.end.label}</span>
                  </div>
                </foreignObject>,
              );
            }

            if (dot.start.label && dots.findIndex((item) => item.start.label === dot.start.label) === i) {
              const pos = getLabelPosition(startPoint, dot.start.side);
              labels.push(
                <foreignObject
                  key={`start-label-${i}`}
                  x={pos.x}
                  y={pos.y}
                  width={pos.width ?? 240}
                  height={pos.height ?? 80}
                  className="pointer-events-none overflow-visible"
                >
                  <div className={`flex h-full w-full items-center ${pos.align}`}>
                    <span className={labelClass}>{dot.start.label}</span>
                  </div>
                </foreignObject>,
              );
            }

            return labels;
          })}

        {dots.map((dot, i) => {
          const startPoint = projectPoint(dot.start.lat, dot.start.lng);
          const endPoint = projectPoint(dot.end.lat, dot.end.lng);
          const startTime = (i * staggerDelay) / fullCycleDuration;
          const endTime = (i * staggerDelay + animationDuration) / fullCycleDuration;
          const resetTime = totalAnimationTime / fullCycleDuration;

          return (
            <motion.path
              key={`path-${i}`}
              d={createCurvedPath(startPoint, endPoint)}
              fill="none"
              stroke="url(#qll-path-gradient)"
              strokeWidth="1.5"
              initial={{ pathLength: 0 }}
              animate={loop ? { pathLength: [0, 0, 1, 1, 0] } : { pathLength: 1 }}
              transition={
                loop
                  ? {
                      duration: fullCycleDuration,
                      times: [0, startTime, endTime, resetTime, 1],
                      ease: 'easeInOut',
                      repeat: Infinity,
                    }
                  : {
                      duration: animationDuration,
                      delay: i * staggerDelay,
                      ease: 'easeInOut',
                    }
              }
            />
          );
        })}

        {dots.map((dot, i) => {
          const startPoint = projectPoint(dot.start.lat, dot.start.lng);
          const endPoint = projectPoint(dot.end.lat, dot.end.lng);

          return (
            <React.Fragment key={`points-${i}`}>
              <motion.circle
                cx={startPoint.x}
                cy={startPoint.y}
                r="3.5"
                fill={lineColor}
                filter="url(#qll-map-glow)"
                whileHover={{ scale: 1.5 }}
                className="cursor-pointer"
              />
              <motion.circle
                cx={endPoint.x}
                cy={endPoint.y}
                r="3.5"
                fill={lineColor}
                filter="url(#qll-map-glow)"
                whileHover={{ scale: 1.5 }}
                className="cursor-pointer"
              />
            </React.Fragment>
          );
        })}
      </svg>
    </div>
  );
}
