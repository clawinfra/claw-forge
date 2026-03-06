/**
 * ProgressBar — overall project progress indicator.
 *
 * Shows: X / Y features passing with a coloured fill bar.
 * Fill width is tweened via GSAP (power2.out) for a satisfying deceleration.
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

  const fillColour =
    pct === 100
      ? "bg-emerald-500"
      : pct >= 60
        ? "bg-blue-500"
        : pct >= 30
          ? "bg-amber-500"
          : "bg-red-500";

  useEffect(() => {
    if (!fillRef.current) return;
    gsap.to(fillRef.current, { width: `${pct}%`, duration: 0.6, ease: "power2.out" });
  }, [pct]);

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <div className="flex justify-between text-xs font-medium text-slate-600 dark:text-slate-400">
        <span>Progress</span>
        <span>
          {passing}/{total} passing ({pct}%)
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
        <div
          ref={fillRef}
          className={`h-full rounded-full ${fillColour}`}
          style={{ width: "0%" }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
    </div>
  );
}
