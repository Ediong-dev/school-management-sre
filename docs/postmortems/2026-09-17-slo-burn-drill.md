# Postmortem: SLO Burn Drill — Academics Failure Injection

**Date:** 2026-09-17
**Author:** Senyene
**Status:** Resolved
**Type:** Deliberate drill (chaos engineering)

---

## Summary

A synthetic incident was injected into the `academics` service by setting
`ACADEMICS_FAILURE_RATE=0.3` in the Deployment manifest via GitOps. The
change caused approximately 30% of `/students` requests to return HTTP 500.
Over a 5-minute load test, 380 client-visible 5xx errors were generated
(and mirrored upstream as 380 gateway 5xx via cascading). The `SchoolSLOSlowBurn`
alert fired in Prometheus. **The alert did not initially reach the Discord notification channel — a
routing gap identified by this drill, diagnosed, and fixed within the same
session. See Finding 2 for details.

## Impact

- **Users affected:** all callers of `/api/academics/*`
- **Error rate:** peaked at 22% (5m window) / 10.5% (1h window) for academics
- **Total 5xx errors:** 380 (academics), 380 (gateway as cascade)
- **Duration:** ~5 minutes of sustained failure
- **Alerting:** one alert fired in Prometheus (`SchoolSLOSlowBurn`); **zero reached Discord**

## Timeline (UTC)

| Time | Event |
|------|-------|
| 00:44:41 | Failure injected: `ACADEMICS_FAILURE_RATE` changed 0 → 0.3 |
| 00:44:5x | `git sync` — commit `4ffa78a` pushed to main |
| 00:47:20 | ArgoCD applied the change; academics pods rolled |
| 00:48 | Smoke test confirmed 30% failure rate (`Fails: 4/20`, then `6/20`) |
| 00:50:40 | Load generator started (2 req/s to `/api/academics/students`) |
| 00:52:39 | `SchoolSLOSlowBurn` condition first became active (pending) |
| 00:55:54 | Load generator finished (600 requests over 5 min) |
| ~01:07:39 | `SchoolSLOSlowBurn` transitioned pending → **firing** |
| 01:19:57 | Mitigation: `git revert 4ffa78a` committed (`36bed61`) |
| 01:20:26 | ArgoCD rolled back academics; env var reverted to `0` |
| ~01:22 | Recovery verified: all SLIs back to 1.000000 |

## Root Cause

**Direct cause:** `ACADEMICS_FAILURE_RATE` env var set to `0.3` via a Git
commit, deliberately, as a drill.

**Underlying cause:** this was a deliberate chaos engineering experiment
to validate the SLO burn detection and notification pipeline.

## Detection

- **Detected by:** `SchoolSLOSlowBurn` alert in Prometheus (fired at ~01:07:39)
- **Time from injection to alert:** ~23 minutes (SlowBurn has a 15m `for`
  requirement after the 30m/6h windows cross threshold; the 6h window is
  slow to accumulate)
- **Time from alert to notification:** **N/A — no notification was delivered**

## What Worked

1. **Failure injection path** — GitOps-driven env change deployed cleanly
   via ArgoCD in ~2.5 minutes
2. **SLI computation** — `school:http_error_ratio:rate5m` and `:rate1h`
   correctly reflected the injection (peaked at 22% and 10.5%)
3. **Blast radius visibility** — cascading failure to gateway was visible
   in the same SLI (gateway mirrored academics error ratio)
4. **Mitigation via `git revert`** — full rollback in under 3 minutes
5. **Recovery** — SLIs returned to 1.0 within 60 seconds of pod rollover

## What Did Not Work — Findings for Action

### Finding 1: `SchoolSLOFastBurn` did not fire

**Observation:** The FastBurn rule (14.4× threshold = 1.44%, requires both
5m and 1h windows above threshold for 2 continuous minutes) never transitioned
to `firing`.

**Hypothesis:** The 1h window crosses threshold gradually. By the time both
windows were simultaneously above 1.44%, the load had already stopped
(00:55:54) and the 5m window began dropping. The `for: 2m` timer never
completed.

**Impact:** Fast-burn detection did not trigger, so the "page immediately"
pathway was not exercised. Slow burn caught the incident ~23 minutes later.

**Action items:**
- [ ] Reduce FastBurn `for` duration from `2m` to `1m`
- [ ] Add a "very fast burn" alert on the 5m window only (no 1h requirement)
- [ ] Add a synthetic alert injection tool to the tooling (like `amtool` but
      for Prometheus rules) so we can test rule evaluation without load

### Finding 2: `SchoolSLOSlowBurn` fired in Prometheus but did not reach Discord — RESOLVED

**Observation:** The rule transitioned to `firing` at ~01:07:39. Alertmanager's
API confirmed it received the alert — `wget -qO- http://localhost:9093/api/v2/alerts`
showed `SchoolSLOSlowBurn: receiver_names=['null']`. But no notification
reached Discord.

