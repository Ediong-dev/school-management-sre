# School Management System — Reliability Review

**Author:** Senyene Udoh
**Date:** 2026-09-22
**Reporting period:** 2026-09-15 to 2026-09-22 (7 days)
**Project:** 4-service microservices system with GitOps, SLOs, and chaos engineering
**Repository:** https://github.com/Ediong-dev/school-management-sre

---

## Executive Summary

This project is a deliberately-constructed SRE portfolio artifact. It is not a
tutorial clone — it is a production-shaped system that was built to be *operated*,
observed under failure, and documented through real incidents.

The system is four FastAPI microservices (gateway, auth, academics, dashboard)
running on Kubernetes, backed by PostgreSQL, deployed entirely via GitOps, with
SLO-based alerting, canary deployments, and automated backups. Over seven days
of active development, the project accumulated:

- **10 tagged releases** (`lab0-complete` through `lab10-complete`)
- **10 write-ups** in `submissions/` documenting real incidents
- **3 formal chaos experiments** with falsified hypotheses
- **5+ postmortems** for real failures
- **~70 commits** with a fully-elite DORA profile
- **A cluster rebuilt from Git three times** without manual intervention

The most valuable artifact is not the code — it is the **incident history**. Every
real bug, every falsified hypothesis, and every operational gap is documented with
root cause and fix. This is what an SRE portfolio looks like when it is honest.

---

## Architecture

### Services

| Service | Port | Role | Dependencies |
|---------|------|------|--------------|
| gateway | 3000 | Front door, request routing | auth, academics, dashboard |
| auth | 3001 | Login, JWT issuance, RBAC | PostgreSQL |
| academics | 3002 | Students, teachers, classes, sections | none |
| dashboard | 3003 | Role-specific aggregated views | auth, academics |

### Infrastructure

- **Kubernetes:** k3d (k3s in Docker) — 1 server, 2 agents
- **Ingress:** k3d load balancer → `gateway-stable` NodePort 30000 → host port 4000
- **Database:** PostgreSQL 16, StatefulSet with persistent volume
- **Observability:** Prometheus, Grafana, Alertmanager (kube-prometheus-stack)
- **GitOps:** ArgoCD with `automated.prune` and `automated.selfHeal`
- **Progressive delivery:** Argo Rollouts with canary strategy and Prometheus analysis
- **CI/CD:** GitHub Actions → ghcr.io → GitOps overlay commit → ArgoCD sync

### Data flow
Browser → localhost:4000
↓
k3d load balancer (host port 4000 → cluster NodePort 30000)
↓
gateway-stable Service → 4 gateway pods
↓
├─→ auth Service → 2 auth pods → PostgreSQL
├─→ academics Service → 2 academics pods
└─→ dashboard Service → 2 dashboard pods → academics Service (4 sequential calls)


---

## Service Level Objectives

Defined formally in `monitoring/slos/school-slo.md` and implemented as
PrometheusRule CRDs in `k8s/base/prometheusrules-alerts.yaml`.

| SLI | Target | Error Budget (30d) |
|-----|--------|--------------------|
| Availability (all services) | 99.9% | 43m 12s |
| Latency P95 < 500ms | 99% | 7h 12m |

### Alerting strategy

Alerts fire on **burn rate**, not raw thresholds:

- **`SchoolSLOFastBurn`** — 14.4× sustainable rate over 5m and 1h windows
  (exhausts budget in ~2 days)
- **`SchoolSLOSlowBurn`** — 6× sustainable rate over 30m and 6h windows
  (exhausts budget in ~5 days)
- **`SchoolHighLatencyP95`** — P95 > 500ms for 10 minutes

All SLO alerts carry `namespace: school` and route to Discord via
AlertmanagerConfig. Non-actionable alerts route to `null` (learned in Lab 6 —
see "Alert fatigue incident" below).

---

## DORA Metrics

Full analysis in `docs/reliability/dora-metrics.md`.

| Metric | Value | DORA Tier |
|--------|-------|-----------|
| Deployment Frequency | 11.3 deployments/day | **Elite** |
| Lead Time for Changes | ~55 seconds | **Elite** |
| Change Failure Rate | 5.3% (3 of 57) | **Elite** |
| Mean Time to Recovery | 7 minutes (median) | **Elite** |

