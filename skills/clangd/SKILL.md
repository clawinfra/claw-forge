# C/C++ LSP — clangd

## What this skill does
Provides compiler-accurate diagnostics for C/C++ files using the same clang frontend as the build.

## Installation check
```bash
clangd --version
```
If not installed:
```bash
# Ubuntu/Debian
sudo apt install clangd

# macOS
brew install llvm
# Add to PATH: export PATH="$(brew --prefix llvm)/bin:$PATH"
```

## Type checking / diagnostics
```bash
# Check a single file (outputs diagnostics to stderr)
clangd --check=path/to/file.cpp

# With verbose output
clangd --check=path/to/file.cpp --log=verbose
```
Output means:
- `error:` → must fix before committing
- `warning:` → review but non-blocking
- `note:` → informational (context for above diagnostic)

## Key flags
| Flag | Purpose |
|------|---------|
| `--check=<file>` | Run diagnostics on a single file and exit |
| `--log=verbose` | Show detailed processing steps |
| `--compile-commands-dir=<dir>` | Override location of `compile_commands.json` |
| `--query-driver=<glob>` | Allow clangd to query a cross-compiler for system headers |

## Config file
`.clangd` — YAML file in project root:
```yaml
CompileFlags:
  Add: [-Wall, -Wextra, -std=c++17]
  Remove: [-W*]           # strip noisy flags from compile_commands.json
Diagnostics:
  ClangTidy:
    Add: [modernize-*, readability-*]
    Remove: [modernize-use-trailing-return-type]
```

`compile_commands.json` — **#1 requirement** — tells clangd how the project is built:
```bash
# Generate with CMake
cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -B build .
cp build/compile_commands.json .

# Generate with Bear (any build system)
bear -- make
```

## Common errors and fixes
| Error | Cause | Fix |
|-------|-------|-----|
| `file not found` for includes | Missing `compile_commands.json` | Generate via cmake or bear (see above) |
| `unknown type name` | Missing `#include` | Add the appropriate header |
| `too few arguments` | Wrong function signature | Check prototype vs call site |
| `redefinition of` | Header included twice | Add `#pragma once` or include guards |
| `no member named 'X'` | Typo or wrong type | Verify struct/class definition |

## Integration with agent workflow
1. **First**: ensure `compile_commands.json` exists in the project root — without it, clangd cannot find headers and will report false errors.
2. Run `clangd --check=<file>` on each modified `.c`, `.cpp`, `.cc`, `.h`, or `.hpp` file.
3. Fix all `error:` lines before committing. `warning:` items should be reviewed.
4. For whole-project checks, pipe all source files: `find src -name '*.cpp' | xargs -I{} clangd --check={}`.
