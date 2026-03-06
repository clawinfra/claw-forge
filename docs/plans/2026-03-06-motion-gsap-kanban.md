# Motion.dev + GSAP Kanban Animation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance the Kanban UI with purposeful animations using Motion.dev for React component lifecycle transitions and GSAP for numeric DOM tweens — "Functional & Fast" style (animations that aid comprehension, never ornamental).

**Architecture:** Motion.dev (`motion/react`) owns React component boundaries via `AnimatePresence` and `motion.*` elements. GSAP owns numeric DOM value tweening via `useRef` + `useEffect`. The two libraries operate on entirely different surfaces, eliminating conflicts.

**Tech Stack:** React 18, Motion.dev v11 (`motion` package), GSAP 3, TypeScript, Tailwind CSS, @dnd-kit/core

---

### Task 1: Install motion and gsap

**Files:**
- Modify: `ui/package.json`

**Step 1: Install the packages**

```bash
npm --prefix ui install motion gsap
```

**Step 2: Verify build still passes**

```bash
npm --prefix ui run build
```
Expected: Build succeeds with no TypeScript errors.

**Step 3: Commit**

```bash
git -C ui add package.json package-lock.json
git commit -am "chore(ui): add motion and gsap dependencies"
```

---

### Task 2: ProgressBar — GSAP fill tween

Replace CSS `transition-all duration-500` on the fill bar with a GSAP `power2.out` tween. GSAP's easing is more satisfying for progress bars — it starts fast and decelerates.

**Files:**
- Modify: `ui/src/components/ProgressBar.tsx`

**Step 1: Rewrite ProgressBar.tsx**

Replace the entire file contents with:

```tsx
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
```

Key changes:
- Added `useRef<HTMLDivElement>` and `useEffect` with `gsap.to`
- Removed `transition-all duration-500` from the fill div's className
- Initial `style={{ width: "0%" }}` — GSAP takes over from first render

**Step 2: Verify build**

```bash
npm --prefix ui run build
```
Expected: Passes. No TypeScript errors.

**Step 3: Commit**

```bash
git commit -am "feat(ui): GSAP power2.out tween for ProgressBar fill"
```

---

### Task 3: FeatureCard — status badge spring pop

When a card's status changes (e.g. pending→running), the status badge re-mounts with a spring pop. This makes status changes unmissable without being jarring.

**Files:**
- Modify: `ui/src/components/FeatureCard.tsx`

**Step 1: Add motion import at the top of FeatureCard.tsx**

After the existing imports (around line 17), add:
```tsx
import { motion } from "motion/react";
```

**Step 2: Replace the status badge `<span>` with `motion.span`**

Find this block (around line 174–181):
```tsx
<span
  className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
    STATUS_BADGE[feature.status] ?? STATUS_BADGE.pending
  }`}
>
  {isStopping ? "stopping…" : feature.status}
</span>
```

Replace with:
```tsx
<motion.span
  key={isStopping ? "stopping" : feature.status}
  initial={{ scale: 0.8, opacity: 0 }}
  animate={{ scale: 1, opacity: 1 }}
  transition={{ type: "spring", stiffness: 400, damping: 20 }}
  className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
    STATUS_BADGE[feature.status] ?? STATUS_BADGE.pending
  }`}
>
  {isStopping ? "stopping…" : feature.status}
</motion.span>
```

The `key` prop forces React to unmount/remount the element on status change, triggering the `initial` → `animate` spring transition.

**Step 3: Verify build**

```bash
npm --prefix ui run build
```

**Step 4: Commit**

```bash
git commit -am "feat(ui): Motion spring pop on status badge change"
```

---

### Task 4: FeatureCard — enter/exit animation

Wrap the card's root `div` with `motion.div` so cards animate in when appearing in a column and animate out when removed or moved.

**Files:**
- Modify: `ui/src/components/FeatureCard.tsx`

**Step 1: Replace the outer `div` with `motion.div`**

