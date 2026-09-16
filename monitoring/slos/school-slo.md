# SLO Definitions — School Management System

**Owner:** Platform / SRE
**Review cadence:** Quarterly

## Services In Scope

| Service | Port | Criticality |
|---------|------|-------------|
| gateway | 3000 | Tier 1 — front door, all user traffic |
| auth | 3001 | Tier 1 — required for login |
| dashboard | 3003 | Tier 2 — read-only aggregation |
| academics | 3002 | Tier 1 — underlying data service |

## SLI Definitions

### Availability SLI
**Definition:** proportion of non-5xx responses over total responses, measured at the gateway.
availability = 1 - (rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]))

text

**Measurement window:** rolling 5m for alerts, rolling 30d for the SLO.

### Latency SLI
**Definition:** proportion of requests completing in < 500ms, measured at the gateway.
latency_good = rate(http_request_duration_seconds_bucket{le="0.5"}[5m]) / rate(http_request_duration_seconds_count[5m])

text

## SLO Targets

| SLI | Target | Window | Error Budget |
|-----|--------|--------|--------------|
| Availability | 99.9% | 30 days | 43m 12s |
| Latency (P95 < 500ms) | 99% | 30 days | 7h 12m |

## Error Budget Policy

When a service exhausts its error budget:
1. All non-urgent feature work for that service is paused.
2. Engineering effort is redirected to reliability improvements.
3. A written postmortem is required before feature work resumes.

## Alerting Philosophy

We do not alert on raw error rate thresholds ("error rate > 1%"). We alert on **error budget burn rate** — how fast we're consuming the budget relative to the sustainable rate. This produces fewer, more meaningful alerts.

- **Fast burn** (page): burning 14.4× sustainable rate over both 5m and 1h windows → exhausts monthly budget in ~2 days
- **Slow burn** (ticket): burning 6× sustainable rate over both 30m and 6h windows → exhausts monthly budget in ~5 days
