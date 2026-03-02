/**
 * CelebrationOverlay — confetti + message when 100% features pass.
 * Pure CSS animations, no external library.
 */
import { useEffect, useRef, useState } from "react";
import { PartyPopper } from "lucide-react";

interface CelebrationOverlayProps {
  passing: number;
  total: number;
}

const CONFETTI_COLORS = [
  "#f97316", "#3b82f6", "#22c55e", "#eab308", "#ec4899",
  "#8b5cf6", "#14b8a6", "#ef4444", "#06b6d4", "#f59e0b",
];

function ConfettiPiece({ index }: { index: number }) {
  const color = CONFETTI_COLORS[index % CONFETTI_COLORS.length];
  const left = Math.random() * 100;
  const delay = Math.random() * 2;
  const duration = 2 + Math.random() * 2;
  const size = 6 + Math.random() * 8;
  const rotation = Math.random() * 360;

  return (
    <div
      className="absolute top-0 animate-confetti-fall pointer-events-none"
      style={{
        left: `${left}%`,
        animationDelay: `${delay}s`,
        animationDuration: `${duration}s`,
      }}
    >
      <div
        className="animate-confetti-spin"
        style={{
          width: `${size}px`,
          height: `${size * 0.6}px`,
          backgroundColor: color,
          borderRadius: "2px",
          transform: `rotate(${rotation}deg)`,
        }}
      />
    </div>
  );
}

export function CelebrationOverlay({ passing, total }: CelebrationOverlayProps) {
  const [show, setShow] = useState(false);
  const firedRef = useRef(false);

  useEffect(() => {
    if (passing === total && total > 0 && !firedRef.current) {
      firedRef.current = true;
      setShow(true);
      const timer = setTimeout(() => setShow(false), 5000);
      return () => clearTimeout(timer);
    }
  }, [passing, total]);

  if (!show) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 backdrop-blur-sm cursor-pointer"
      onClick={() => setShow(false)}
    >
      {/* Confetti */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {Array.from({ length: 50 }, (_, i) => (
          <ConfettiPiece key={i} index={i} />
        ))}
      </div>

      {/* Message */}
      <div className="relative z-10 bg-white dark:bg-slate-800 rounded-2xl shadow-2xl px-12 py-10 text-center animate-celebration-pop">
        <div className="flex justify-center mb-4">
          <PartyPopper size={48} className="text-amber-500" />
        </div>
        <h2 className="text-3xl font-bold text-slate-800 dark:text-slate-100 mb-2">
          🎉 All features passing!
        </h2>
        <p className="text-slate-500 dark:text-slate-400 text-lg">
          {total} / {total} features completed successfully
        </p>
        <p className="text-slate-400 dark:text-slate-500 text-sm mt-3">
          Click anywhere to dismiss
        </p>
      </div>
    </div>
  );
}