The current outer element (line ~148–167):
```tsx
<div
  ref={setNodeRef}
  onClick={isMobile ? undefined : onClick}
  {...(isMobile ? longPressHandlers : {})}
  {...listeners}
  {...attributes}
  style={{
    transform: CSS.Transform.toString(transform),
    opacity: isDragging ? 0.5 : undefined,
  }}
  className={`group rounded-lg border-l-4 border bg-white dark:bg-slate-800 p-3 shadow-sm
    hover:shadow-md transition-all duration-200 touch-manipulation
    border-slate-200 dark:border-slate-700
    ${isDraggable ? (isDragging ? "cursor-grabbing" : "cursor-grab") : "cursor-pointer"}
    ${STATUS_BORDER[feature.status] ?? STATUS_BORDER.pending}
    ${feature.status === "running" ? "border-r-blue-200 dark:border-r-blue-900" : ""}
    ${feature.status === "failed" ? "border-r-red-200 dark:border-r-red-900" : ""}
    ${showExpanded ? "ring-2 ring-forge-500/50" : ""}
  `}
  data-testid="feature-card"
>
```

Replace with:
```tsx
<motion.div
  ref={setNodeRef}
  onClick={isMobile ? undefined : onClick}
  {...(isMobile ? longPressHandlers : {})}
  {...listeners}
  {...attributes}
  layout
  initial={{ opacity: 0, y: -8 }}
  animate={{ opacity: isDragging ? 0.5 : 1, y: 0 }}
  exit={{ opacity: 0, scale: 0.95 }}
  transition={{ duration: 0.2, ease: "easeOut" }}
  style={{
    transform: CSS.Transform.toString(transform),
  }}
  className={`group rounded-lg border-l-4 border bg-white dark:bg-slate-800 p-3 shadow-sm
    hover:shadow-md transition-shadow duration-200 touch-manipulation
    border-slate-200 dark:border-slate-700
    ${isDraggable ? (isDragging ? "cursor-grabbing" : "cursor-grab") : "cursor-pointer"}
    ${STATUS_BORDER[feature.status] ?? STATUS_BORDER.pending}
    ${feature.status === "running" ? "border-r-blue-200 dark:border-r-blue-900" : ""}
    ${feature.status === "failed" ? "border-r-red-200 dark:border-r-red-900" : ""}
    ${showExpanded ? "ring-2 ring-forge-500/50" : ""}
  `}
  data-testid="feature-card"
>
```

Also replace the closing `</div>` tag at the bottom of the return with `</motion.div>`.

Key changes:
- `motion.div` instead of `div`
- `layout` prop: when a card is removed from above, remaining cards shift smoothly (FLIP technique)
- `initial/animate/exit` for enter/exit lifecycle
- `opacity: isDragging ? 0.5 : 1` moved into Motion's `animate` (was previously in `style`)
- Removed `opacity` from `style` to avoid conflicts with Motion
- Changed `transition-all` to `transition-shadow` to avoid conflicting with Motion's transforms

**Step 2: Verify build**

```bash
npm --prefix ui run build
```

**Step 3: Commit**

```bash
git commit -am "feat(ui): Motion enter/exit/layout animation on FeatureCard"
```

---

### Task 5: App.tsx — AnimatePresence on column card lists + DragOverlay tilt

Wrap each column's `cards.map(...)` with `AnimatePresence` so card exit animations actually run. Add tilt to the DragOverlay ghost card.

**Files:**
- Modify: `ui/src/App.tsx`

**Step 1: Add AnimatePresence import**

Add to the existing React imports at the top of `App.tsx`:
```tsx
import { AnimatePresence, motion } from "motion/react";
```

**Step 2: Wrap `cards.map(...)` in PendingDropColumn with AnimatePresence**

In `PendingDropColumn` component (around line 197–205), find:
```tsx
: cards.map((feature) => (
    <FeatureCard
      key={feature.id}
      feature={feature}
      onClick={() => setSelectedFeatureId(feature.id)}
      onLongPress={(f) => setLongPressFeature(f)}
      implicatedFeatureIds={implicatedFeatureIds}
    />
  ))}
```

Replace with:
```tsx
: (
  <AnimatePresence initial={false}>
    {cards.map((feature) => (
      <FeatureCard
        key={feature.id}
        feature={feature}
        onClick={() => setSelectedFeatureId(feature.id)}
        onLongPress={(f) => setLongPressFeature(f)}
        implicatedFeatureIds={implicatedFeatureIds}
      />
    ))}
  </AnimatePresence>
)}
```

`initial={false}` prevents animating cards already on screen when the component first mounts.

**Step 3: Wrap `cards.map(...)` in KanbanBoard non-pending columns with AnimatePresence**

