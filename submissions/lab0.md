# Lab 0 — Scaffold and Baseline

**Date:** 2026-09-13
**Environment:** GitHub Codespaces (4-core, 8 GB RAM), Ubuntu 22.04, Docker-in-Docker

## Architecture

Four services + Docker bridge network:

| Service     | Port | Responsibility                          | Depends on        |
|-------------|------|-----------------------------------------|-------------------|
| gateway     | 3000 | Front door, request routing             | auth, academics, dashboard |
| auth        | 3001 | Login, JWT issuance, role claims        | —                 |
| academics   | 3002 | Students, teachers, classes, sections   | —                 |
| dashboard   | 3003 | Role-specific aggregated views          | auth, academics   |

## Environment as Code

- `.devcontainer/devcontainer.json` pins the base image and features (Docker-in-Docker, Python 3.12, kubectl, Helm)
- `.devcontainer/setup.sh` installs k3d, ArgoCD CLI, Argo Rollouts plugin, apache2-utils (ab)
- Git LFS is installed via setup to prevent pre-push hook failures

## Services

Each service:
- Uses FastAPI + uvicorn
- Exposes `/health` for liveness checks
- Exposes `/metrics` via `prometheus-fastapi-instrumentator`
- Injects failures via environment variables (for Labs 1, 6, 8)
- Uses a multi-stage Dockerfile (builder for pip deps, slim runtime)

## Verified Behaviors

- `docker compose ps` → 4 containers running
- All four `/health` endpoints return `{"status":"ok"}`
- `curl http://localhost:3000/api/dashboard/admin/overview` returns `{"total_students":5,"total_teachers":3,"total_sections":3,"total_classes":3}`
- `curl -X POST http://localhost:3000/api/auth/login?...` returns a valid JWT with role claim
- Prometheus metrics exported on all four `/metrics` endpoints

## Incidents

### Incident 1 — Broken `hey` install (silent failure)
`curl -sL` downloaded a "Not Found" HTML page and the setup script moved it to `/usr/local/bin/hey` and marked it executable. Only caught by running the tool.

**Fix:** Switched to `apache2-utils` (`ab`), which ships with Ubuntu.
**Lesson:** `curl -s` silences errors. Verify every tool after install.

### Incident 2 — Git LFS hook blocked push
Codespace had a pre-push hook installed by default, but the `git-lfs` binary wasn't present. Hook exited non-zero on every push.

**Fix:** `apt install git-lfs`. Added to setup.sh.
**Lesson:** The error pointed at the hook; the root cause was the missing binary the hook depends on.

## Next

Lab 1: SRE philosophy — break the system systematically, map the blast radius.