/**
 * CostSparkline — tiny SVG sparkline showing cumulative cost over time.
 * Pure SVG, no external libraries.
 */
import { useState } from "react";

interface CostSparklineProps {
  costHistory: number[];
  currentCost: number;
}

export function CostSparkline({ costHistory, currentCost }: CostSparklineProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  // Use costHistory if available, otherwise just show the current cost
  const data = costHistory.length > 0 ? costHistory : [currentCost];
  const width = 120;
  const height = 28;
  const padding = 2;

  const max = Math.max(...data, 0.01);
  const min = Math.min(...data, 0);

  const points = data.map((val, i) => {
    const x = padding + (i / Math.max(data.length - 1, 1)) * (width - padding * 2);
    const y =
      height -
      padding -
      ((val - min) / (max - min || 1)) * (height - padding * 2);
    return { x, y, val };
  });

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const areaPath = `${linePath} L ${points[points.length - 1]?.x ?? 0} ${height} L ${points[0]?.x ?? 0} ${height} Z`;

  return (
    <div className="flex items-center gap-2 font-mono text-slate-700 dark:text-slate-300 relative">
      <span className="text-slate-400 dark:text-slate-500 font-sans text-xs mr-1">total</span>
      <svg
        width={width}
        height={height}
        className="cursor-crosshair"
        onMouseLeave={() => setHoveredIndex(null)}
      >
        {/* Gradient fill */}
        <defs>
          <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f97316" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#f97316" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        {data.length > 1 && (
          <>
            <path d={areaPath} fill="url(#sparkGrad)" />
            <path
              d={linePath}
              fill="none"
              stroke="#f97316"
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </>
        )}
        {/* Hover targets */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={p.x}
            cy={p.y}
            r={hoveredIndex === i ? 3 : data.length > 1 ? 0 : 2.5}
            fill="#f97316"
            className="transition-all duration-100"
            onMouseEnter={(e) => {
              setHoveredIndex(i);
              const rect = (e.target as SVGElement).closest("svg")?.getBoundingClientRect();
              if (rect) {
                setTooltipPos({ x: p.x, y: rect.top - 24 });
              }
            }}
          />
        ))}
        {/* Invisible wider hover areas */}
        {points.map((p, i) => (
          <rect
            key={`h${i}`}
            x={p.x - 4}
            y={0}
            width={8}
            height={height}
            fill="transparent"
            onMouseEnter={(e) => {
              setHoveredIndex(i);
              const rect = (e.target as SVGElement).closest("svg")?.getBoundingClientRect();
              if (rect) {
                setTooltipPos({ x: p.x, y: rect.top - 24 });
              }
            }}
          />
        ))}
      </svg>
      <span className="text-sm">${currentCost.toFixed(2)}</span>
      {/* Tooltip */}
      {hoveredIndex !== null && (
        <div
          className="absolute -top-7 bg-slate-900 dark:bg-slate-700 text-white text-[10px] px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap z-50"
          style={{ left: `${tooltipPos.x + 28}px` }}
        >
          ${points[hoveredIndex]?.val.toFixed(3)}
        </div>
      )}
    </div>
  );
}