Around line 837–848, find:
```tsx
: cards.map((feature) => (
    <FeatureCard
      key={feature.id}
      feature={feature}
      onClick={() => setSelectedFeatureId(feature.id)}
      onLongPress={(f) => setLongPressFeature(f)}
      implicatedFeatureIds={implicatedFeatureIds}
      onStop={col.id === "in_progress" ? handleStopTask : undefined}
      isStopping={stoppingTasks.has(feature.id)}
    />
  ))}
```

Replace with:
```tsx
: (
  <AnimatePresence initial={false}>
    {cards.map((feature) => (
      <FeatureCard
        key={feature.id}
        feature={feature}
        onClick={() => setSelectedFeatureId(feature.id)}
        onLongPress={(f) => setLongPressFeature(f)}
        implicatedFeatureIds={implicatedFeatureIds}
        onStop={col.id === "in_progress" ? handleStopTask : undefined}
        isStopping={stoppingTasks.has(feature.id)}
      />
    ))}
  </AnimatePresence>
)}
```

**Step 4: Enhance DragOverlay with motion tilt**

Find the DragOverlay section (around line 866–872):
```tsx
<DragOverlay>
  {activeFeature ? (
    <div className="shadow-xl opacity-90 rounded-lg">
      <FeatureCard feature={activeFeature} />
    </div>
  ) : null}
</DragOverlay>
```

Replace with:
```tsx
<DragOverlay>
  {activeFeature ? (
    <motion.div
      initial={{ scale: 1.02, rotate: 1.5 }}
      animate={{ scale: 1.02, rotate: 1.5 }}
      className="rounded-lg"
      style={{ boxShadow: "0 20px 40px rgba(0,0,0,0.2)" }}
    >
      <FeatureCard feature={activeFeature} />
    </motion.div>
  ) : null}
</DragOverlay>
```

The 1.5° tilt + elevated shadow signals "I'm being carried" without being distracting.

**Step 5: Verify build**

```bash
npm --prefix ui run build
```

**Step 6: Commit**

```bash
git commit -am "feat(ui): AnimatePresence on column card lists + DragOverlay tilt"
```

---

### Task 6: FeatureDetailDrawer — Motion spring slide-in

Replace the CSS `translate-x-full / translate-x-0` toggle with a Motion spring slide from the right. This gives the drawer a physical, weighted feel.

**Files:**
- Modify: `ui/src/components/FeatureDetailDrawer.tsx`

**Step 1: Add Motion imports**

At the top of the file, after existing imports:
```tsx
import { AnimatePresence, motion } from "motion/react";
```

**Step 2: Replace the return block**

Replace the entire `return (...)` block with:

```tsx
return (
  <>
    <AnimatePresence>
      {feature && (
        <motion.div
          key="backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-[80] bg-black/20"
        />
      )}
    </AnimatePresence>

    <AnimatePresence>
      {feature && (
        <motion.div
          key="drawer"
          ref={drawerRef}
          initial={{ x: "100%", opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: "100%", opacity: 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 30, opacity: { duration: 0.2 } }}
          className="fixed top-0 right-0 h-full w-[400px] max-w-[90vw] z-[90]
            bg-white dark:bg-slate-800 shadow-2xl border-l border-slate-200 dark:border-slate-700
            overflow-y-auto"
        >
          <div className="flex flex-col h-full">
            {/* Header */}
            <div className="flex items-start justify-between p-5 border-b border-slate-200 dark:border-slate-700">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <Hash size={14} className="text-slate-400 shrink-0" />
                  <span className="text-xs font-mono text-slate-400 truncate">
                    {feature.id}
                  </span>
                </div>
                <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100 leading-snug">
                  {feature.name}
                </h3>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="ml-2 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300
                  rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all"
              >
                <X size={18} />
              </button>
            </div>

            {/* Body — keep all existing body JSX unchanged from line 151 to the end of the feature content */}
            <div className="flex-1 p-5 space-y-5 overflow-y-auto">
              {/* ... all existing body content stays exactly the same ... */}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  </>
);
```

**IMPORTANT:** The body content between `<div className="flex-1 p-5 space-y-5 overflow-y-auto">` and its closing `</div>` stays exactly as-is from the original file (lines 151–444). Do not change any of that inner content — only the outer structural wrapper changes.

Key changes from original:
- Removed the conditional `${feature ? "translate-x-0" : "translate-x-full"}` class toggling
- Removed `transform transition-transform duration-300 ease-out` classes
- Replaced with `motion.div` inside `AnimatePresence` — drawer only mounts when `feature` is truthy
- Backdrop is now also animated in/out via its own `AnimatePresence`
- The `useEffect` for outside-click detection (`drawerRef`) stays unchanged

