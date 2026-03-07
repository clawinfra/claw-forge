/**
 * ProgressBar — overall project progress indicator.
 *
 * Shows: X / Y features passing with a coloured gradient fill bar.
 * Fill width is tweened via GSAP (power2.out). Milestone ticks at 25/50/75%.
 * A moving shimmer overlays the fill while progress is in-flight.
 */
import { useEffect, useRef } from "react";
import { gsap } from "gsap";

interface ProgressBarProps {
  passing: number;
  total: number;
  className?: string;
}

export function ProgressBar({ passing, total, className = "" }: ProgressBarProps) {
  const pct = total > 0 ? Math.round((passing / total) * 100) : 0;
  const fillRef = useRef<HTMLDivElement>(null);
  const isComplete = pct === 100;

  // Gradient fill colour by progress tier
  const fillGradient = isComplete
    ? "bg-gradient-to-r from-emerald-400 to-emerald-500"
    : pct >= 60
      ? "bg-gradient-to-r from-blue-400 to-blue-500"
      : pct >= 30
        ? "bg-gradient-to-r from-amber-400 to-orange-400"
        : "bg-gradient-to-r from-red-400 to-rose-400";

  const pctColor = isComplete
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-slate-700 dark:text-slate-200";

  useEffect(() => {
    if (!fillRef.current) return;
    gsap.to(fillRef.current, { width: `${pct}%`, duration: 0.6, ease: "power2.out" });
  }, [pct]);

  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {/* Labels */}
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
          Progress
        </span>
        <div className="flex items-baseline gap-1.5 text-xs">
          <span className="font-mono font-semibold tabular-nums text-slate-700 dark:text-slate-200">
            {passing}
            <span className="text-slate-400 dark:text-slate-500 font-normal">/{total}</span>
          </span>
          <span className="text-slate-400 dark:text-slate-500">passing</span>
          <span className={`font-bold tabular-nums ${pctColor}`}>{pct}%</span>
        </div>
      </div>

      {/* Track */}
      <div className="relative h-2.5 w-full rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
        {/* Animated fill */}
        <div
          ref={fillRef}
          className={`h-full rounded-full ${fillGradient} ${!isComplete && pct > 0 ? "progress-shimmer" : ""}`}
          style={{ width: "0%" }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
        {/* Milestone ticks at 25 / 50 / 75 % */}
        {[25, 50, 75].map((m) => (
          <div
            key={m}
            className="absolute top-0 bottom-0 w-px bg-white/40 dark:bg-black/25 pointer-events-none"
            style={{ left: `${m}%` }}
          />
        ))}
      </div>
    </div>
  );
}
