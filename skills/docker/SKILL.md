# Docker

## When to use this skill
Use when building, debugging, or operating Docker containers and Compose services.

## Protocol
1. **Diagnose before changing** — always run `docker ps` and `docker logs <container>` first.
2. **Build** — use `--no-cache` when debugging to avoid stale layer cache.
3. **Image size** — check after build; flag anything >1GB; use multi-stage builds to reduce.
4. **Debug a failing container** — override entrypoint to get a shell: `docker run --rm -it --entrypoint bash name:tag`
5. **Compose** — use `docker compose` (v2); `docker-compose` (v1) is deprecated.
6. **Secrets** — never pass secrets as `ENV` in Dockerfile; use build args or mounted secrets.

## Commands
```bash
# List running containers
docker ps

# Follow container logs
docker logs --tail 100 -f <container>

# Shell into running container
docker exec -it <container> sh

# Build (no cache)
docker build --no-cache -t name:tag .

# Check image size
docker images name:tag

# Debug failing container
docker run --rm -it --entrypoint bash name:tag

# Compose operations
docker compose up -d
docker compose logs -f <service>
docker compose down -v          # -v removes named volumes
docker compose ps

# Resource usage
docker stats --no-stream

# Clean dangling images + stopped containers
docker system prune -f
```

## Output interpretation
- Container in `Exited (1)` state → check logs with `docker logs`; non-zero exit = error
- `OOMKilled` in `docker inspect` → container ran out of memory; increase `mem_limit`
- `No space left on device` → run `docker system prune -f` to free space
- Build fails at a specific layer → add `--no-cache` to bypass cached layers
- Image size >1GB → use multi-stage build; only copy final artefact into slim base image

Dockerfile best practices:
- Multi-stage: `FROM python:3.12 AS builder` then `FROM python:3.12-slim`
- Non-root user: `RUN useradd -m app && USER app`
- `.dockerignore`: exclude `.git`, `__pycache__`, `*.pyc`, test files
- Pin base image tags: `python:3.12.3-slim` not `python:latest`
- COPY dependency files first (`requirements.txt`), RUN install, then COPY source — maximises layer cache

## Done criteria
- Container starts and passes health check
- Image size is reasonable (< 500MB for most services; < 1GB hard limit)
- No secrets in Dockerfile or image layers
- Compose services restart cleanly with `docker compose down && docker compose up -d`
