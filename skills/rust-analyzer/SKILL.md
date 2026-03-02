# Rust LSP — rust-analyzer

## What this skill does
Provides fast incremental type checking and lint diagnostics for Rust projects via `cargo check` and `cargo clippy`.

## Installation check
```bash
rust-analyzer --version
```
If not installed:
```bash
rustup component add rust-analyzer
# Also ensure clippy is available
rustup component add clippy
```

## Type checking / diagnostics
```bash
# Fast type check — does NOT produce binaries, much faster than build
cargo check 2>&1

# Lint check — type check + clippy lints, treat warnings as errors
cargo clippy -- -D warnings 2>&1

# Check all targets (tests, examples, benchmarks)
cargo check --all-targets 2>&1

# rust-analyzer single-file diagnostics (if needed)
rust-analyzer diagnostics path/to/file.rs
```
Output means:
- `error[EXXXX]:` → must fix before committing
- `warning:` → review but non-blocking (clippy `-D warnings` promotes to error)
- `note:` → informational context

## Key flags
| Flag | Purpose |
|------|---------|
| `cargo check` | Type-check only — fastest, no binary output |
| `cargo check --all-targets` | Include test and bench targets |
| `cargo clippy -- -D warnings` | Lints as errors (CI-safe) |
| `cargo clippy --fix` | Auto-apply clippy suggestions |
| `cargo check --message-format=json` | Machine-readable JSON output |
| `RUSTFLAGS="-D warnings" cargo check` | All warnings as errors via env |

## Config file
`Cargo.toml` — workspace and dependency manifest:
```toml
[package]
name = "my-crate"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }

[workspace]
members = ["crates/*"]
```

`rust-analyzer` settings live in `.cargo/config.toml` or editor config. For CLI use no extra config is needed.

## Common errors and fixes
| Error | Cause | Fix |
|-------|-------|-----|
| `E0308: mismatched types` | Type mismatch | Fix type annotation or conversion |
| `E0382: use of moved value` | Use after move | Clone, borrow (`&`), or restructure ownership |
| `E0502: cannot borrow as mutable` | Borrow conflict | Separate mutable and immutable borrows |
| `E0277: trait bound not satisfied` | Missing `impl` | Derive or implement the required trait |
| `E0433: failed to resolve` | Missing import | Add `use crate::...` or `extern crate` |
| `unused import` (warning) | Dead `use` statement | Remove or prefix with `_` |

## Integration with agent workflow
1. After writing or modifying `.rs` files, run `cargo check 2>&1` — fastest feedback loop.
2. Before committing, run `cargo clippy -- -D warnings 2>&1` to catch lint issues.
3. Fix all `error[EXXXX]` lines. Address `warning:` items from clippy.
4. Use `cargo check --message-format=json` for machine-readable output when parsing programmatically.
5. Run `cargo test` before declaring complete.
