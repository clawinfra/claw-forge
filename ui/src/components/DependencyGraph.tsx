/**
 * DependencyGraph — SVG-based dependency graph with topological layout.
 * No external libraries — pure SVG + React.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { useDarkMode } from "../hooks/useDarkMode";
import type { Feature } from "../types";

interface DependencyGraphProps {
  features: Feature[];
  onSelectFeature: (featureId: string) => void;
}

interface GraphNode {
  id: string;
  feature: Feature;
  depth: number;
  x: number;
  y: number;
}

const NODE_WIDTH = 180;
const NODE_HEIGHT = 48;
const H_GAP = 60;
const V_GAP = 24;
const PADDING = 40;

interface StatusColorSet {
  fill: string;
  stroke: string;
  text: string;
}

const STATUS_COLORS_LIGHT: Record<Feature["status"], StatusColorSet> = {
  pending: { fill: "#f1f5f9", stroke: "#94a3b8", text: "#475569" },
  queued: { fill: "#e0e7ff", stroke: "#818cf8", text: "#4338ca" },
  running: { fill: "#dbeafe", stroke: "#3b82f6", text: "#1e40af" },
  paused: { fill: "#f3e8ff", stroke: "#a855f7", text: "#6b21a8" },
  completed: { fill: "#d1fae5", stroke: "#10b981", text: "#065f46" },
  failed: { fill: "#fce7ef", stroke: "#ef4444", text: "#991b1b" },
  blocked: { fill: "#fef3c7", stroke: "#f59e0b", text: "#92400e" },
};

const STATUS_COLORS_DARK: Record<Feature["status"], StatusColorSet> = {
  pending: { fill: "#1e293b", stroke: "#64748b", text: "#cbd5e1" },
  queued: { fill: "#1e1b4b", stroke: "#818cf8", text: "#c7d2fe" },
  running: { fill: "#172554", stroke: "#60a5fa", text: "#bfdbfe" },
  paused: { fill: "#3b0764", stroke: "#c084fc", text: "#e9d5ff" },
  completed: { fill: "#052e16", stroke: "#34d399", text: "#a7f3d0" },
  failed: { fill: "#450a0a", stroke: "#f87171", text: "#fecaca" },
  blocked: { fill: "#451a03", stroke: "#fbbf24", text: "#fde68a" },
};


function computeLayout(features: Feature[]): { nodes: GraphNode[]; width: number; height: number } {
  // Build adjacency map
  const featureMap = new Map(features.map((f) => [f.id, f]));

  // Compute depth (topological level)
  const depth = new Map<string, number>();

  function getDepth(id: string, visited: Set<string>): number {
    if (depth.has(id)) return depth.get(id)!;
    if (visited.has(id)) return 0; // cycle guard
    visited.add(id);

    const feature = featureMap.get(id);
    if (!feature || feature.depends_on.length === 0) {
      depth.set(id, 0);
      return 0;
    }

    let maxDep = 0;
    for (const depId of feature.depends_on) {
      if (featureMap.has(depId)) {
        maxDep = Math.max(maxDep, getDepth(depId, visited) + 1);
      }
    }
    depth.set(id, maxDep);
    return maxDep;
  }

  for (const f of features) {
    getDepth(f.id, new Set());
  }

  // Group by depth
  const columns = new Map<number, Feature[]>();
  for (const f of features) {
    const d = depth.get(f.id) ?? 0;
    if (!columns.has(d)) columns.set(d, []);
    columns.get(d)!.push(f);
  }

  const maxDepth = Math.max(0, ...Array.from(columns.keys()));
  const maxColSize = Math.max(1, ...Array.from(columns.values()).map((c) => c.length));

  const nodes: GraphNode[] = [];
  for (const [d, col] of columns) {
    col.forEach((f, i) => {
      nodes.push({
        id: f.id,
        feature: f,
        depth: d,
        x: PADDING + d * (NODE_WIDTH + H_GAP),
        y: PADDING + i * (NODE_HEIGHT + V_GAP),
      });
    });
  }

  const width = PADDING * 2 + (maxDepth + 1) * (NODE_WIDTH + H_GAP) - H_GAP;
  const height = PADDING * 2 + maxColSize * (NODE_HEIGHT + V_GAP) - V_GAP;

  return { nodes, width: Math.max(width, 400), height: Math.max(height, 300) };
}

export function DependencyGraph({ features, onSelectFeature }: DependencyGraphProps) {
  const [isDark] = useDarkMode();
  const statusColors = isDark ? STATUS_COLORS_DARK : STATUS_COLORS_LIGHT;
  const edgeColor = isDark ? "#64748b" : "#94a3b8";
  const legendBg = isDark ? "#1e293b" : "white";
  const legendBgOpacity = isDark ? 0.9 : 0.8;
  const legendStroke = isDark ? "#334155" : "#e2e8f0";
  const legendText = isDark ? "#94a3b8" : "#64748b";

  const { nodes } = useMemo(() => computeLayout(features), [features]);
  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  // Pan & zoom state
  const svgRef = useRef<SVGSVGElement>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setZoom((z) => Math.max(0.2, Math.min(3, z * delta)));
  }, []);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as SVGElement).closest(".graph-node")) return;
      setDragging(true);
      dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
    },
    [pan],
  );

  const onMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!dragging) return;
      setPan({
        x: dragStart.current.panX + (e.clientX - dragStart.current.x),
        y: dragStart.current.panY + (e.clientY - dragStart.current.y),
      });
    },
    [dragging],
  );

  const onMouseUp = useCallback(() => {
    setDragging(false);
  }, []);

  // Edges
  const edges: { from: GraphNode; to: GraphNode }[] = [];
  for (const node of nodes) {
    for (const depId of node.feature.depends_on) {
      const depNode = nodeMap.get(depId);
      if (depNode) {
        edges.push({ from: depNode, to: node });
      }
    }
  }

  return (
    <div className="flex-1 overflow-hidden bg-slate-50 dark:bg-slate-900 relative">
      {features.length === 0 ? (
        <div className="flex items-center justify-center h-full text-slate-400 dark:text-slate-500">
          <p className="text-sm">No features to display</p>
        </div>
      ) : (
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          className={`${dragging ? "cursor-grabbing" : "cursor-grab"}`}
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          <defs>
            <marker
              id="arrowhead"
              viewBox="0 0 10 7"
              refX="10"
              refY="3.5"
              markerWidth="8"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <polygon points="0 0, 10 3.5, 0 7" fill={edgeColor} />
            </marker>
          </defs>

          <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
            {/* Edges */}
            {edges.map((edge) => {
              const x1 = edge.from.x + NODE_WIDTH;
              const y1 = edge.from.y + NODE_HEIGHT / 2;
              const x2 = edge.to.x;
              const y2 = edge.to.y + NODE_HEIGHT / 2;
              const mx = (x1 + x2) / 2;

              return (
                <path
                  key={`${edge.from.id}-${edge.to.id}`}
                  d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                  fill="none"
                  stroke={edgeColor}
                  strokeWidth={1.5}
                  markerEnd="url(#arrowhead)"
                  className="opacity-50"
                />
              );
            })}

            {/* Nodes */}
            {nodes.map((node) => {
              const colors = statusColors[node.feature.status];
              return (
                <g
                  key={node.id}
                  className="graph-node cursor-pointer"
                  transform={`translate(${node.x}, ${node.y})`}
                  onClick={() => onSelectFeature(node.id)}
                >
                  <rect
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    rx={8}
                    fill={colors.fill}
                    stroke={colors.stroke}
                    strokeWidth={2}
                    className="transition-all duration-200 hover:brightness-95"
                  />
                  {/* Status indicator dot */}
                  <circle cx={14} cy={NODE_HEIGHT / 2} r={4} fill={colors.stroke} />
                  {/* Name */}
                  <text
                    x={26}
                    y={NODE_HEIGHT / 2 - 4}
                    fontSize={11}
                    fontWeight={600}
                    fill={colors.text}
                  >
                    {node.feature.name.length > 18
                      ? node.feature.name.slice(0, 18) + "…"
                      : node.feature.name}
                  </text>
                  {/* Status label */}
                  <text
                    x={26}
                    y={NODE_HEIGHT / 2 + 12}
                    fontSize={9}
                    fill={colors.stroke}
                  >
                    {node.feature.status}
                  </text>
                </g>
              );
            })}
          </g>

          {/* Legend */}
          <g transform={`translate(${10}, ${10})`}>
            <rect
              width={130}
              height={20}
              rx={4}
              fill={legendBg}
              fillOpacity={legendBgOpacity}
              stroke={legendStroke}
            />
            <text x={8} y={14} fontSize={10} fill={legendText}>
              Scroll: zoom · Drag: pan
            </text>
          </g>
        </svg>
      )}
    </div>
  );
}
