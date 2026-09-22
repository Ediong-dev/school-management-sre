# School Management System — An SRE Portfolio Project

> A 4-service microservices system that was **built to be operated**, observed
> under failure, and documented through 35+ real incidents. Not a tutorial
> clone — a production-shaped system with SLOs, GitOps, canary deployments,
> chaos engineering, and disaster recovery drills.

**Tags:** `lab0-complete` → `lab10-complete`
**Author:** Senyene Udoh
**Period:** 7 days of active development

---

## What This Demonstrates

Most portfolio projects stop at "it works." This one starts there and asks
*"what happens when it doesn't?"*

Over seven days of building and operating, this project accumulated:

- **11 tagged releases** — one per lab in a self-directed SRE curriculum
- **35+ documented incidents** — real failures, real root causes, real fixes
- **3 formal chaos experiments** — two of which falsified their own hypotheses
- **10 lab write-ups** — the narrative of what broke and why
- **All four DORA metrics at Elite tier** — deployment frequency, lead time,
  change failure rate, MTTR
- **A cluster destroyed and rebuilt from Git three times** — 15 minutes each,
  zero manual configuration

The distinction that matters: **this system was operated, not just built.**
Every SLO, every alert, every runbook, and every postmortem in this repository
was created in response to a real problem.

---

## At a Glance

| Metric | Value |
|--------|-------|
| Services | 4 (gateway, auth, academics, dashboard) |
| Language | Python 3.12, FastAPI |
| Orchestrator | Kubernetes (k3d) |
| Database | PostgreSQL 16, StatefulSet + PVC |
| GitOps | ArgoCD with automated sync, self-heal, prune |
| Progressive delivery | Argo Rollouts (canary with Prometheus analysis) |
| Observability | Prometheus, Grafana, Alertmanager |
| CI/CD | GitHub Actions → ghcr.io → GitOps overlay commit |
| SLOs | 99.9% availability, 99% latency P95 < 500ms |
| Deployment frequency | 11.3 per day |
| Lead time for changes | 55 seconds |
| Change failure rate | 5.3% |
| Mean time to recovery | 7 minutes median |

---

## Architecture

```
Browser → localhost:4000
  ↓
k3d load balancer (host port 4000 → cluster NodePort 30000)
  ↓
gateway-stable Service (Argo Rollout) → 4 gateway pods
  ↓
  ├─→ auth Service → 2 auth pods → PostgreSQL
  ├─→ academics Service → 2 academics pods
  └─→ dashboard Service → 2 dashboard pods → academics (4 sequential calls)
```

Each service is independently deployable, horizontally scalable, and observed
via Prometheus ServiceMonitors. The gateway is managed by Argo Rollouts with a
canary strategy that automatically aborts on Prometheus-detected SLO violations.

