# Lab 8 — Chaos Engineering

**Date:** 2026-09-18
**Baseline:** tag `lab7-complete`

## What Was Built

Two hypothesis-driven chaos experiments on the school-management system. Each is
documented as a standalone artifact in `docs/chaos-experiments/` following the
standard hypothesis → method → evidence → conclusion template.

## Experiments

### Experiment 1 — Latency Injection Cascade
**File:** `docs/chaos-experiments/01-latency-cascade.md`

Injected `ACADEMICS_LATENCY_MS=3000` into the academics service via Git commit.
Generated sustained load through the gateway to `/api/dashboard/admin/overview`
(which makes 4 sequential calls to academics).

**Hypothesis:** academics P95 rises to ~3s, dashboard cascades to ~12s, gateway
returns 503s, auth unaffected.

**Result:** Partially falsified. academics P95 rose (to 1.0s — measurement
resolution limit), auth remained flat at 0.095s, gateway returned 14 × 503 during
the injection window. **Dashboard did not cascade in the metrics (0.098s)** — but
users experienced real 503s.

**Key finding:** The cascade happened (proven by gateway 503s), but the P95 metric
didn't reflect it due to histogram bucket resolution and rate-window dilution. The
latency SLO would not have fired under this failure mode.

### Experiment 2 — Simultaneous Pod Kills
**File:** `docs/chaos-experiments/02-simultaneous-pod-kills.md`

Deleted one pod from each of auth, academics, dashboard, and gateway in parallel,
while a load generator continuously hit the full chain and recorded non-200
responses.

**Hypothesis:** K8s recreates all four pods within 30s, zero user-visible errors.

**Result:** Partially falsified. All four pods recovered in ~10 seconds. But
**1 out of 518 requests returned HTTP 503** — one second after the SIGTERM was
dispatched.

**Root cause:** The classic "in-flight request during pod termination" race. The pod
is still listed in the Service EndpointSlice for a brief moment after SIGTERM, so an
in-flight request can be routed to a shutting-down pod.

**Mitigation (documented, not applied):** Add a `preStop` hook with `sleep 5` to all
four services, plus a PodDisruptionBudget.

## Overall Findings

Both experiments produced **falsified hypotheses** — the more useful outcome. Each
revealed a class of operational gap that would not have been visible without chaos
testing:

1. The latency SLO alerting has a measurement-resolution blind spot.
2. The pod-kill mitigation is missing `preStop` hooks — a known K8s pattern that
   most teams implement to achieve true zero-downtime under pod restarts.

Neither gap would have shown up in unit tests or CI. Both require running the
system under realistic conditions and observing user-visible behavior.

## Portfolio Framing

*"I ran two hypothesis-driven chaos experiments on my production-shaped system.
Both hypotheses were falsified, and both falsifications revealed real operational
gaps. The experiments are documented as standalone artifacts with method, evidence,
and follow-up actions — not as success stories."*

## Next

Lab 9: Database reliability — Postgres, migrations, backups, RTO/RPO measurement.
