# Git Workflow

## When to use this skill
Use when creating branches, writing commits, rebasing, resolving conflicts, or preparing a pull request.

## Protocol
1. **Understand current state first** — run `git status` and `git log --oneline -10` before doing anything.
2. **Feature branches** — always branch from `main`: `git checkout -b feat/short-description`.
3. **Atomic commits** — one logical change per commit; never mix refactor + feature + bug fix in one commit.
4. **Commit message format**: `type: short description (≤72 chars)`
   - Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
   - Example: `feat: add retry logic for 5xx responses`
5. **Before opening a PR** — rebase interactively to clean up WIP commits: `git rebase -i main`
6. **Conflict resolution** — list conflicts with `git diff --diff-filter=U`; resolve each file; `git add <file>`; continue.

## Commands
```bash
# See current state
git status
git log --oneline -10

# Create feature branch
git checkout -b feat/description

# Stage and commit
git add -p                          # interactive staging
git commit -m "feat: description"

# Undo last commit (keep changes staged)
git reset --soft HEAD~1

# Discard all local changes
git checkout -- .

# Interactive rebase (squash WIP commits)
git rebase -i main

# See what changed vs main
git diff main...HEAD --stat
git diff main...HEAD

# Find when a bug was introduced
git bisect start
git bisect bad HEAD
git bisect good <known-good-hash>   # then test each commit git bisect marks

# List conflicted files
git diff --diff-filter=U --name-only
```

## Output interpretation
- `Your branch is ahead of 'origin/main' by N commits` → changes not pushed yet; push when ready
- `CONFLICT (content): Merge conflict in <file>` → open file, resolve `<<<<<<<` markers, then `git add`
- `error: failed to push some refs` → remote has newer commits; `git pull --rebase` then push
- `detached HEAD` → you're not on a branch; `git checkout -b new-branch` to recover

Rules:
- Never `git push --force` on a shared branch (only allowed on your own feature branch)
- Never commit directly to `main`
- Never commit `.env` files — add to `.gitignore` immediately
- `git stash` before switching branches with uncommitted changes

## Done criteria
- Branch name follows `type/description` convention
- Commit history is clean (no "WIP", "fix typo", "asdf" commits in final PR)
- `git diff main...HEAD --stat` shows only intended changes
- No `.env` or secret files in the diff
