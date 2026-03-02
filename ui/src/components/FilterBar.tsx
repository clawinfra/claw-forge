/**
 * FilterBar — search + category dropdown + status filter chips.
 */
import { Search, X, Filter } from "lucide-react";
import type { FeatureStatus, FilterState } from "../types";

interface FilterBarProps {
  filters: FilterState;
  onFiltersChange: (filters: FilterState) => void;
  searchInputRef: React.RefObject<HTMLInputElement>;
}

const CATEGORIES = ["All", "backend", "frontend", "testing", "infra", "security", "docs"];

const STATUS_CHIPS: { status: FeatureStatus; label: string; color: string; activeColor: string }[] = [
  { status: "pending", label: "Pending", color: "border-slate-300 text-slate-500 dark:border-slate-600 dark:text-slate-400", activeColor: "bg-slate-200 border-slate-400 text-slate-700 dark:bg-slate-700 dark:border-slate-500 dark:text-slate-200" },
  { status: "running", label: "Running", color: "border-blue-300 text-blue-500 dark:border-blue-700 dark:text-blue-400", activeColor: "bg-blue-100 border-blue-400 text-blue-700 dark:bg-blue-900 dark:border-blue-600 dark:text-blue-200" },
  { status: "completed", label: "Passing", color: "border-emerald-300 text-emerald-500 dark:border-emerald-700 dark:text-emerald-400", activeColor: "bg-emerald-100 border-emerald-400 text-emerald-700 dark:bg-emerald-900 dark:border-emerald-600 dark:text-emerald-200" },
  { status: "failed", label: "Failed", color: "border-red-300 text-red-500 dark:border-red-700 dark:text-red-400", activeColor: "bg-red-100 border-red-400 text-red-700 dark:bg-red-900 dark:border-red-600 dark:text-red-200" },
  { status: "blocked", label: "Blocked", color: "border-amber-300 text-amber-500 dark:border-amber-700 dark:text-amber-400", activeColor: "bg-amber-100 border-amber-400 text-amber-700 dark:bg-amber-900 dark:border-amber-600 dark:text-amber-200" },
];

export function FilterBar({ filters, onFiltersChange, searchInputRef }: FilterBarProps) {
  const hasFilters = filters.search || filters.category !== "All" || filters.statuses.size > 0;

  const toggleStatus = (status: FeatureStatus) => {
    const next = new Set(filters.statuses);
    if (next.has(status)) {
      next.delete(status);
    } else {
      next.add(status);
    }
    onFiltersChange({ ...filters, statuses: next });
  };

  const clearFilters = () => {
    onFiltersChange({ search: "", category: "All", statuses: new Set() });
  };

  return (
    <div className="bg-white dark:bg-slate-800/80 border-b border-slate-200 dark:border-slate-700 px-6 py-2">
      <div className="max-w-screen-2xl mx-auto flex items-center gap-3 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Search features…"
            value={filters.search}
            onChange={(e) => onFiltersChange({ ...filters, search: e.target.value })}
            className="w-full pl-8 pr-3 py-1.5 text-sm border border-slate-200 dark:border-slate-600 rounded-lg
              bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200
              focus:outline-none focus:ring-2 focus:ring-forge-500 focus:border-transparent
              placeholder:text-slate-400 dark:placeholder:text-slate-500
              transition-all duration-200"
          />
        </div>

        {/* Category dropdown */}
        <div className="flex items-center gap-1.5">
          <Filter size={14} className="text-slate-400" />
          <select
            value={filters.category}
            onChange={(e) => onFiltersChange({ ...filters, category: e.target.value })}
            className="text-sm border border-slate-200 dark:border-slate-600 rounded-lg px-2 py-1.5
              bg-slate-50 dark:bg-slate-700 text-slate-700 dark:text-slate-200
              focus:outline-none focus:ring-2 focus:ring-forge-500
              transition-all duration-200 cursor-pointer"
          >
            {CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        </div>

        {/* Status chips */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {STATUS_CHIPS.map((chip) => (
            <button
              key={chip.status}
              type="button"
              onClick={() => toggleStatus(chip.status)}
              className={`px-2.5 py-1 text-[11px] font-medium border rounded-full
                transition-all duration-200 hover:scale-105
                ${filters.statuses.has(chip.status) ? chip.activeColor : chip.color}`}
            >
              {chip.label}
            </button>
          ))}
        </div>

        {/* Clear */}
        {hasFilters && (
          <button
            type="button"
            onClick={clearFilters}
            className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
          >
            <X size={12} />
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
