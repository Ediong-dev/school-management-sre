# Capacity Analysis — School Management SRE Project

**Date:** 2026-09-22
**Load testing tool:** Locust 2.32.0, deployed in-cluster
**Target:** `http://gateway-stable:3000` (the stable Service from the Lab 7 Rollout)
**Test duration:** 2 minutes per level
**Test ramp:** 2 users/second

## Summary

| Concurrent users | Total requests | Failures | Throughput | Median | P95 | P99 |
|------------------|----------------|----------|------------|--------|-----|-----|
| 10 | 1163 | 0 (0%) | 9.73 req/s | 26 ms | 97 ms | 170 ms |
| 50 | 4788 | 0 (0%) | 40.05 req/s | 52 ms | 550 ms | 940 ms |
| 200 | 5872 | **817 (13.91%)** | **49.19 req/s** | **430 ms** | **6400 ms** | **8300 ms** |

**Breaking point: between 50 and 200 concurrent users.** Throughput scales
linearly until ~50 users, then plateaus. At 200 users, the system is saturated
and user-visible errors appear.

## Scaling Characteristics

### Linear scaling: 10 → 50 users

- 5× users, 4.1× throughput, sub-second latencies
- No failures
- The system has spare capacity at this level

### Saturation: 50 → 200 users

- 4× users, 1.23× throughput
- Median latency 8× higher, P95 latency 12× higher
- 13.91% of requests fail

**Interpretation:** beyond ~50 concurrent users, additional load is not served —
it accumulates in queues. The system is throughput-bound somewhere between 50
and 200 users, and the queue depth grows fast enough to trigger timeouts.

## The Bottleneck — Endpoint-Level Analysis

At 200 users, the failure distribution is decisive:

| Endpoint | Requests | Failures | Failure rate |
|----------|----------|----------|--------------|
| `/api/dashboard/admin/overview` | 2785 | **815** | **29.26%** |
| `/api/academics/students` | 1971 | 2 | 0.10% |
| `POST /api/auth/login` | 200 | 0 | 0% |
| `GET /health` | 916 | 0 | 0% |

**Only the dashboard endpoint fails meaningfully.** Everything else holds.

### Root cause

The dashboard's `/admin/overview` endpoint makes **4 sequential calls** to
academics: `/students`, `/teachers`, `/sections`, `/classes`. Under normal
load, each call takes ~20 ms, so the total is ~80 ms.

Under heavy load:
- Each call's individual latency grows (academics is queuing)
- The calls are sequential — there is no parallelism
- The gateway has a 10-second timeout on the dashboard call
- When 4 sequential calls exceed 10 seconds total, the gateway returns 503

**This is the exact failure signature identified in Lab 1 Experiment 5
during the initial failure mapping.** The chaos experiment predicted it; the
capacity test confirmed it at scale.

### Error class

All 817 failures are **HTTP 503**, not `connection refused` and not `gaierror`.
This means:
- The gateway pod was healthy (not crashed, not unreachable)
- The gateway's httpx client reached its 10s timeout and correctly returned 503
- No container was OOMKilled
- No node ran out of resources

**The failure is a design limitation, not an infrastructure failure.**

## Fixing the Bottleneck — Three Approaches

### Approach 1 — Parallelize the dashboard's downstream calls

The 4 calls to academics are independent — nothing requires them to be sequential.
Rewriting them with `asyncio.gather` would reduce the total time from 4T to T.

**Expected impact:** 4× fewer sequential hops → breaks the cascade → the
dashboard endpoint should hold under load as well as the others.

### Approach 2 — Cache the aggregates

The overview data changes infrequently. A 10–30 second cache (Redis, or even
in-process with a short TTL) would eliminate most of the load on academics.

**Expected impact:** Reduces academics load by ~4× per dashboard request,
pushing the breaking point much higher.

### Approach 3 — Increase replicas

The current setup has 2 dashboard pods and 2 academics pods. Scaling to 4 each
would help but not solve it — the fundamental issue is the serial nature of the
calls, which scales linearly with load no matter how many replicas exist.

**Not recommended as a primary fix.** Useful as a secondary mitigation.

### Recommended fix

**Approach 1 (parallelize) + Approach 2 (cache).** Together, they reduce the
dashboard's effective load on academics by ~8× and eliminate the sequential
timeout cascade.

## What Held Under Load

Notably, the following remained healthy at 200 concurrent users:

- **Auth** — 200 login requests, 0 failures. Password hashing via pgcrypto is
  computationally expensive, but 2 auth replicas absorbed the load.
- **Health checks** — 916 requests, 0 failures. Readiness probes were not
  affected by application load.
- **Direct academics calls** — 1971 requests, 2 failures (0.10%). The academics
  service itself scales well when not gated by a serialized aggregation.

## Interpretation

**The system's capacity envelope is roughly 50–80 concurrent users for the
current configuration.** Above that threshold, the dashboard endpoint begins to
fail, which is user-visible (the admin overview is one of the primary dashboard
screens).

**This is a fixable design problem, not an infrastructure limit.** The rest of
the system proved it can handle load. The dashboard's use of 4 serial
downstream calls created an artificial bottleneck.

## Methodology Notes

- All tests run against the in-cluster `gateway-stable` Service, matching the
  path real users take
- Load generator ramps at 2 users/second to avoid a thundering-herd artifact
- All tests complete in 2 minutes, avoiding time-based variance
- Failures are measured per request, not per session
- The CronJob was suspended during the tests to eliminate background noise

## Portfolio Framing

*"I load-tested the system at 10, 50, and 200 concurrent users. The system
scaled linearly up to ~50 users. Beyond that, throughput plateaued and the
dashboard endpoint began failing at 29% because it makes 4 sequential calls to
a downstream service and hits the gateway's 10-second timeout. This is the same
cascade failure mode I predicted in the Lab 1 chaos experiment — and the
capacity test confirmed it at scale. The fix is to parallelize the calls with
asyncio.gather and add caching. The rest of the system held under load, which
tells me the bottleneck is specific and fixable, not architectural."*