# Lab 7 — Progressive Delivery with Argo Rollouts

**Date:** 2026-09-17
**Baseline:** tag `lab6-complete`

## What Was Built

- Argo Rollouts controller installed (`v1.10.0`)
- Gateway converted from `Deployment` to `Rollout` with canary strategy
- Two-Service pattern: `gateway-stable` (NodePort) + `gateway-canary` (ClusterIP)
- Rollout steps: 25% → pause 30s → 50% → pause 30s → 100%
- `AnalysisTemplate` querying Prometheus for canary error rate
- Auto-abort on 3+ consecutive analysis failures
- ArgoCD custom health check for Rollout CRD (Lua script in `argocd-cm`)

## The Canary That Actually Works — Basic Mode Limitations

Argo Rollouts' **basic canary mode** (no `trafficRouting` provider) does **not**
send user traffic to the canary. In basic mode:
- `gateway-stable` Service receives 100% of user traffic
- `gateway-canary` Service exists but receives no traffic from the k3d LB
- The analysis can only observe the canary if something queries `gateway-canary` directly

**Consequence:** A demo that only sends load to the front door (`localhost:4000`)
will not exercise the canary and the analysis will pass despite the injection.

**Solution used:** a `canary-tester` pod in-cluster that continuously curls
`http://gateway-canary:3000/...`, generating synthetic traffic to the canary
during the analysis window. This is a real pattern — production teams do this
when they don't have a traffic router configured.

## The Abort — Verified End-to-End

**Injection:** `GATEWAY_FAILURE_RATE=0.5` set on the canary pod template, pushed via Git (commit `976592d`).

**Analysis query:**
```promql
(
  sum(rate(http_requests_total{service="gateway-canary", status=~"5.."}[1m]))
  /
  sum(rate(http_requests_total{service="gateway-canary"}[1m]))
)
or
(0 * sum(rate(http_requests_total{service="gateway-canary"}[1m])))
AnalysisRun history: ✔ 3, ✖ 4 — 7 checks run, 4 failed. On the 4th failure
(> failureLimit: 3), the analysis was marked Failed.

Rollout condition:

text
reason: RolloutAborted
message: "Rollout aborted update to revision 7: Background analysis phase
          error/failed: Metric \"error-rate\" assessed Failed due to
          failed (4) > failureLimit (3)"
Result: Rollout scaled down the canary ReplicaSet and held traffic on the
stable revision. Full automatic recovery — no human intervention.

Timeline
Event	Time (UTC)
Baseline: canary-tester all 200s	~22:41
INJECTED AT	22:42:06
AnalysisRun started	~22:43:49
Analysis: 3 passed, 4 failed	~22:43–22:51
ANALYSIS ABORTED AT	22:51:16
Git revert 61320de pushed	~22:53:30
RECOVERED AT	22:54:07
Total abort time from injection: ~9 minutes.

Bugs Found and Fixed During the Lab
Bug 1 — Kustomize doesn't rewrite references inside CRDs
Kustomize's built-in transformers rewrite configMapRef/secretRef in known
resource kinds (Deployment, Pod, etc.). The Rollout CRD is not in that list,
so the reference to school-config (which Kustomize had renamed to
school-config-<hash> via configMapGenerator) was not rewritten, and pods
failed with CreateContainerConfigError.

Fix: hard-coded the hashed name in the Rollout. Documented as a limitation
of the Kustomize + Rollout integration.

Bug 2 — Rollout conversion split the service label
Converting gateway from Deployment to Rollout introduced two Services
(gateway-stable and gateway-canary), both selected by the ServiceMonitor.
Prometheus's auto-injected service label now has two values instead of one.

Every query hardcoding service="gateway" broke silently.

Fix: analysis query changed to service=~"gateway.*" and later to
service="gateway-canary" for canary isolation.

Bug 3 — AnalysisTemplate returns empty vector when there are no errors
sum(rate(...{status=~"5.."})) / sum(rate(...)) returns an empty vector when
the numerator is empty. The analysis can't evaluate an empty result, so it
reports "nil or empty" and counts it as a failure.

Fix: or (0 * sum(rate(...))) — the PromQL idiom for coercing empty to zero.

Bug 4 — ArgoCD has no built-in health check for Rollout CRD
ArgoCD reports Degraded for Rollouts regardless of actual state, because it
doesn't know how to interpret the Rollout CRD's status conditions.

Fix: custom Lua health check in argocd-cm that reads status.conditions,
looking for Completed/RolloutCompleted → Healthy and Progressing/RolloutAborted → Degraded.

Bug 5 — Analysis query aggregated stable + canary error rates
Initial query used service=~"gateway.*", which summed stable + canary errors.
At 25% canary weight with 50% canary error rate, the aggregate is ~12.5% — and
with the 5m rate window diluting the short injection burst, the aggregate
stayed under 5%. Analysis passed despite a failing canary.

Fix: query service="gateway-canary" only, and use a [1m] rate window
so short bursts register.

Bug 6 — Basic canary mode does not route user traffic to the canary
The most important finding. In basic canary mode without a traffic router,
user traffic goes only to gateway-stable. Canary pods receive no user
requests. The analysis can only see canary behavior if synthetic traffic is
directed at gateway-canary.

Fix: canary-tester pod in-cluster, continuously curling the canary Service.

Production note: with Istio, SMI, or NGINX ingress as a trafficRouting
provider, the canary receives a fraction of real user traffic — no synthetic
tester needed. Basic canary mode on k3s is deliberately conservative, which
means canary demos require synthetic traffic.

Lessons Learned
1. Canary is not what most tutorials imply. "Canary" in Argo Rollouts without
a traffic router means "run a parallel ReplicaSet and let analysis probe it." It
does not mean "shift 25% of user traffic to the new version." That requires
trafficRouting.

2. AnalysisTemplates are code and need validation against production Prometheus.
The empty-vector bug, the label-split bug, and the aggregate-vs-canary bug
each produced silent failures that made the analysis pass when it should have
failed. Validate the query directly (curl /api/v1/query) before committing
the template.

3. Every tooling change has a downstream contract. The Rollout conversion
changed the service label values silently. The ConfigMap hash-suffix broke
the CRD reference silently. Neither was caught by ArgoCD's Synced status.
Only empirical checks (curl, log inspection, alert state) surface these.

4. git revert is the correct mitigation even when progressive delivery
aborts automatically. The system aborts the rollout, but the config is
still in Git. Reverting the commit restores the desired state and prevents
the failed revision from being retried on the next reconcile.

5. Nine minutes is too slow for real-time canary analysis. In production,
this would be tuned: shorter analysis intervals, faster pod scheduling,
pipelined rollouts. The 9-minute window is an artifact of running on k3s
without a traffic router and with modest compute.