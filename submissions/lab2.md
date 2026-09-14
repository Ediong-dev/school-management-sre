markdown
# Lab 2 — Containerization: Audit and Optimize

**Date:** 2026-09-14
**Baseline:** tag `lab1-complete`

## Image Sizes (before and after)

| Service | Disk Usage | Content Size | Notes |
|---------|-----------|--------------|-------|
| auth | 271 MB | 65.1 MB | cryptography pulls C extensions |
| academics | 244 MB | 58.7 MB | No crypto, smallest |
| dashboard | 246 MB | 59.2 MB | httpx |
| gateway | 246 MB | 59.2 MB | httpx |

After the security changes, sizes remained essentially the same. **This was expected** — the security improvements don't shrink images, they harden them. Multi-stage builds already did the size work in Lab 0.

## Layer Audit (auth)
87.5 MB Debian trixie base
13.2 MB ca-certificates, netbase, tzdata
41.4 MB Python 3.12 built from source
64.3 MB pip install layer (cryptography + friends)
12.3 kB main.py

text

**Observation:** The `pip install` layer is the largest after the base image. The multi-stage build correctly excludes build tools (gcc, g++, libssl-dev) from the runtime.

## Security Findings

### Finding 1 — Container ran as root
Before: `docker exec school-auth whoami` → `root`, uid 0, gid 0.
After: `app`, uid 10001, gid 10001.

### Finding 2 — `main.py` was world-writable
Before: mode `-rw-rw-rw-` (666).
After: mode `-r--r--r--` (444), owned by `app:app`.

### Finding 3 — No `.dockerignore`
Before: entire build context sent to Docker daemon.
After: `.dockerignore` per service excludes `__pycache__`, `.venv`, `.git`, `*.pyc`, `Dockerfile`.

### What was already good
- Multi-stage build correctly excluded build tools
- Minimal runtime package set (`pip list` showed 8 packages)
- No `curl`, `ps`, `ip` — minimal attack surface
- Debian trixie base (smaller than Ubuntu)

## Dockerfile Changes

```dockerfile
# Before
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY main.py .
ENV PATH=/root/.local/bin:$PATH
EXPOSE 3001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3001"]
dockerfile
# After
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
RUN groupadd -r -g 10001 app && useradd -r -g app -u 10001 -d /home/app -m app
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=app:app --chmod=0444 main.py .
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/usr/local/bin:$PATH
USER app
EXPOSE 3001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3001"]
Incident — Orphan Container from Lab 1
Summary
After rebuilding images with the security improvements, docker compose up -d failed with:

text
Bind for 0.0.0.0:3002 failed: port is already allocated
Root Cause
A manually-run container school-academics-slow from Lab 1 Experiment 5 was still alive, holding port 3002. The docker rm command in Lab 1's log appeared to succeed, but the container had been recreated by a later docker compose up -d academics call (or was never fully removed).

The chain:

Lab 1 E5 ran docker run -d --name school-academics-slow ...

Cleanup commands ran, but the container persisted (or was recreated)

docker compose down only manages Compose-created containers, not manual ones

docker compose up -d tried to bind port 3002, hit the orphan, silently failed to recreate academics

Subsequent health checks: dashboard returned {"detail":"Upstream unavailable: "} — empty error because httpx couldn't connect

Detection
Port conflict error during docker compose up

Symptom: empty upstream error from dashboard

Confirmed via docker ps -a --filter "name=school-" — orphan visible

Resolution
bash
docker compose down -v --remove-orphans
docker rm -f $(docker ps -aq --filter "name=school-")
docker network rm school-management-sre_school-net
docker compose up -d --force-recreate
Prevention
Never manually docker run containers in a Compose-managed project

Use docker compose run for one-off containers, which Compose tracks

Before starting a new lab, always docker compose down --remove-orphans

Verification is not optional: every deploy needs a smoke test

Definition of "Configuration Drift"
The desired state (docker-compose.yaml) said one academics on port 3002.
The actual state (Docker daemon) had two containers competing for that port.
Compose could not reconcile because it only manages containers it created.

This is exactly the class of problem Kubernetes solves. K8s reconciliation continuously compares desired state to actual state and converges — it would have deleted the orphan automatically. We'll see this in Lab 4.

Verification
Check	Command	Result
Non-root user	docker exec school-auth whoami	app
Fixed UID/GID	docker exec school-auth id	uid=10001 gid=10001
Read-only code	docker exec school-auth ls -la /app	-r--r--r-- app:app
Full chain	curl .../api/dashboard/admin/overview	{"total_students":5,...}
Login	curl -X POST .../api/auth/login	Valid JWT, role=admin
Takeaways
Container size is not the only metric. The security changes didn't shrink images. The attack surface shrank. That matters more.

--chmod and --chown on COPY are underused. They replace runtime chmod/chown RUN steps and keep the image smaller.

PYTHONUNBUFFERED=1 matters for observability. Without it, logs buffer and you can't debug live. This will pay off in Lab 3.

Manual docker run inside a Compose project causes drift. Avoid it. Or clean up exhaustively.

Compose is not convergent. It doesn't reconcile. Kubernetes does. This is the reason Lab 4 exists.