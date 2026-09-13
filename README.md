# School Management System — SRE Portfolio Project

A 4-service microservices school management system built to demonstrate SRE competency:
- **gateway** (:3000) — API routing, circuit breaker
- **auth** (:3001) — Login, JWT, role-based access
- **academics** (:3002) — Students, sections, classes
- **dashboard** (:3003) — Role-specific aggregated views

## SRE Practices Demonstrated
- SLOs and error budgets (Lab 3)
- Golden signals observability with Prometheus + Grafana (Lab 3)
- Kubernetes deployment on k3d (Lab 4)
- GitOps with ArgoCD (Lab 5)
- SLO-based alerting and blameless postmortems (Lab 6)
- Progressive delivery with Argo Rollouts (Lab 7)
- Chaos engineering experiments (Lab 8)
- Database reliability: migrations, backups, RTO/RPO (Lab 9)

## Status
Lab 0 — Scaffolding
