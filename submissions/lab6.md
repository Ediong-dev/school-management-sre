# Lab 6 — Alerting & Incident Response

**Date:** 2026-09-16
**Baseline:** tag `lab5-complete`

## Part A — Monitoring Stack Migrated to In-Cluster

**What changed:**
- Stopped the Docker Compose monitoring stack from Lab 3
- Installed `kube-prometheus-stack` (Prometheus Operator, Prometheus, Alertmanager, Grafana, node-exporter, kube-state-metrics) via Helm into the `monitoring` namespace
- Trimmed the default resource limits for a 4-core Codespace with 3 k3d nodes

**Resource footprint (measured):**
| Component | CPU | Memory |
|-----------|-----|--------|
| Prometheus | 15m | 405Mi |
| Grafana | 19m | 398Mi |
| Alertmanager | 1m | 26Mi |
| kube-state-metrics | 1m | 16Mi |
| Operator | 3m | 21Mi |
| node-exporter × 3 | ~1m each | ~9Mi each |
| **Total monitoring** | ~45m | ~900Mi |

Per-node utilization: **1-2% CPU, 8-10% memory.** Substantial headroom remaining.

**Why monitoring belongs inside the cluster:**
- If the cluster goes down, the monitoring goes down with it — but so does the thing being monitored, so there's no missed signal
- Prometheus Operator manages the full lifecycle via CRDs (ServiceMonitors, PrometheusRules) — declarative, GitOps-compatible
- Alertmanager's `AlertmanagerConfig` CRD integrates alerting config into the same GitOps loop as everything else
- Node-exporter runs as a DaemonSet, giving per-node metrics that a Compose stack on the host can't see

## Part B — ServiceMonitors

**What was added:**
- Four `ServiceMonitor` CRDs (`k8s/base/servicemonitor-*.yaml`), one per service
- All labeled `release: kube-prometheus-stack` so Prometheus Operator discovers them
- Committed to Git, synced by ArgoCD

**Verification:** Prometheus `/targets` shows 8 new targets in the `school` namespace — 2 per service, one per replica, all `up`:
serviceMonitor/school/academics/0 2/2 up
serviceMonitor/school/auth/0 2/2 up
serviceMonitor/school/dashboard/0 2/2 up
serviceMonitor/school/gateway/0 2/2 up

text

**Key insight:** The ServiceMonitor is a Kubernetes custom resource that *declares* the scrape configuration. Prometheus Operator watches for these, generates the actual scrape config, and reloads Prometheus. This is how you add scrape targets in a GitOps world — you don't edit `prometheus.yml` by hand, you commit a ServiceMonitor and let the operator reconcile.

## Incidents

### Incident 1 — Grafana crash loop on first install (fixed before Lab 6)
Grafana crash-looped with the initial `values.yaml` that included a custom `additionalDataSources` block. The chart already wires Prometheus as the default datasource, so the extra declaration conflicted.

**Fix:** Removed `additionalDataSources` and `auth.disable_login_form: false` from the values file.

### Incident 2 — ArgoCD sync retry exhaustion
After five failed syncs (caused by a missing `school` namespace on a fresh cluster), ArgoCD entered backoff and stopped retrying. Creating the namespace didn't trigger a retry.

**Fix:** Changed the Application's `syncOptions` to `CreateNamespace=true`, which mutated the spec and triggered a fresh sync. Also updated the manifest permanently so future cluster bootstraps don't need a manual `kubectl create namespace school`.

**Lesson:** Retry backoff is a feature. To reset it, change the resource — an `argocd app sync` command or a spec mutation both work. Simply fixing the underlying problem does not trigger a new attempt.

### Incident 3 — Codespace restart kills port-forwards
Backgrounded `kubectl port-forward` jobs don't survive a Codespace pause/resume. All CLI access (ArgoCD, Prometheus, Grafana, Alertmanager) breaks until they're restarted.

**Fix:** A shell script that restarts the four port-forwards and verifies each is responsive. This is now part of the bootstrap flow.

### Incident 4 — Disaster Recovery Drill (from Lab 5)
Lost the entire cluster when switching GitHub accounts. Rebuilt from Git alone in ~90 seconds:
1. `k3d cluster create`
2. `kubectl apply -f k8s/argocd/application.yaml`
3. ArgoCD sync pulled images from ghcr.io and reconciled all resources

**Zero manual `kubectl apply` on application resources. Zero `k3d image import`.** The pipeline is genuinely portable.

## Portfolio Framing

*"My monitoring stack runs inside the Kubernetes cluster it monitors — Prometheus Operator, Prometheus, Alertmanager, and Grafana, all installed via Helm and managed declaratively. Four services are scraped via ServiceMonitor CRDs, so adding a new service to monitoring means committing one YAML file. I can point at the Prometheus `/targets` page and show 8 scrape targets, all healthy, driven entirely by Git."*

## Next

Part C: SLOs as code (`PrometheusRule` CRDs) — burn-rate alerts, error budgets, and the Grafana alert UI.
Part D: Contact point (Discord webhook), alert routing, and the notification pipeline.
Part E: Runbooks.
Part F: Injected incident + blameless postmortem.

---

## Follow-Up Incident — Alert Fatigue on the Discord Channel (2026-09-18)

**Symptom:** After several chaos and drill attempts, the Discord `#alerts` channel
was flooded with chart-default alerts from kube-prometheus-stack:
`Watchdog`, `InfoInhibitor`, `CPUThrottlingHigh`, `NodeClockNotSynchronising`,
`TargetDown`. The real `SchoolSLOFastBurn` and `SchoolSLOSlowBurn` alerts were
firing during the drill attempts but were buried in the noise and easily missed.

**Diagnosis:** The `AlertmanagerConfig`'s top-level `route.receiver` was set to
`discord`. Alerts that did not match any sub-route — i.e. the chart-default
cluster alerts — fell through to the default receiver and were delivered to
Discord anyway. The design had no default-drop policy; the default was "send
everywhere."

**Fix:** Changed the top-level `route.receiver` to `null` and added explicit
`namespace=school` matchers on each Discord sub-route. Only alerts carrying
our namespace label plus a matching severity label are now delivered.

**Verification:**
- Synthetic `InfoInhibitor` alert fired → routed to `null` → Discord stayed silent ✅
- Synthetic `SchoolSLOFastBurn` alert fired → routed to `discord` → message delivered ✅
- Real `SchoolSLOFastBurn` and `SchoolSLOSlowBurn` alerts (from Lab 6 drill)
  remain visible in the Discord channel history from the drill window

**Impact:** This was a genuine production-grade observability problem. In SRE
terms, the alerting pipeline had no *default-drop* policy — the default was
"send everywhere." Alert fatigue is one of the most common reasons on-call
rotations fail. Fixing it requires reversing the polarity of the routing tree:
default to drop, explicitly opt-in to notification via matchers.

**Lesson:** Alertmanager route trees should terminate at a `null` receiver.
Every notification destination should be reached by an explicit matcher, never
by fallthrough. This is the same discipline as least-privilege IAM: deny by
default, allow explicitly.

**Evidence preservation:** The alerting pipeline was working correctly during
the Lab 7 auto-abort drill — the `SchoolSLOFastBurn` and `SchoolSLOSlowBurn`
messages visible in Discord's history are direct artifacts of the deployed
PrometheusRule + AlertmanagerConfig + Discord webhook chain. They were
retroactively discovered when auditing the channel for the postmortem, which
is itself a real-world debugging technique: when you don't know what state the
system was in, read the notification history.