**Step 2: Verify build**

```bash
npm --prefix ui run build
```

**Step 3: Commit**

```bash
git commit -am "feat(ui): Motion spring slide for FeatureDetailDrawer"
```

---

### Task 7: CommandPalette — Motion scale+fade appear

Replace the `if (!isOpen) return null` pattern with `AnimatePresence` so the palette animates in/out.

**Files:**
- Modify: `ui/src/components/CommandPalette.tsx`

**Step 1: Add Motion imports**

After existing imports:
```tsx
import { AnimatePresence, motion } from "motion/react";
```

**Step 2: Remove the early return guard**

Delete this line (around line 137):
```tsx
if (!isOpen) return null;
```

**Step 3: Wrap the return JSX with AnimatePresence + motion**

Replace the entire `return (...)` block with:

```tsx
return (
  <AnimatePresence>
    {isOpen && (
      <motion.div
        key="palette"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
        onClick={onClose}
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />

        {/* Panel */}
        <motion.div
          initial={{ scale: 0.96, opacity: 0, y: -8 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.96, opacity: 0, y: -8 }}
          transition={{ duration: 0.15, ease: "easeOut" }}
          className="relative z-10 w-full max-w-xl rounded-2xl bg-white dark:bg-slate-800 shadow-2xl
            border border-slate-200 dark:border-slate-700 overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Search */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-200 dark:border-slate-700">
            <span className="text-slate-400 dark:text-slate-500 text-sm font-mono">⌘</span>
            <input
              ref={inputRef}
              type="text"
              className="flex-1 bg-transparent text-sm text-slate-800 dark:text-slate-100
                placeholder:text-slate-400 dark:placeholder:text-slate-500 outline-none"
              placeholder="Search commands…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={handleKeyDown}
            />
            <button
              type="button"
              onClick={onClose}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
            >
              <X size={16} />
            </button>
          </div>

          {/* Results */}
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-400 dark:text-slate-500">
              No commands found
            </div>
          ) : (
            <ul ref={listRef} className="max-h-80 overflow-y-auto py-1">
              {filtered.map((cmd, idx) => {
                const Icon = ICON_MAP[cmd.icon] ?? Activity;
                const isActive = idx === activeIndex;
                return (
                  <li
                    key={cmd.id}
                    className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors
                      ${isActive
                        ? "bg-slate-100 dark:bg-slate-700"
                        : "hover:bg-slate-50 dark:hover:bg-slate-700/60"
                      }`}
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => {
                      onExecute(cmd);
                      onClose();
                    }}
                  >
                    <Icon
                      size={16}
                      className="shrink-0 text-slate-500 dark:text-slate-400"
                    />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
                        {cmd.label}
                      </span>
                      <span className="ml-2 text-xs text-slate-400 dark:text-slate-500 truncate">
                        {cmd.description}
                      </span>
                    </div>
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold
                        ${CATEGORY_BADGE[cmd.category] ?? "bg-slate-100 text-slate-600"}`}
                    >
                      {cmd.category}
                    </span>
                    {cmd.shortcut && (
                      <kbd className="shrink-0 text-[10px] font-mono bg-slate-100 dark:bg-slate-700
                        text-slate-500 dark:text-slate-400 rounded px-1.5 py-0.5 border
                        border-slate-200 dark:border-slate-600">
                        {cmd.shortcut}
                      </kbd>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {/* Footer hint */}
          <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-700
            flex items-center gap-3 text-[10px] text-slate-400 dark:text-slate-500">
            <span><kbd className="font-mono">↑↓</kbd> navigate</span>
            <span><kbd className="font-mono">↵</kbd> run</span>
            <span><kbd className="font-mono">Esc</kbd> close</span>
          </div>
        </motion.div>
      </motion.div>
    )}
  </AnimatePresence>
);
```

**Step 2: Verify build**

```bash
npm --prefix ui run build
```

**Step 3: Commit**

```bash
git commit -am "feat(ui): Motion scale+fade animation for CommandPalette"
```

---

### Task 8: TaskDetailModal — Motion spring bottom sheet

Replace the CSS `animate-slide-up` class with a Motion spring that gives the bottom sheet a native-feeling bounce.

**Files:**
- Modify: `ui/src/components/TaskDetailModal.tsx`