**Data flow example:** the dashboard's `/admin/overview` endpoint makes four
sequential calls to academics (`/students`, `/teachers`, `/sections`, `/classes`).
This design choice is the system's primary capacity bottleneck — see
[Capacity Findings](#capacity-findings).

---

## Service Level Objectives

Defined in `monitoring/slos/school-slo.md`, implemented as PrometheusRule CRDs.

| SLI | Target | Error Budget (30 days) |
|-----|--------|------------------------|
| Availability (all services) | 99.9% | 43m 12s |
| Latency P95 < 500ms | 99% | 7h 12m |

Alerts fire on **SLO burn rate**, not raw thresholds:

- `SchoolSLOFastBurn` — 14.4× sustainable rate (exhausts budget in ~2 days)
- `SchoolSLOSlowBurn` — 6× sustainable rate (exhausts budget in ~5 days)
- `SchoolHighLatencyP95` — P95 > 500ms for 10 minutes

All SLO alerts route to a Discord channel via AlertmanagerConfig. Non-actionable
alerts route to a `null` receiver — a lesson learned from a real alert-fatigue
incident in Lab 6.

---

## Selected Incidents

Every incident is documented in full with root cause, timeline, and fix. These
are the stories that shaped the project.

### The orphan container that taught us why GitOps exists

A container started manually in Lab 1 survived `docker compose down`. It held
port 3002 silently for hours, breaking every subsequent deploy. **Docker Compose
doesn't reconcile state it didn't create.** This incident directly motivated
the entire GitOps chapter (Lab 5).

### The ConfigMap that didn't roll pods

Changing a ConfigMap value and applying it via GitOps reported `Synced`, but
pods kept serving the old value. **Kubernetes reads env vars at container start
and doesn't watch for changes.** The fix — Kustomize's `configMapGenerator`
with content-hash suffixes — is now a standard part of the deployment pattern.

### The alert that fired but didn't reach Discord

During the Lab 6 SLO burn drill, the alert transitioned to `firing` in
Prometheus — but no message arrived in Discord. **The Prometheus Operator
auto-injects a `namespace` matcher for multi-tenancy, but doesn't auto-inject
the label onto alerts.** Every alert rule now carries an explicit
`namespace: school` label.

### The canary that kept promoting bad deployments

Six consecutive attempts to demo an auto-aborting canary all succeeded — each
one promoting a version that was intentionally broken. The root cause took
five iterations to find: **basic canary mode in Argo Rollouts doesn't route
user traffic to the canary.** The canary Service exists but receives no traffic
without a routing provider (Istio, SMI, NGINX ingress). The demo required
synthetic traffic to the canary Service.

### The backup CronJob that backed up the broken database

During the Lab 9 disaster drill, we dropped the `users` table. The CronJob —
running every 2 minutes — continued faithfully backing up the broken database.
Within 10 minutes, three good backups had been rotated out and replaced by
three corrupt ones. **Backups are only as good as the data in them.** Production
systems require pre-backup validation and file-size monitoring.

### The 200-user load test that found the capacity limit

The load tests revealed that everything holds under load *except* the dashboard
endpoint, which fails at 29% error rate under saturation. The failure signature
is exactly what was predicted in the very first week's chaos experiment:
sequential calls to a downstream dependency hitting a gateway timeout.

---

## Capacity Findings

Full analysis in [`docs/reliability/capacity-analysis.md`](docs/reliability/capacity-analysis.md).

| Concurrent users | Throughput | Failures | Median | P95 |
|------------------|-----------|----------|--------|-----|
| 10 | 9.73 req/s | 0% | 26 ms | 97 ms |
| 50 | 40.05 req/s | 0% | 52 ms | 550 ms |
| **200** | **49.19 req/s** | **13.91%** | **430 ms** | **6400 ms** |

**Breaking point: between 50 and 200 concurrent users.**

The bottleneck is specific. Under saturation, `/api/dashboard/admin/overview`
fails at 29% because it makes 4 sequential calls to academics, each blocking
the next, until the gateway's 10-second timeout fires. All other endpoints —
including auth login with pgcrypto password hashing — held under the same load.

**Fix identified:** parallelize with `asyncio.gather` and add a short-TTL cache.
The fix is documented but not yet implemented — leaving it as a concrete "next
step" for the repo.

---

## Repository Structure

```
.
├── services/               # 4 FastAPI microservices
│   ├── gateway/            # Front door, request routing, timeout budget
│   ├── auth/               # Login, JWT, role-based access
│   ├── academics/          # Students, teachers, classes, sections
│   └── dashboard/          # Role-specific aggregated views
├── k8s/
│   ├── base/               # Environment-agnostic manifests
│   └── overlays/gitops/    # Image tags set by CI
├── monitoring/
│   ├── prometheus/         # Scrape configs, SLI recording rules
│   ├── grafana/            # Golden Signals dashboard (as code)
│   └── slos/               # SLO definitions
├── docs/
│   ├── chaos-experiments/  # 3 formal experiments with hypotheses
│   ├── postmortems/        # Blameless postmortems
│   ├── reliability/        # DORA metrics, capacity, final review
│   └── runbooks/           # Alert-specific operational procedures
├── submissions/            # 10 lab write-ups (the narrative)
├── load-testing/           # Locust scripts and Job manifest
├── scripts/
│   └── bootstrap.sh        # Rebuild the cluster from Git in one command
└── .devcontainer/          # Reproducible environment (Codespaces)
```

**Start here for the story:** [`docs/reliability/reliability-review.md`](docs/reliability/reliability-review.md)
**Start here for the incidents:** [`submissions/`](submissions/)
**Start here for the deep dives:** [`docs/chaos-experiments/`](docs/chaos-experiments/)

---

## Getting Started

### Prerequisites

- Docker Desktop (or any Docker daemon) with 6 GB RAM available
- `k3d` — [install](https://k3d.io/#installation)
- `kubectl` — [install](https://kubernetes.io/docs/tasks/tools/)
- `helm` — [install](https://helm.sh/docs/intro/install/)
- `argocd` CLI — [install](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- `git`

Verify:

```bash
docker --version && k3d version && kubectl version --client && helm version && argocd version --client --short
```

### One-command bootstrap

```bash
git clone https://github.com/Ediong-dev/school-management-sre.git
cd school-management-sre
./scripts/bootstrap.sh
```

The script does the following in order:

1. Creates a 3-node k3d cluster with the correct port mappings
2. Installs ArgoCD (server-side apply for the CRDs)
3. Installs Argo Rollouts
4. Installs `kube-prometheus-stack` via Helm
5. Applies the ArgoCD Application manifest
6. Waits for ArgoCD to sync the application stack from Git
7. Prints the URLs and the post-bootstrap step (Discord webhook secret)

Runtime: **~15 minutes**, most of it waiting for pods.

When it finishes:

- Gateway: http://localhost:4000
- ArgoCD: http://localhost:8090 (login: `admin`; password in secret `argocd-initial-admin-secret`)
- Grafana: http://localhost:3030
- Prometheus: http://localhost:9090

### Verify the deployment

```bash
# Login
curl -X POST "http://localhost:4000/api/auth/login?email=admin@school.edu&password=admin123"

# Full chain (gateway → dashboard → academics)
curl http://localhost:4000/api/dashboard/admin/overview
```

Expected for the second command:

```json
{"total_students":5,"total_teachers":3,"total_sections":3,"total_classes":3}
```

### One thing not in Git

The Discord webhook URL for alerting is a credential and is not committed.
After bootstrap, create the Secret manually (once in each namespace):

```bash
kubectl -n monitoring create secret generic alertmanager-discord \
  --from-literal=webhook-url="<your-webhook-url>"

kubectl -n school create secret generic alertmanager-discord \
  --from-literal=webhook-url="<your-webhook-url>"
```

Without it, alerts fire correctly in Prometheus, but Discord delivery fails.

### Tear down

```bash
k3d cluster delete school
```

---

## Notable Engineering Decisions

### Why ArgoCD instead of `kubectl apply`

Manual `kubectl apply` requires a human to run it. That means every deploy has
a failure mode called "the human forgot to run the command." ArgoCD reconciles
continuously — drift is corrected within seconds. The orphan container incident
in Lab 1 was the direct motivation.

### Why `configMapGenerator` instead of plain ConfigMaps

Kubernetes doesn't restart pods when a ConfigMap changes. If you edit a
ConfigMap and `kubectl apply` it, running pods keep serving the old value.
Kustomize's `configMapGenerator` appends a content hash to the ConfigMap name,
so any change forces a Deployment rollout automatically.

### Why canary with Prometheus analysis

Rolling updates replace all pods without gating on metrics. If the new version
is bad, all users see it. Argo Rollouts canary strategy sends a small fraction
of traffic to the new version, queries Prometheus every 15 seconds, and aborts
automatically if the error rate exceeds 5%.

### Why backups go to a separate PVC

Postgres's data volume and the backup volume are separate `PersistentVolumeClaim`
resources. If the data volume is corrupted, backups survive. If both were on the
same volume, a single disk failure would lose everything.

### Why the Postgres init Job is separate from the schema migrations

The init Job creates the database schema for the first time. Alembic migrations
evolve it afterward. Keeping them separate means a fresh cluster can be seeded
idempotently, and migrations can run on top of an existing database.

---

## Known Limitations

Honest about what wasn't achieved:

- **No HPA** — the capacity test found the breaking point, but auto-scaling was
  not implemented. A production system would add this.
- **No traffic router** — canary uses basic pod-count mode. Precise percentage
  traffic shifting requires Istio or NGINX ingress.
- **Secrets in Git** — the JWT secret and Postgres password are in the lab
  manifests. Production would use SealedSecrets or ExternalSecrets.
- **Single-node Postgres** — no replication, no failover. Production would use
  Patroni or a managed database service.
- **No distributed tracing** — Tempo or Jaeger would complete the three pillars
  of observability (metrics and logs are in place).

Each limitation is documented in `docs/reliability/reliability-review.md` with
the specific approach that would address it.

---

## Further Reading

**For the 60-second version:** you just read it.

**For the 10-minute version:**

- [`docs/reliability/reliability-review.md`](docs/reliability/reliability-review.md) —
  the full retrospective with architecture, DORA metrics, and incident analysis
- [`docs/reliability/dora-metrics.md`](docs/reliability/dora-metrics.md) —
  how the four metrics were computed from Git history

**For the deep dives:**

- [`docs/chaos-experiments/`](docs/chaos-experiments/) — three formal experiments
  with falsified hypotheses and evidence
- [`submissions/`](submissions/) — 10 lab write-ups, one per chapter
- [`docs/runbooks/`](docs/runbooks/) — operational procedures for each alert

**For the "how do I run this myself" curiosity:**

- [`scripts/bootstrap.sh`](scripts/bootstrap.sh) — the whole cluster from Git
  in one command

---

## About

**Senyene Udoh** — SRE / Platform Engineer
[GitHub](https://github.com/Ediong-dev) · [LinkedIn](https://www.linkedin.com/)

Built as a portfolio project to demonstrate practical SRE competency across the
full stack: architecture, observability, incident response, capacity planning,
and disaster recovery. Feedback welcome.

---

*The most important thing this repository demonstrates is not any single tool
or technique. It is the discipline of treating reliability as a first-class
engineering concern — as important as feature work, as measurable as
performance, and as documented as any other production system.*