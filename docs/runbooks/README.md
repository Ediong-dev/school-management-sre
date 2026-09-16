# Runbooks — School Management System

Every alert in `k8s/base/prometheusrules-alerts.yaml` has a section here.

---

## SchoolSLOFastBurn

**Severity:** critical
**Meaning:** Service is burning its 30-day error budget at 14.4× the sustainable
rate. At this rate, the entire month's budget is gone in ~2 days.

**First 5 minutes:**
1. Identify which `service` is burning from the alert's labels.
2. Check the last 15 minutes of that service's logs:
kubectl -n school logs -l app=<service> --tail=200 --since=15m

text
3. Check pod status:
kubectl -n school get pods -l app=<service>

text
4. Check for recent deploys:
argocd app history school

text

**Most likely causes (in order):**
1. Bad config pushed (check `git log --oneline -5 k8s/base/config.env`)
2. Pod crash loop (check `kubectl describe pod <pod>`)
3. Upstream dependency down (check downstream services' health)
4. A dependency is slow (check the P95 latency panel)

**Mitigation:**
- **If recent deploy:** `git revert HEAD && git push` (rollback via GitOps)
- **If pod crash loop:** check logs, restart the deployment
- **If upstream down:** follow the runbook for that service

**Escalation:** page platform lead if not resolved in 15 minutes.

---

## SchoolSLOSlowBurn

**Severity:** warning
**Meaning:** Service is trending toward SLO violation — burning at 6× sustainable
rate. Budget exhausted in ~5 days if not addressed.

**Action:** investigate within business hours. Not a page.
1. Identify the service.
2. Check error rate over 6h.
3. Look for gradual regression.
4. File a ticket with the finding.

Slow burn is the most common cause of "sudden" SLO violations — the budget
was being consumed quietly.

---

## SchoolHighLatencyP95

**Severity:** warning
**Meaning:** Service P95 latency exceeded 500ms for 10 minutes.

**First 5 minutes:**
1. Identify the service.
2. Check logs for downstream timeouts:
kubectl -n school logs -l app=<service> --tail=100

text
3. Look for:
- Slow downstream dependencies
- Connection pool exhaustion (`PoolTimeout` in logs)
- Memory pressure

---

## GatewayDown

**Severity:** critical
**Meaning:** Gateway is down, all user traffic failing.

**Diagnosis:**
kubectl -n school get pods -l app=gateway
kubectl -n school get endpoints gateway
kubectl -n school describe svc gateway

text

**Mitigation:**
- CrashLoop: `kubectl -n school logs -l app=gateway --tail=100`
- No endpoints: readiness probe failing
- All down: `kubectl -n school scale deploy gateway --replicas=4`

---

## General debugging cheat sheet

**Pod won't start:**
kubectl -n school describe pod <pod> | tail -30
kubectl -n school logs <pod> --previous

text

**Service has no endpoints:**
kubectl -n school get endpoints <service>
kubectl -n school get pods -l app=<service> -o wide

text

**ArgoCD OutOfSync but nothing happening:**
argocd app get school --refresh
argocd app sync school

text

**Prometheus not scraping a service:**
kubectl -n school get servicemonitor <service>

Check /targets in the Prometheus UI
text

---

## Escalation policy

| Severity | Response Time | Escalation |
|----------|--------------|------------|
| critical | 5 min | Platform lead @ 15 min |
| warning | 1 hour | Platform lead next business day if unresolved |