/**
 * CostSparkline — cost badge + SVG sparkline showing cumulative cost over time.
 * Shows a clean pill when no history, sparkline + live dot when history exists.
 */
import { useState } from "react";
import { DollarSign } from "lucide-react";

interface CostSparklineProps {
  costHistory: number[];
  currentCost: number;
}

export function CostSparkline({ costHistory, currentCost }: CostSparklineProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const data = costHistory.length > 0 ? costHistory : [currentCost];
  const hasHistory = data.length > 1;
  const width = 80;
  const height = 28;
  const padding = 4;

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
  const lastPoint = points[points.length - 1];

  // Color-code by spend level
  const valueColor =
    currentCost > 5
      ? "text-red-600 dark:text-red-400"
      : currentCost > 1
        ? "text-amber-600 dark:text-amber-400"
        : "text-slate-700 dark:text-slate-300";

  return (
    <div className="flex items-center gap-2 relative">
      {/* Cost pill */}
      <div
        className="flex items-center gap-1 px-2.5 py-1 rounded-full border
          bg-orange-50 border-orange-200 dark:bg-orange-950/30 dark:border-orange-800"
        title={`Total cost: $${currentCost.toFixed(4)}`}
      >
        <DollarSign size={11} className="text-orange-500 shrink-0" />
        <span className={`text-sm font-semibold font-mono tabular-nums leading-none ${valueColor}`}>
          {currentCost.toFixed(2)}
        </span>
      </div>

      {/* Sparkline — only when we have multiple data points */}
      {hasHistory && (
        <svg
          width={width}
          height={height}
          className="cursor-crosshair overflow-visible"
          onMouseLeave={() => setHoveredIndex(null)}
        >
          <defs>
            <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f97316" stopOpacity={0.25} />
              <stop offset="100%" stopColor="#f97316" stopOpacity={0.02} />
            </linearGradient>
          </defs>

          {/* Area fill */}
          <path d={areaPath} fill="url(#sparkGrad)" />

          {/* Line */}
          <path
            d={linePath}
            fill="none"
            stroke="#f97316"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Hovered data point dot */}
          {points.map((p, i) => (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={hoveredIndex === i ? 3 : 0}
              fill="#f97316"
              className="transition-all duration-100"
            />
          ))}

          {/* Live pulsing dot at latest data point */}
          {lastPoint && (
            <>
              {/* Ping ring */}
              <circle
                cx={lastPoint.x}
                cy={lastPoint.y}
                r={5}
                fill="#f97316"
                fillOpacity={0.25}
                className="animate-ping"
                style={{ transformOrigin: `${lastPoint.x}px ${lastPoint.y}px` }}
              />
              {/* Solid core */}
              <circle cx={lastPoint.x} cy={lastPoint.y} r={2.5} fill="#f97316" />
            </>
          )}

          {/* Invisible wider hover areas */}
          {points.map((p, i) => (
            <rect
              key={`h${i}`}
              x={p.x - 6}
              y={0}
              width={12}
              height={height}
              fill="transparent"
              onMouseEnter={() => setHoveredIndex(i)}
            />
          ))}
        </svg>
      )}

      {/* Hover tooltip */}
      {hoveredIndex !== null && hasHistory && (
        <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-slate-900 dark:bg-slate-700
          text-white text-[10px] font-mono px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap z-50">
          ${points[hoveredIndex]?.val.toFixed(4)}
        </div>
      )}
    </div>
  );
}
