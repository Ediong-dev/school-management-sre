markdown
# Lab 1 — SRE Philosophy: Failure Mapping

**Date:** 2026-09-13
**Baseline:** tag `lab0-complete`

## Dependency Graph
         ┌──────────────┐
Browser →│    gateway   │ :3000
         └───────┬──────┘
                 │
        ┌────────┼─────────┐
        ▼        ▼         ▼
    ┌──────┐ ┌──────────┐ ┌───────────┐
    │ auth │ │academics │ │ dashboard │
    │:3001 │ │ :3002    │ │ :3003     │
    └──────┘ └──────────┘ └─────┬─────┘
                                │
                                ▼
                            ┌──────────┐
                            │academics │ ← 4 sequential calls
                            └──────────┘

**Key structural fact:** Academics has two parents (gateway directly, and dashboard indirectly). Auth and dashboard each have one parent (gateway).

## Experiments

### E1 — Kill Academics
| Path | Status | Time | Body |
|------|--------|------|------|
| gateway → auth | 200 | 11ms | token |
| gateway → academics | 503 | 22ms | `[Errno -2] Name or service not known` |
| gateway → dashboard | 503 | 43ms | `[Errno -2] Name or service not known` |
| gateway /health | 200 | 1.5ms | ok |

**Error class:** DNS NXDOMAIN (Docker removes the network alias when a container is stopped).
**Surprise:** Both failing paths returned in under 50ms. Fast fail, clean error propagation.

### E2 — Kill Auth
| Path | Status | Time |
|------|--------|------|
| gateway → auth | 503 | 23ms |
| gateway → academics | 200 | 22ms |
| gateway → dashboard | 200 | 22ms |

**Surprise:** Data paths have zero coupling to auth. Confirms the architecture's isolation design.

### E3 — Kill Dashboard
| Path | Status | Time |
|------|--------|------|
| gateway → auth | 200 | 24ms |
| gateway → academics | 200 | 10ms |
| gateway → dashboard | 503 | 23ms |

**Surprise:** Cleanest possible containment.

### E4 — Kill Gateway
- Gateway `/health`: **connection refused** in 0.0003s (HTTP 000)
- auth direct: 200 · academics direct: 200 · dashboard direct: 200

**Surprise:** 0.3ms. OS-level TCP RST. Fastest possible failure.

### E5 — Slow Academics (4s latency injection)
**First run (accidental — renamed container, DNS lost):**
- gateway: 503 in 55ms — *this was DNS NXDOMAIN, not a timeout*
- Taught us: renaming a container without `--network-alias` removes it from the service DNS.

**Second run (correct — `--network-alias academics`):**
| Path | Status | Time |
|------|--------|------|
| direct to academics | 200 | 4.015s |
| via gateway | 200 | 4.012s |
| via gateway → dashboard | **503** | **10.010s** |

**Diagnosis:** Gateway timeout is 10s. Dashboard's `/admin/overview` makes 4 sequential calls to academics, each 4s → 16s expected total. Gateway timed out at 10s and returned 503. **Dashboard kept working for 6 more seconds after the user gave up** — zombie request.

**Root cause:** Timeout budgets don't cascade correctly. Outer timeout (10s) < total inner work (16s).

**Surprise:** The user experiences the *outermost* timeout, not the innermost one. Also: `docker run --network-alias` was required to preserve service discovery when replacing a Compose-managed container manually.

## Failure Mode Comparison

| Failure mode | Detection time | Retry safety | Danger |
|--------------|----------------|--------------|--------|
| DNS missing | ~50ms | Safe | Low |
| Connection refused | <1ms | Safe | Low |
| Downstream timeout | ~10s | **Unsafe — amplifies load** | High |
| Partial/slow | variable | **Unsafe — causes zombie work** | High |

## Single Points of Failure

- **User-facing SPOF:** gateway. Every browser request goes through it. Killing it takes down all user paths, even though all four data services stay healthy.
- **System-operation SPOF:** none at the container level for this exercise. But gateway is a single replica, so it's a SPOF for user traffic.

## Hypotheses for Future Labs

1. **Lab 3:** The E5 failure signature (10s response) is invisible in error-rate graphs alone. I'll build latency histograms per route so I can see "P99 latency > 1s" firing before "error rate > 1%" does.
2. **Lab 4:** Multiple gateway replicas + readiness probes will eliminate the gateway SPOF.
3. **Lab 6:** I'll write two alerts — `GatewayHighErrorRate` and `GatewayHighLatency` — and prove that only the second one fires during E5.
4. **Lab 8:** Inject slow-dependency again and verify the alert fires *before* the error rate moves. Also test whether a circuit breaker on gateway would prevent the zombie work.

## The Core Lesson

"Down" is the easiest failure to handle. "Slow" is the one that causes real incidents. In four of five experiments, the system failed cleanly in under 50ms. The fifth experiment — the one with the same services all running — took 200× longer to return an error and continued doing work after the user gave up. **That's the failure mode SRE exists to prevent.**