**All four metrics reach DORA Elite tier.**

The deployment pipeline is: `git push` → GitHub Actions builds 4 images in
parallel (~50s) → pushes to ghcr.io → commits the new SHAs to the GitOps overlay
→ ArgoCD syncs → K8s rolls pods. Total time: under 4 minutes.

Rollback is `git revert HEAD && git push`. GitOps makes the "undo" of any deploy
a single commit.

---

## Incident History

Every incident below is documented in full in `submissions/` with root cause,
fix, and lesson learned. These are real failures, not hypotheticals.

### Lab 0 — Bootstrap failures

1. **Codespaces refused to boot on an empty repo** — no default branch to clone.
   Fix: commit a README via the GitHub web UI first.
2. **`hey` binary downloaded as HTML** — `curl -sL` fetched a "Not Found" page
   silently. Fix: switched to `apache2-utils`.
3. **Git LFS hook blocked every push** — hook present, binary missing.
   Fix: `apt install git-lfs`.
4. **Pylance couldn't resolve imports** — cosmetic, the container was fine.

### Lab 1 — Failure mapping

5. **E5 chaos test accidentally injected DNS failure** — renamed container
   without `--network-alias`. The "slow service" test produced a different
   failure mode than intended. Named the "symptom vs. cause" discipline that
   recurred throughout the project.

### Lab 2 — Container hardening

6. **Orphan container held port 3002** — a manual `docker run` survived
   `docker compose down`. Compose can't reconcile state it didn't create.
   This directly motivated the GitOps decision in Lab 5.

### Lab 3 — Observability

7. **Empty PromQL vector broke Grafana panels** — `sum(rate(...{status=~"5.."}))`
   returns empty when there are no 5xx, not zero. Fix: `A or (0 * B)` idiom.
8. **Error ratio exceeded 10000%** — `rate()` extrapolation diverged under
   zero traffic. Fix: `clamp_max(..., 1)`.

### Lab 4 — Kubernetes

9. **k3d load balancer port conflict on 9090** — Prometheus still running from
   Lab 3. Fix: used 9091.
10. **Readiness probe fired before Uvicorn bound its port** — expected behavior,
    documented rather than "fixed."

### Lab 5 — GitOps

11. **ArgoCD CRD annotation size limit** — `kubectl apply` failed with
    "annotation too long." Fix: server-side apply with `--force-conflicts`.
12. **ConfigMap changes didn't roll pods** — K8s reads env at container start.
    Fix: `configMapGenerator` with content hash suffix.
13. **CI bot race on every push** — bot pushed its own commit while we were
    working. Fix: `git pull --rebase` before every push.

### Lab 6 — Alerting

14. **Grafana crash looped on first install** — `additionalDataSources`
    conflicted with the chart's built-in Prometheus datasource.
15. **ArgoCD sync retry exhaustion** — after 5 failures, backoff kicked in and
    fixing the underlying problem didn't trigger a retry. Fix: change the
    Application spec to reset the counter.
16. **AlertmanagerConfig secret in wrong namespace** — the Prometheus Operator
    resolves secrets within the AlertmanagerConfig's namespace, not Alertmanager's.
17. **SLO burn drill: `sed` didn't match** — pattern assumed two strings on
    one line. Fix: `sed` with the `n` command.
18. **Alert routing gap** — real alerts lacked the `namespace=school` label the
    Prometheus Operator auto-injects as a matcher. They fell through to `null`
    receiver. Fix: explicit label on every PrometheusRule alert.
19. **Alert fatigue** — chart-default alerts (Watchdog, InfoInhibitor,
    CPUThrottlingHigh) flooded Discord. Fix: `receiver: null` as the default
    route; explicit matchers only.

### Lab 7 — Progressive delivery

20. **Kustomize doesn't rewrite references inside CRDs** — the Rollout's
    ConfigMap reference was left unmodified while the ConfigMap name got a
    hash suffix. Pods failed with `CreateContainerConfigError`.
21. **Rollout conversion split the `service` label** — from `gateway` to
    `gateway-stable`/`gateway-canary`. Every query hardcoding `service="gateway"`
    broke silently.