**Step 1: Add Motion imports**

After existing imports:
```tsx
import { AnimatePresence, motion } from "motion/react";
```

**Step 2: Replace the return block**

Replace the entire `return (...)` block with:

```tsx
return (
  <AnimatePresence>
    {feature && (
      <motion.div
        key="modal-backdrop"
        ref={backdropRef}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[100] bg-black/50 flex items-end sm:items-center justify-center"
        onClick={(e) => {
          if (e.target === backdropRef.current) onClose();
        }}
        data-testid="task-detail-modal"
      >
        <motion.div
          initial={{ y: "100%", opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: "100%", opacity: 0 }}
          transition={{ type: "spring", stiffness: 350, damping: 35, opacity: { duration: 0.15 } }}
          className="bg-white dark:bg-slate-800 w-full sm:max-w-lg sm:rounded-2xl rounded-t-2xl max-h-[85vh] overflow-y-auto shadow-2xl"
        >
          {/* Header */}
          <div className="sticky top-0 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-3 flex items-start justify-between z-10">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_COLOR[feature.status]}`}>
                  {feature.status}
                </span>
                {feature.category && (
                  <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                    {feature.category}
                  </span>
                )}
              </div>
              <h2 className="text-base font-bold text-slate-800 dark:text-slate-100 leading-snug">
                {feature.name}
              </h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="ml-2 p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300
                rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all shrink-0"
            >
              <X size={20} />
            </button>
          </div>

          {/* Body — keep all existing body content unchanged */}
          <div className="px-4 py-4 space-y-4">
            {feature.description && (
              <div>
                <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                  <FileText size={12} />
                  Description
                </h4>
                <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
                  {feature.description}
                </p>
              </div>
            )}

            {feature.steps && feature.steps.length > 0 && (
              <div>
                <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                  <Layers size={12} />
                  Steps ({feature.steps.length})
                </h4>
                <ol className="space-y-1">
                  {feature.steps.map((step, i) => (
                    <li key={i} className="flex gap-2 text-sm text-slate-600 dark:text-slate-300">
                      <span className="text-slate-400 font-mono text-xs shrink-0 mt-0.5">{i + 1}.</span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {feature.error_message && (
              <div>
                <h4 className="flex items-center gap-1.5 text-xs font-semibold text-red-500 uppercase tracking-wider mb-1.5">
                  <AlertCircle size={12} />
                  Error Output
                </h4>
                <pre className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words max-h-48">
                  {feature.error_message}
                </pre>
              </div>
            )}

            <div>
              <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                <Clock size={12} />
                Timeline
              </h4>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500 dark:text-slate-400">Created</span>
                  <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">{formatTime(feature.created_at)}</span>
                </div>
                {feature.started_at && (
                  <div className="flex justify-between">
                    <span className="text-slate-500 dark:text-slate-400">Started</span>
                    <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">{formatTime(feature.started_at)}</span>
                  </div>
                )}
                {feature.completed_at && (
                  <div className="flex justify-between">
                    <span className="text-slate-500 dark:text-slate-400">Completed</span>
                    <span className="text-slate-700 dark:text-slate-300 font-mono text-xs">{formatTime(feature.completed_at)}</span>
                  </div>
                )}
              </div>
            </div>

            {feature.cost_usd > 0 && (
              <div>
                <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                  <Coins size={12} />
                  Cost & Tokens
                </h4>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Input tokens</span>
                    <span className="font-mono text-slate-700 dark:text-slate-300">{feature.input_tokens.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Output tokens</span>
                    <span className="font-mono text-slate-700 dark:text-slate-300">{feature.output_tokens.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between font-medium">
                    <span className="text-slate-600 dark:text-slate-300">Total Cost</span>
                    <span className="font-mono text-slate-800 dark:text-slate-200">${feature.cost_usd.toFixed(4)}</span>
                  </div>
                </div>
              </div>
            )}

            {feature.progress !== undefined && feature.status === "running" && (
              <div>
                <div className="flex justify-between items-center mb-1">
                  <span className="text-xs text-slate-500 dark:text-slate-400 font-semibold uppercase">Progress</span>
                  <span className="text-xs font-mono text-slate-600 dark:text-slate-300">{feature.progress}%</span>
                </div>
                <div className="h-2 w-full rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-blue-500 transition-all duration-300"
                    style={{ width: `${feature.progress}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    )}
  </AnimatePresence>
);
```

**IMPORTANT:** The `if (!feature) return null;` early return guard (line 45) must be **removed** since `AnimatePresence` now handles the conditional rendering. The `feature` check is handled by `{feature && (` inside `AnimatePresence`.

**Step 2: Verify build**

```bash
npm --prefix ui run build
```

**Step 3: Commit**

```bash
git commit -am "feat(ui): Motion spring bottom sheet for TaskDetailModal"
```

---

### Task 9: App.tsx — GSAP agent count counter

When the number of running agents changes, the header counter animates through intermediate values rather than jumping.

**Files:**
- Modify: `ui/src/App.tsx`

**Step 1: Add gsap import**

Add to the imports in `App.tsx`:
```tsx
import { gsap } from "gsap";
```

**Step 2: Add counter state and ref in KanbanBoard**

After the `const summary = useSummary(allFeatures);` line (around line 473), add:
```tsx
const agentCountRef = useRef<HTMLSpanElement>(null);
const displayedRunningRef = useRef(summary.running);
```

**Step 3: Add the GSAP counter effect**

After the ref declarations, add:
```tsx
useEffect(() => {
  const obj = { val: displayedRunningRef.current };
  gsap.to(obj, {
    val: summary.running,
    duration: 0.4,
    ease: "power1.out",
    snap: { val: 1 },
    onUpdate: () => {
      if (agentCountRef.current) {
        agentCountRef.current.textContent = String(Math.round(obj.val));
      }
      displayedRunningRef.current = Math.round(obj.val);
    },
  });
}, [summary.running]);
```

**Step 4: Attach the ref to the agent count span**

Find the agent count display in the header (around line 586–589):
```tsx
<span className="text-slate-600 dark:text-slate-300 font-medium">
  {summary.running} agent{summary.running !== 1 ? "s" : ""} live
</span>
```

Replace with:
```tsx
<span className="text-slate-600 dark:text-slate-300 font-medium">
  <span ref={agentCountRef}>{summary.running}</span>
  {" "}agent{summary.running !== 1 ? "s" : ""} live
</span>
```

Note: The plural suffix (`agent` vs `agents`) won't animate with the number, but this is intentional — it would be disruptive to have the text jump mid-tween. The count itself is what matters.

**Step 5: Verify build**

```bash
npm --prefix ui run build
```

**Step 6: Commit**

```bash
git commit -am "feat(ui): GSAP counter animation for running agent count"
```

---

### Task 10: Clean up replaced CSS

Remove the `animate-slide-up` keyframe and class from `index.css` since `TaskDetailModal` no longer uses it.

**Files:**
- Modify: `ui/src/index.css`

**Step 1: Remove the slide-up animation block**

Find and remove these lines (around lines 107–120):
```css
/* Slide up for modal (mobile bottom sheet) */
@keyframes slide-up {
  from {
    transform: translateY(100%);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}
.animate-slide-up {
  animation: slide-up 0.3s ease-out;
}
```

Keep all other keyframes — `mascot-glow`, `confetti-*`, `celebration-pop`, `fab-expand`, `fade-in`, `slide-in-right` are all still in use.

**Step 2: Verify build**

```bash
npm --prefix ui run build
```

**Step 3: Verify no references to animate-slide-up remain**

```bash
grep -r "animate-slide-up" ui/src/
```
Expected: No output (zero matches).

**Step 4: Commit**

```bash
git commit -am "chore(ui): remove animate-slide-up CSS (replaced by Motion spring)"
```

---

## Verification Checklist

After all tasks complete, verify the full build and run the dev server:

```bash
npm --prefix ui run build
# Expected: Build succeeds, no TypeScript errors

npm --prefix ui run dev
# Then open http://localhost:5173 and verify:
# ✓ Cards animate in with fade+slide when they appear in columns
# ✓ Cards animate out with fade+scale when moved/removed
# ✓ Status badges spring-pop when status changes (pending→running→completed)
# ✓ DragOverlay tilts 1.5° with elevated shadow when dragging
# ✓ FeatureDetailDrawer springs in from the right
# ✓ CommandPalette scales up from center (⌘K)
# ✓ TaskDetailModal springs up from bottom (long-press on mobile)
# ✓ ProgressBar fill tweens smoothly with power2.out
# ✓ Agent count counter animates through values when agents start/finish
```

Final commit after verification:
```bash
git commit -am "feat(ui): Motion.dev + GSAP animation enhancement complete"
```
