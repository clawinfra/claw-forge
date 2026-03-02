# TypeScript LSP — tsc

## What this skill does
Runs TypeScript's compiler for type checking across `.ts`, `.tsx`, `.js`, and `.jsx` files without emitting output.

## Installation check
```bash
tsc --version
```
If not installed:
```bash
# Global install
npm install -g typescript

# Or use project-local (preferred)
npm install --save-dev typescript
npx tsc --version
```

## Type checking / diagnostics
```bash
# Type-check only — no output files written (preferred)
npx tsc --noEmit

# With strict mode enabled (even if not in tsconfig.json)
npx tsc --noEmit --strict

# Check a specific file (no tsconfig needed)
npx tsc --noEmit --strict path/to/file.ts

# Watch mode for continuous checking
npx tsc --noEmit --watch
```
Output means:
- `error TS<code>:` → must fix before committing
- `warning:` → review but non-blocking
- `note:` → informational

## Key flags
| Flag | Purpose |
|------|---------|
| `--noEmit` | Type-check only, write no `.js` files |
| `--strict` | Enable all strict checks (recommended) |
| `--skipLibCheck` | Skip type checking of `.d.ts` files (faster) |
| `--incremental` | Cache results for faster subsequent checks |
| `--project <path>` | Specify path to `tsconfig.json` |
| `--listFiles` | Show all files included in compilation |

## Config file
`tsconfig.json` — place in project root:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "outDir": "./dist",
    "rootDir": "./src"
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}
```

## Common errors and fixes
| Error | Cause | Fix |
|-------|-------|-----|
| `Cannot find module 'X'` | Package not installed or missing types | `npm install X` and/or `npm install @types/X` |
| `implicitly has an 'any' type` | Missing type annotation with strict on | Add explicit type annotation |
| `not assignable to parameter of type` | Type mismatch | Fix the type, add narrowing, or use `as` cast |
| `Object is possibly 'undefined'` | Optional chaining or null check missing | Add `?.` or nullish check `if (x !== undefined)` |
| `Property 'X' does not exist on type` | Typo or missing interface field | Fix name or add field to interface |
| `Could not find declaration file for 'X'` | Missing `@types` package | `npm install --save-dev @types/X` |

## Integration with agent workflow
1. After writing or modifying `.ts`/`.tsx`/`.js`/`.jsx` files, run `npx tsc --noEmit`.
2. Fix all `error TS<code>:` items before committing.
3. Use `--strict` for new projects; match existing tsconfig settings for existing projects.
4. For CI, add `tsc --noEmit` as a build step — zero-exit on clean, non-zero on errors.