22. **Kubernetes Job immutability** — ArgoCD's default apply tried to patch a
    Job's immutable spec.template. Fix: `Force=true,Replace=true` annotation.
23. **Basic canary mode doesn't route user traffic to the canary** — the
    canary Service exists but receives no traffic without a routing provider.
    Fix for demo: synthetic traffic to the canary Service.
24. **Six failed canary demo attempts** — each produced a distinct learning
    about how the mechanism actually works.

### Lab 8 — Chaos engineering

25. **Latency injection cascade — hypothesis partially falsified** — the cascade
    happened (14 × 503) but P95 metrics didn't reflect it due to histogram
    bucket resolution. The latency SLO would not have fired under this failure.
26. **Simultaneous pod kills — hypothesis falsified** — 4 pods killed in
    parallel, MTTR ~10s, but 1 of 518 requests returned 503. Root cause: pod
    still in EndpointSlice for a moment after SIGTERM. Fix: `preStop` hook.

### Lab 9 — Database reliability

27. **YAML indentation error in auth Deployment** — ArgoCD refused to apply,
    kept cluster in last-known-good state.
28. **Alembic Job used fully-qualified image ref** — bypassed the Kustomize
    transformer. Ran a stale cached image.
29. **Job immutability blocked reconciliation** (repeat of Lab 7) — resolved
    with the same Force+Replace pattern.
30. **`alembic-migrate` raced Postgres startup** — no wait step. Fix: init
    container with `pg_isready` loop.
31. **Restore failed with double-prefix path** — `$BACKUP_FILE` already contained
    the prefix. Cost ~2 minutes during the drill.
32. **Backup CronJob backed up the broken DB** — after `DROP TABLE users`, the
    CronJob continued every 2 min, eventually rotating out good backups. Lesson:
    backups are only as good as the data in them; pre-backup validation is
    required in production.

### Lab 10 — Portfolio

33. **Locust ConfigMap not created** — heredoc paste failed silently. Fix:
    switched to `code <file>` for all YAML.
34. **Load test hit wrong Service name** — Locust targeted `gateway` which
    doesn't exist anymore after the Lab 7 Rollout split. Fix: `gateway-stable`.
35. **200-user test found the capacity limit** — dashboard endpoint failed at
    29% because it makes 4 sequential calls to academics and hits the gateway's
    10-second timeout. Same cascade identified in Lab 1 E5.

---

## Capacity Findings

Full analysis in `docs/reliability/capacity-analysis.md`.

| Load | Throughput | Failures | Median | P95 |
|------|-----------|----------|--------|-----|
| 10 users | 9.73 req/s | 0% | 26 ms | 97 ms |
| 50 users | 40.05 req/s | 0% | 52 ms | 550 ms |
| **200 users** | **49.19 req/s** | **13.91%** | **430 ms** | **6400 ms** |

**Breaking point: between 50 and 200 concurrent users.**

The bottleneck is specific: `/api/dashboard/admin/overview` fails at 29% under
saturation because it makes 4 sequential calls to academics. All other endpoints
— including auth login with pgcrypto password hashing — held at 200 users.

**Fix identified:** parallelize the dashboard's downstream calls with
`asyncio.gather` and add a short-TTL cache for the aggregate data.

---

## Disaster Recovery

**The cluster was destroyed and rebuilt from Git three separate times during
this project** (Codespace resets, quota exhaustion, environment changes).

Each rebuild used the same procedure:

1. `k3d cluster create` with matching port mappings
2. Install ArgoCD, Argo Rollouts, kube-prometheus-stack
3. Recreate the Discord webhook Secret (the one thing not in Git)
4. `kubectl apply -f k8s/argocd/application.yaml`
5. Wait 2 minutes for ArgoCD to sync everything from Git

**Total time: 15 minutes, zero manual configuration of application resources.**

This is the strongest empirical proof that the reliability investments paid off.
When an interviewer asks "what happens if the cluster dies?", the answer is
not theoretical — it's a rehearsed procedure with a known time budget.

---

## What This Project Demonstrates

### Technical competencies

- **Microservices architecture** with proper service boundaries
- **Kubernetes** — StatefulSets, PVCs, Deployments, Rollouts, Jobs, CronJobs,
  ConfigMaps, Secrets, ServiceMonitors, PrometheusRules, AlertmanagerConfigs
