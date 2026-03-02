/**
 * AgentMascot — animated mascot for running features.
 * 5 mascots assigned deterministically by feature ID hash.
 */

interface AgentMascotProps {
  featureId: string;
}

const MASCOTS = [
  { emoji: "⚡", name: "Volt", color: "rgba(250, 204, 21, 0.4)" },
  { emoji: "🔥", name: "Blaze", color: "rgba(239, 68, 68, 0.4)" },
  { emoji: "🌊", name: "Wave", color: "rgba(59, 130, 246, 0.4)" },
  { emoji: "🌿", name: "Sprout", color: "rgba(34, 197, 94, 0.4)" },
  { emoji: "🔮", name: "Mystic", color: "rgba(168, 85, 247, 0.4)" },
];

function hashId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function AgentMascot({ featureId }: AgentMascotProps) {
  const mascot = MASCOTS[hashId(featureId) % 5];

  return (
    <div className="flex items-center gap-1.5 mt-1.5">
      <div
        className="relative flex items-center justify-center w-6 h-6 rounded-full animate-mascot-glow"
        style={{
          boxShadow: `0 0 8px ${mascot.color}, 0 0 16px ${mascot.color}`,
        }}
      >
        <span className="text-sm">{mascot.emoji}</span>
      </div>
      <span className="text-[10px] font-medium text-blue-600 dark:text-blue-400">
        {mascot.name}
      </span>
    </div>
  );
}