**Root cause:** The three SLO alert rules in `k8s/base/prometheusrules-alerts.yaml`
emitted only two labels: `severity` and `slo`. The Prometheus Operator automatically
wraps every `AlertmanagerConfig` in a namespace-scoped sub-route that requires a
`namespace=school` matcher. Alerts without that label fell through to the default
`null` receiver.

This is a **multi-tenancy guardrail** by design: one shared Alertmanager instance
can serve many tenants, and the namespace matcher prevents tenant A's alerts from
routing into tenant B's receivers. But the operator does **not** automatically
inject the `namespace` label onto alerts emitted by `PrometheusRule` — the rule
author must add it explicitly.

**Evidence chain:**
1. `SchoolSLOSlowBurn` was `state=firing` in Prometheus `/api/v1/rules` — the rule
   logic worked correctly.
2. Alertmanager's `/api/v2/alerts` showed the alert was received but its
   `receiver_names` was `['null']`.
3. The `TestDiscord` synthetic alert with `namespace=school` sent earlier had
   routed correctly to `['school/school-alerts/discord']` — proving the receiver
   itself was configured and reachable.
4. The only difference: real alerts lacked the `namespace` label.

**Fix:** Added `namespace: school` to the `labels` block of all three SLO alerts
in `k8s/base/prometheusrules-alerts.yaml`. Commit `07174da`.

**Verification:**
1. Rule definition now shows `namespace: school` in the labels of all three alerts
   (`curl http://localhost:9090/api/v1/rules?type=alert`).
2. A synthetic alert with the exact label set produced by the fixed rules
   (`{alertname=SchoolSLOSlowBurn, severity=warning, namespace=school, slo=availability_99_9}`)
   routed to `receiver_names=['school/school-alerts/discord']`.
3. Discord received the notification.

**Impact:** This was the most serious finding of the drill. An alert that fires
in Prometheus but does not reach the on-call engineer is a reliability gap that
undermines the entire alerting posture. In a real incident, this gap would have
delayed response from seconds to hours. The drill caught it before production.

**Lesson:** In multi-tenant Alertmanager setups with the Prometheus Operator,
**always add an explicit `namespace` label to alerts emitted by `PrometheusRule`.**
The operator's namespace matcher is a security feature, not a bug — but it requires
cooperation from the rule author.

## Action Items (Summary)

- [x] Diagnose and fix the SlowBurn→Discord routing gap (commit `07174da`; verified)
- [ ] Reduce `SchoolSLOFastBurn` `for` from 2m → 1m
- [ ] Add `SchoolSLOVeryFastBurn` alert (5m window only, 20× threshold, 1m `for`)
- [ ] Add synthetic alert canary (Watchdog) → Discord every hour
- [ ] Add DEBUG logging to Alertmanager config for drill windows
- [ ] Document drill procedures as a runbook (`docs/runbooks/drills/slo-burn.md`)
- [ ] Deploy Locust in `load-testing` namespace for reproducible load
- [ ] Schedule quarterly incident drills

## Alerting Pipeline — Post-Fix Verification

After the routing fix (commit `07174da`), the complete alert chain was validated:

| Stage | Verification method | Result |
|-------|---------------------|--------|
| Rule evaluation | `curl /api/v1/rules?type=alert` | Labels now include `namespace=school` |
| Alertmanager receipt | `curl Alertmanager /api/v2/alerts` | Alert arrived with `receiver=['school/school-alerts/discord']` |
| Discord delivery | Visual inspection of `#alerts` | `🔥 FIRING: SchoolSLOSlowBurn` received |

**The full pipeline is confirmed operational.** Prometheus → Alertmanager → Discord
works end-to-end for any alert carrying the `namespace=school` label.

## Lessons Learned

**1. Multi-window alerting has a warm-up cost.** The FastBurn rule requires
BOTH windows above threshold — which is correct for preventing flapping but
means it can miss short, intense incidents. A "very fast burn" rule (5m
window only) is worth adding for exactly this scenario.

**2. "Alert fired" ≠ "Someone was notified."** The drill revealed the
distance between these two events. In production, this is the difference
between a caught incident and an unnoticed outage. Every alerting stack
should have an end-to-end canary that verifies the whole pipeline, not just
the rule evaluation.

**3. The GitOps mitigation worked perfectly.** `git revert` → ArgoCD sync →
rolling update → recovery. Total mitigation time from decision to
recovered service: under 3 minutes. This is the outcome of the entire
Labs 4–5 investment.

**4. Drill value comes from finding gaps, not from confirming assumptions.**
The drill was designed to show the FastBurn alert firing and reaching Discord.
Instead it showed that FastBurn is hard to trigger in short incidents, and
that SlowBurn doesn't currently reach Discord. **Both findings are more
valuable than a "success"** because they represent real production risks.

## References

- SLO definitions: `monitoring/slos/school-slo.md`
- Alert rules: `k8s/base/prometheusrules-alerts.yaml`
- Runbook: `docs/runbooks/README.md#schoolslofastburn`
- Discord alert channel: `#alerts`
- Drill commit: `4ffa78a`
- Mitigation revert: `36bed61`