# Chaos Experiment 2 — Simultaneous Pod Kills

**Date:** 2026-09-18
**Experimenter:** Senyene
**Status:** Complete — hypothesis falsified, meaningful finding

## Hypothesis

If one pod from each of the four services (auth, academics, dashboard, gateway)
is deleted simultaneously:
1. Kubernetes will recreate all four within 30 seconds
2. Zero user-visible errors will occur (0 failures)

## Method

- Load: continuous curl loop at ~3 req/s to `/api/dashboard/admin/overview` for 180s
- Kills: `kubectl delete pod --wait=false` for one pod per service, dispatched in parallel
- Timing: kills dispatched ~94 seconds into the 180-second load window
- Measure: non-200 responses and their timestamps; pod recreation time

## Timeline (UTC)

| Event | Time |
|-------|------|
| BASELINE verified | 23:18:00 |
| LOAD START | 23:18:22 |
| KILLS AT | 23:19:56 |
| **FAIL (HTTP 503)** | **23:19:57** |
| LOAD END | 23:21:22 |

## Results

**User-visible failures:** 1 out of 518 requests (0.19% error rate)
**Failure timestamp:** 23:19:57 — exactly **1 second after kills dispatched**
**Pod recreation time:** All 4 new pods `1/1 Running` within **~10 seconds**
**Recovery MTTR:** ~10 seconds to full availability

## Hypothesis Scorecard

| Prediction | Result |
|-----------|--------|
| All pods recovered within 30s | ✅ Validated — ~10 seconds |
| Zero user-visible errors | ❌ **Falsified** — 1 failure |

## Root Cause of the Single Failure

The failed request arrived at 23:19:57, one second after SIGTERM was
delivered to the pods being deleted. During graceful shutdown:

1. kubelet sends SIGTERM → app begins shutdown
2. Pod is still listed in the Service's EndpointSlice for a brief moment
3. An in-flight request routed to the terminating pod → connection reset
4. Client received HTTP 503

This is the classic "in-flight request during pod termination" failure mode.
It happens because there is no delay between the pod being marked for
termination and its removal from the load balancer's endpoint list.

## Why Only 1 Failure

Each service has 2+ replicas (gateway has 4). Only the pods *being killed*
had the brief window of unreachability. The other replicas continued serving
traffic normally. The failure surface was ~1 second × 3 req/s ≈ 1-3 requests.
We observed exactly 1.

## Mitigation (Not Applied — Documented for Later)

The standard fix is a `preStop` hook that delays actual shutdown:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["sh", "-c", "sleep 5"]
With this, kubelet:

Marks pod for termination

Removes pod from EndpointSlice

Runs preStop (5s delay while traffic drains)

Sends SIGTERM

App shuts down

By the time SIGTERM is delivered, no traffic is being routed to the pod.
The failure mode is eliminated.

Additionally, a PodDisruptionBudget (PDB) enforces minimum availability
during voluntary disruptions (drains, upgrades), which is a required
production practice.

Conclusion
K8s self-healing works: 4 correlated pod kills recovered in ~10 seconds
with only 1 user-visible failure.

Zero-downtime was not achieved: the failure count of 1 is a real, honest
finding. The mitigation (preStop hook + PDB) is well-understood and would
eliminate the failure. This is a known pattern that many production teams
implement to achieve true zero-downtime under pod restarts.

Portfolio value: A chaos experiment that predicted zero failures,
observed one, diagnosed its cause to the second, and identified the
industry-standard fix — without needing to re-run the experiment.

Follow-Up Actions
□ Add preStop: sleep 5 to all four Deployments/Rollout
□ Add PodDisruptionBudget for each service
□ Re-run this experiment to validate the fix (future lab or reference)
□ Add terminationGracePeriodSeconds: 30 to pods (default is already 30s but worth explicit)
Observations
A single failure is a valid finding. Reporting "0 failures" here would
have been inaccurate. The 1 failure is the whole point.

Correlation between the failure timestamp and kill timestamp is exact.
This is why recording timestamps matters — it turns "we saw an error" into
"we saw an error because of the kill at 23:19:56".

The observed impact (~1 failed request) is very low. For most SLAs,
this would still be within the error budget for a single event. But the
capability to eliminate it exists.

