# Performance

## When to use this skill
Use when a function, endpoint, or query is slow — profile first, then optimize with evidence.

## Protocol
1. **Measure first** — establish a baseline before touching any code. Record: wall time, CPU time, memory.
2. **Profile** — find where the time is actually spent (not where you think it is):
   - Python: `cProfile` or `py-spy` for live processes
   - Go: `go test -bench=. -cpuprofile=cpu.prof`
   - Node: `--inspect` flag + Chrome DevTools Performance tab
   - HTTP: `ab` or `k6` for endpoint throughput
3. **Find the hotspot** — look for functions consuming >10% of total time. That's your target.
4. **Optimize in priority order**:
   1. Algorithmic: O(n²) → O(n log n) (biggest wins)
   2. Data structure: list → set for membership tests
   3. I/O batching: 100 DB calls → 1 batch call
   4. Caching: last resort; adds complexity and staleness risk
5. **Verify** — re-run the same benchmark after optimizing. Confirm improvement. Check for regressions.
6. **Document** — write a comment explaining what was optimized and why.

## Commands
```bash
# Python: profile a script
python -m cProfile -s cumulative script.py | head -30

# Python: save and inspect profile
python -m cProfile -s cumulative -o prof.out script.py
python -m pstats prof.out   # then type "sort cumtime" + "stats 20"

# Python: memory profiling
pip install memory-profiler
python -m memory_profiler script.py

# Go: benchmark
go test -bench=. -benchmem ./...
go test -bench=. -cpuprofile=cpu.prof ./...
go tool pprof cpu.prof

# Rust: benchmark
cargo bench

# HTTP load test (Apache bench)
ab -n 1000 -c 10 http://localhost:8080/endpoint

# HTTP load test (k6, more flexible)
k6 run --vus 10 --duration 30s script.js
```

## Output interpretation
- `cumtime` in cProfile → total time including sub-calls; your real bottleneck shows here
- `tottime` → time spent only in that function; helps identify tight loops
- `p50/p95/p99 latency` from load test → p99 being 10× p50 means outliers; investigate GC or I/O spikes
- Memory growing over time → check for unbounded caches or collections that never clear
- Go pprof flame graph: wide bars = hot functions; tall bars = deep call stacks

Rules:
- Never optimize without a measured baseline
- Always benchmark after optimization — confirm the improvement is real
- Document every optimization: what changed, what the before/after numbers were
- Premature optimization is the root of all evil — only optimize proven bottlenecks

## Done criteria
- Baseline benchmark recorded before any change
- Profile identifies the specific hotspot that was optimized
- After-optimization benchmark shows measurable improvement
- No regressions in test suite
- Change is documented with before/after numbers
