# Chaos Experiment 1 — Latency Injection Cascade

**Date:** 2026-09-18
**Experimenter:** Senyene
**Status:** Complete — hypothesis partially falsified

## Hypothesis

If `academics` responds with 3s latency:
1. Dashboard P95 will exceed 3s (4 sequential calls to academics → ~12s)
2. Gateway will return 503s (10s timeout exceeded)
3. Auth will remain unaffected

## Method

- Injection: `ACADEMICS_LATENCY_MS=3000` set via Git commit `f27d326`, synced by ArgoCD
- Load: 2 req/s to `/api/dashboard/admin/overview` for ~90 seconds via `curl` loop
- Sampling: P95 every 30s via `school:http_latency_p95:rate5m` (Prometheus 5m window)
- Recovery: `git revert` of `f27d326`

## Timeline (UTC)

| Event | Time |
|-------|------|
| Baseline captured | 23:59:28 |
| LOAD START | 23:59:28 |
| INJECTED AT | 23:59:50 |
| ArgoCD synced | 23:59:55 |
| Academics pods rolled | ~00:00:30 |
| Load ended (Ctrl+C) | ~00:01:00 |
| REVERTED AT | 00:01:32 |
| RECOVERED AT | 00:01:38 |

## Baseline (pre-injection)

| Service | P95 |
|---------|-----|
| auth | 0.095s |
| academics | 0.095s |
| dashboard | 0.095s |
| gateway-stable | 0.095s |
| gateway-canary | 0.095s |

## Observed P95 After Injection

| Sample | Time | auth | academics | dashboard | gateway |
|--------|------|------|-----------|-----------|---------|
| 1 | 00:00:20 | 0.095 | 0.095 | 0.095 | 0.095 |
| 2 | 00:00:50 | 0.095 | 0.095 | 0.095 | 0.095 |
| 3 | 00:01:20 | 0.095 | 0.096 | 0.096 | 0.096 |
| 4 | 00:01:50 | 0.095 | 0.099 | 0.097 | 0.096 |
| 5 | 00:02:20 | 0.095 | 1.000 | 0.098 | 0.097 |
| 6 | 00:02:50 | 0.095 | 1.000 | 0.098 | 0.097 |

## User-Visible Impact (from load generator)

- ~70 consecutive requests returned HTTP 200 (baseline)
- ~14 consecutive requests returned HTTP 503 (injection window)
- ~35 consecutive requests returned HTTP 200 (recovery)
- **Total: ~14 failures out of ~120 requests ≈ 12% error rate during the affected window**

## Hypothesis Scorecard

| Prediction | Result |
|-----------|--------|
| Auth unaffected | ✅ Validated — flat at 0.095s |
| Academics P95 rises | ✅ Validated — rose to 1.000s |
| Dashboard P95 cascades (~12s) | ❌ **Falsified** — stayed at 0.098s |
| Gateway returns 503s | ✅ Validated — 14 requests observed |

## Analysis

**Academics P95 discrepancy (1.000s vs expected 3.000s):** This is the histogram bucket resolution issue documented in Lab 3. The default `prometheus-fastapi-instrumentator` bucket boundaries are `[0.75, 1.0, 2.5, 5.0, 7.5, 10]`. A 3s response lands between `le="2.5"` and `le="5.0"` and `histogram_quantile` interpolates to ~1.0s due to the coarse boundary set. Not a system defect — a measurement limitation.

**Dashboard non-cascade:** Multiple contributing factors.
1. **Metric cancellation** — the gateway's 10s timeout caused it to abandon the request before dashboard's 12s aggregate completed. Dashboard's httpx client may cancel its in-flight calls when the outer request is dropped, preventing them from registering in dashboard's latency histogram.
2. **5-minute rate window dilution** — the injection was active for ~1.5 minutes out of the 5-minute window. The P95 is dominated by baseline traffic.
3. **Metric aggregation scope** — `service="dashboard"` measures dashboard's server-side response time. If the outer request was cancelled, dashboard never recorded a "complete" response.

**Gateway's elevated 503s with flat P95:** The 503s were responses the gateway sent *quickly* (at the 10s timeout boundary), but 14 requests out of ~120 fall below the P95 quantile (which covers the 95th percentile — the top 5% slowest). 14/120 ≈ 12% should have registered above P95, but the coarse bucket resolution again hides the true tail.

## Conclusion

**The cascade happened.** The 503s prove it. Users experienced real failures during the injection window.

**The metrics did not clearly reflect the cascade.** P95 latency charts alone would miss this incident. This is a critical operational finding — it means our SLO-based latency alerting would not fire under this failure mode, even though users experienced errors.

## Follow-Up Actions

- [ ] **Add custom histogram buckets** to all services with finer resolution around 1–15s (target: `[.005, .01, .025, .05, .075, .1, .25, .5, .75, 1, 2.5, 5, 7.5, 10, 15]`) so the cascade region is measurable
- [ ] **Add an error-rate alert** (not just latency) — the 503s would be visible in `school:http_error_ratio` even when latency isn't
- [ ] **Run longer injections** (≥ 10 minutes) so the 5m rate window is dominated by injected traffic
- [ ] **Sample metrics DURING the injection**, not just after — the current sampling missed the peak

## Portfolio Value

This experiment demonstrates:

1. **Hypothesis-driven chaos engineering** — formal write-up with predictions that were falsified
2. **Recognition that measurement systems have resolution limits** — the histogram bucket issue is subtle and rarely discussed
3. **A genuine finding that changes operational posture** — the latency-based SLO alerting has a blind spot
4. **GitOps-driven injection and recovery** — every state change is a commit, recovery is a revert

The most valuable output is the **"Dashboard didn't cascade" falsification** — that's a real discovery that emerged from testing an assumption, which is exactly what chaos engineering is for.