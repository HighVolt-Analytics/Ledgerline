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
    const midX = (start.x + end.x) / 2;
    const midY = Math.min(start.y, end.y) - 50;
    return `M ${start.x} ${start.y} Q ${midX} ${midY} ${end.x} ${end.y}`;
  };

  const getLabelPosition = (point, side) => {
    switch (side) {
      case 'left-above':
        return isMobile
          ? { x: point.x - 32, y: point.y - 26, align: 'justify-center', width: 64, height: 24 }
          : { x: point.x - 36, y: point.y - 28, align: 'justify-center', width: 72, height: 26 };
      case 'singapore':
        return isMobile
          ? { x: point.x - 120, y: point.y - 15, align: 'justify-center' }
          : { x: point.x - 120, y: point.y - 22, align: 'justify-center' };
      case 'myanmar':
        return isMobile
          ? { x: point.x + 8, y: point.y - 26, align: 'justify-start', width: 84, height: 24 }
          : { x: point.x + 10, y: point.y - 28, align: 'justify-start', width: 92, height: 26 };
      case 'australia':
        return { x: point.x - 120, y: point.y - (isMobile ? 3 : 80), align: 'justify-center' };
      default:
        return { x: point.x - 120, y: point.y - 80, align: 'justify-center' };
    }
  };

  const staggerDelay = 0.5;
  const totalAnimationTime = dots.length * staggerDelay + animationDuration;
  const pauseTime = 2;
  const fullCycleDuration = totalAnimationTime + pauseTime;

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
            <stop offset="5%" stopColor={lineColor} stopOpacity="1" />
            <stop offset="95%" stopColor={lineColor} stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </linearGradient>

          <filter id="qll-map-glow">
            <feGaussianBlur stdDeviation="1" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {dots.map((dot, i) => {
          const startPoint = projectPoint(dot.start.lat, dot.start.lng);
          const endPoint = projectPoint(dot.end.lat, dot.end.lng);
          const startTime = (i * staggerDelay) / fullCycleDuration;
          const endTime = (i * staggerDelay + animationDuration) / fullCycleDuration;
          const resetTime = totalAnimationTime / fullCycleDuration;

          return (
            <g key={`path-group-${i}`}>
              <motion.path
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
            </g>
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
                r="3"
                fill={lineColor}
                filter="url(#qll-map-glow)"
                whileHover={{ scale: 1.5 }}
                className="cursor-pointer"
              />
              <motion.circle
                cx={endPoint.x}
                cy={endPoint.y}
                r="3"
                fill={lineColor}
                filter="url(#qll-map-glow)"
                whileHover={{ scale: 1.5 }}
                className="cursor-pointer"
              />
              {showLabels &&
                dot.end.label &&
                (() => {
                  const pos = getLabelPosition(endPoint, dot.end.side);
                  return (
                    <foreignObject
                      x={pos.x}
                      y={pos.y}
                      width={pos.width ?? 240}
                      height={pos.height ?? 80}
                      className="pointer-events-none overflow-visible"
                    >
                      <div className={`flex h-full items-center ${pos.align}`}>
                        <span className="rounded border border-white/20 bg-black/90 px-2 py-1 text-[10px] font-bold text-white backdrop-blur-md md:text-xs">
                          {dot.end.label}
                        </span>
                      </div>
                    </foreignObject>
                  );
                })()}
            </React.Fragment>
          );
        })}
      </svg>
    </div>
  );
}