- **GitOps** with ArgoCD — automated sync, self-heal, prune, drift correction
- **Progressive delivery** with Argo Rollouts — canary strategy, automated abort
- **Observability** — golden signals, SLOs, error budgets, burn-rate alerting,
  multi-window alerting, dashboards-as-code
- **Database reliability** — StatefulSets, migrations (Alembic), backups, RTO/RPO
- **Chaos engineering** — hypothesis-driven experiments with documented findings
- **Incident response** — runbooks, postmortems, blameless retrospectives
- **CI/CD** — GitHub Actions, GHCR, Kustomize, GitOps commits from CI

### SRE disciplines

- **SLO-driven alerting** — burn rate, not raw thresholds
- **Error budget management** — quantified, policy-driven
- **Measurement before optimization** — the capacity test was informed by the
  Lab 1 chaos experiment
- **Safe failure** — GitOps rollback as the primary recovery mechanism
- **Honest documentation** — every falsified hypothesis and untested assumption
  is recorded

### Meta-competencies

- **Working with incomplete information** — 6 failed canary attempts before success
- **Diagnosing cross-layer failures** — bugs spanned YAML, GitOps, Kubernetes,
  Prometheus, and application code
- **Rebuilding from scratch under pressure** — 3 cluster rebuilds from Git
- **Recognizing when to stop and reboot** — quota exhaustion, environment switches

---

## Known Limitations

Honest about what was not achieved:

- **No horizontal pod autoscaler (HPA)** — the capacity test found the breaking
  point, but auto-scaling was not implemented. A production system would.
- **No traffic router (Istio/NGINX ingress)** — basic canary mode was used, which
  requires synthetic traffic for the analysis. Real traffic splitting requires a
  routing provider.
- **Secrets in Git** — JWT secret and Postgres password are in `k8s/base/*.yaml`
  for the lab. A production system would use SealedSecrets or ExternalSecrets.
- **Single-node Postgres** — no replication, no failover. Production would use
  Patroni or a managed database.
- **No distributed tracing** — Tempo or Jaeger would complete the three pillars
  of observability.
- **No admission policies** — OPA/Gatekeeper or Kyverno would enforce security
  policy at apply time.

---

## Portfolio Framing

For a hiring manager reading this review, the key signals are:

1. **I built a system and then operated it.** The distinction matters. Many
   candidates can build; fewer can run what they built.

2. **I found real bugs and documented them.** 30+ incidents, each with root
   cause and fix. These are not made-up scenarios — they are things that broke
   during actual development.

3. **I measured the system.** DORA metrics, capacity analysis, RTO/RPO — all
   empirically derived, not estimated.

4. **I practice the failure discipline.** Chaos experiments with falsified
   hypotheses. Postmortems. Runbooks. Blameless retrospectives.

5. **I can rebuild under pressure.** The cluster was destroyed and rebuilt three
   times. Each rebuild took 15 minutes with zero manual configuration.

The project is not perfect. The known limitations section lists the gaps
honestly. But the *process* — build, observe, break, document, fix, rebuild — is
what makes this a portfolio rather than a code repository.

---

## References

- Repository: https://github.com/Ediong-dev/school-management-sre
- SLO definitions: `monitoring/slos/school-slo.md`
- Alert rules: `k8s/base/prometheusrules-alerts.yaml`
- Runbooks: `docs/runbooks/README.md`
- Postmortems: `docs/postmortems/`
- Chaos experiments: `docs/chaos-experiments/`
- DORA metrics: `docs/reliability/dora-metrics.md`
- Capacity analysis: `docs/reliability/capacity-analysis.md`
- Lab write-ups: `submissions/lab0.md` through `submissions/lab10.md`

---

## Closing Note

The most important thing this project demonstrates is not any single tool or
technique. It is the **discipline of treating reliability as a first-class
engineering concern** — as important as feature work, as measurable as
performance, and as documented as any other production system.

Every SLO, every alert, every runbook, and every postmortem in this repository
is real. They were created in response to real problems, and they demonstrate
the operating discipline that separates an SRE from a developer who happens to
write infrastructure code.