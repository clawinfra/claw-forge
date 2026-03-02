# Go LSP — gopls

## What this skill does
Provides type checking, vet diagnostics, and static analysis for Go projects via `go vet` and `gopls`.

## Installation check
```bash
gopls version
```
If not installed:
```bash
go install golang.org/x/tools/gopls@latest
# Also install staticcheck for deeper analysis
go install honnef.co/go/tools/cmd/staticcheck@latest
```

## Type checking / diagnostics
```bash
# Primary: fast compilation + vet checks (run this first)
go vet ./...

# Full build to catch all type errors (stop-at-first-error by default)
go build ./...

# Build without stopping at first error
go build -gcflags="-e" ./...

# gopls diagnostics for a specific file
gopls check ./path/to/file.go

# Deep static analysis (optional, slower)
staticcheck ./...
```
Output means:
- `error:` → must fix before committing (compilation failure)
- `warning:` / `vet:` → review but non-blocking
- `note:` → informational

## Key flags
| Flag | Purpose |
|------|---------|
| `go vet ./...` | Run all vet analysers on entire module |
| `go build -gcflags="-e"` | Report all errors, not just the first |
| `gopls check ./...` | LSP diagnostics without an editor |
| `staticcheck -checks=all ./...` | All available static analysis checks |
| `go test -vet=all ./...` | Run vet as part of test suite |

## Config file
`go.mod` — defines the module and dependencies:
```
module github.com/org/repo

go 1.21

require (
    golang.org/x/tools v0.16.0
)
```

`gopls` settings live in `.gopls/settings.json` or in editor config. For CLI use, no config file is needed.

## Common errors and fixes
| Error | Cause | Fix |
|-------|-------|-----|
| `undefined: X` | Missing import or typo | Add `import` or fix identifier |
| `cannot use X (type A) as type B` | Type mismatch | Fix type, add conversion, or update signature |
| `imported and not used` | Unused import | Remove the import |
| `declared but not used` | Unused variable | Use or remove the variable |
| `go.sum out of date` | Dependency added without `go mod tidy` | Run `go mod tidy` |
| `package X is not in GOROOT` | Module not downloaded | Run `go mod download` |

## Integration with agent workflow
1. After writing or modifying `.go` files, run `go vet ./...` — fastest check.
2. Run `go build ./...` to confirm compilation. Use `-gcflags="-e"` to see all errors at once.
3. Fix all compilation errors and vet issues before committing.
4. Optionally run `staticcheck ./...` for deeper analysis — treat its output as warnings.
5. Run `go test ./...` to ensure tests still pass.
