markdown
# Lab 3 — Observability & SLOs

**Date:** 2026-09-14
**Baseline:** tag `lab2-complete`

## What Was Built

- **Prometheus** (v2.55.0) scraping all four services every 15s
- **Grafana** (v11.3.0) with anonymous viewer access, running on port 3030
- **6 recording rules** producing SLIs (request rate, error rate, error ratio, availability, P95 latency, P99 latency)
- **Golden Signals dashboard** provisioned as code from Git — no manual UI clicks

## Architecture
Four services (:3000-3003) ──/metrics──▶ Prometheus (:9090)
│
├── recording rules (30s eval)
│
└──▶ Grafana (:3030)
Golden Signals dashboard

## Prometheus Targets

All 5 targets scraped successfully:

| Target | State | Scrape Duration |
|--------|-------|-----------------|
| prometheus | UP | ~4ms |
| gateway | UP | ~2.6ms |
| auth | UP | ~2.8ms |
| academics | UP | ~2.3ms |
| dashboard | UP | ~2.5ms |

## Recording Rules

All 6 rules healthy, sub-millisecond evaluation:
school:http_requests:rate5m — sum by (job) rate(http_requests_total[5m])
school:http_errors:rate5m — sum by (job) rate(...{status=~"5.."}[5m])
school:http_error_ratio:rate5m — clamp_max(errors/requests or 0*requests, 1)
school:http_availability:ratio_rate5m — 1 - error_ratio
school:http_latency_p95:rate5m — histogram_quantile(0.95, rate(bucket[5m]))
school:http_latency_p99:rate5m — histogram_quantile(0.99, rate(bucket[5m]))

## Incidents

### Incident 1 — YAML schema false positive
VS Code's YAML extension flagged `apiVersion` and `datasources` as invalid in `prometheus.yml` because the filename matched the schema for the Prometheus *server* config, not the Grafana *datasource* config.

**Fix:** Renamed the file to `grafana-prometheus-datasource.yml`.
**Lesson:** Editor diagnostics are hints, not truth. The runtime is authoritative.

### Incident 2 — Empty error ratio on dashboard
The Availability and Error rate panels showed "No data" until 5xx errors were injected. Cause: `sum by (job) (rate(...{status=~"5.."}[5m]))` produces an *empty vector* when there are no 5xx samples — not a zero-vector. Dividing empty/non-empty produces empty.

**Fix:** `(... / ...) or (0 * school:http_requests:rate5m)` — the `or` idiom coerces empty to zero with correct labels.

### Incident 3 — Error ratio > 100%
After injecting failures, the panel showed values up to 10000%. Cause: `rate()` extrapolation diverges when traffic drops to zero but residual errors age unevenly.

**Fix:** `clamp_max(..., 1)` — mathematically correct ceiling.

## What This Lab Proved

1. **Dashboards as code works.** Every panel, every query, every threshold lives in Git.
2. **Recording rules matter.** Pre-computing expensive PromQL keeps the dashboard fast during incidents.
3. **Metrics alone cannot diagnose.** When the dashboard showed academics at 75% availability, I could not tell *why* — I needed logs.
4. **PromQL has sharp edges.** `empty / non-empty` returns empty, not zero. This pattern will bite anyone who hasn't hit it before.

## The Three Pillars of Observability

| Pillar | Question | Have it? |
|--------|----------|----------|
| Metrics | WHAT is happening? | ✅ Lab 3 |
| Logs | WHY is it happening? | ⏳ Lab 3.5 (optional) |
| Traces | WHERE did time go? | ⏳ Later lab |

**Portfolio framing:** *"Metrics tell me what, logs tell me why, traces tell me where. You need all three to run a production service."*

## Next

Lab 4: Kubernetes. Migrate from Docker Compose to k3d, add readiness/liveness probes, get self-healing and rolling updates.
