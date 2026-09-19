# Lab 9 — Database Reliability (Partial)

**Date:** 2026-09-19
**Baseline:** tag `lab8-complete`
**Status:** Parts A, B, C complete. Parts D (migration under load), E (backups) pending.

## Part A — Postgres with Persistent Storage

Deployed a StatefulSet with a volumeClaimTemplates PVC using the local-path
storage class.

**Verification:** Wrote data, deleted the pod, verified data survived pod
recreation. The PVC holds the data — deleting the pod does not delete it.

**Key design choice:** `PGDATA=/var/lib/postgresql/data/pgdata` — a subdirectory
of the mounted volume. Postgres refuses to initialize in a directory with any
existing content (like lost+found), so PGDATA must point to a fresh subdirectory.

## Part B — Zero-Downtime Migration of Auth to Postgres

Migrated auth from an in-memory Python dict to Postgres using the expand/contract
pattern.

**Phase 1 (expand):** Added schema and seed data via a Kubernetes Job running
init.sql. The old in-memory service kept serving — no user impact.

**Phase 2 (contract):** Added DATABASE_URL to the Deployment env. CI rebuilt auth
with Postgres code. ArgoCD rolled. The old pods and new pods served /login
identically during the overlap because the DB was seeded with the same credentials.

**Verification:** Positive login returns valid JWT; wrong password and unknown
user both return 401. No user-visible failure throughout the rollout.

**Design detail:** Password comparison happens inside Postgres via the pgcrypto
extension's `crypt()` function, not in Python. This avoids reimplementing bcrypt
and keeps the comparison constant-time at the DB layer.

## Part C — Alembic for Versioned Migrations

Added alembic as a dependency, created a baseline migration matching the current
schema, and a first real migration adding a `last_login TIMESTAMPTZ` column.

**Design detail:** The new column is nullable. Adding a NOT NULL column with a
default would rewrite the entire table and hold an ACCESS EXCLUSIVE lock for the
duration — unsafe under live traffic. Adding a nullable column is metadata-only.

**Migration Job:** Runs the same school-auth image as the app, executes
`alembic upgrade head`, reads DATABASE_URL from the Secret.

**Verification:**
- alembic_version table shows 0002_add_last_login
- \d users shows the new last_login column
- Login still works

## Incidents

### Incident 1 — YAML indentation error in auth Deployment

**Symptom:** ArgoCD reported ComparisonError: MalformedYAMLError: yaml: line 31:
mapping values are not allowed in this context.

**Root cause:** The env: block was inserted at 20 spaces of indentation instead
of 10. YAML treated it as a continuation of the ports: mapping.

**Fix:** Corrected the indentation.

**Safe-failure observation:** ArgoCD refused to apply the broken manifest and left
the cluster in the last known-good state. This is correct behavior for a GitOps
system — a broken desired state does not become a broken actual state.

### Incident 2 — Alembic Job used the wrong image reference

**Symptom:** The alembic-migrate Job completed with non-zero exit and was cleaned
up before logs could be inspected.

**Root cause:** The Job's image was written as
ghcr.io/ediong-dev/school-auth:main — a fully-qualified reference. The Kustomize
images: transformer matches on the bare name `school-auth` and rewrites
`school-auth:<tag>` to `ghcr.io/ediong-dev/school-auth:<sha>`. A fully-qualified
reference bypasses the transformer, so the Job ran whatever stale image the node
had cached for :main — an image built before alembic was in requirements.

**Fix:** Changed the Job's image to `school-auth:k8s` — the Kustomize-rewritable
form.

**Lesson:** Every image reference in a Kustomize-managed project must be in the
form the transformer matches. Fully-qualified references silently bypass the
transformer and pin the workload to whatever tag was written.

### Incident 3 — Kubernetes Job immutability blocked ArgoCD updates

**Symptom:** After fixing Incident 2, ArgoCD reported OutOfSync with:
`Job.batch "alembic-migrate" is invalid: spec.template: Invalid value ...:
field is immutable`.

**Root cause:** Kubernetes Jobs have an immutable spec.template. ArgoCD's default
behavior uses kubectl apply, which does a three-way merge / patch. Patching a
Job's template is forbidden. When the image reference changed, the update was
rejected.

**Compounding factor:** The Job had already been recreated by ArgoCD from the
pre-fix Git state after a manual delete. So the live Job's template matched
neither the old nor the new Git state.

**Fix:** Added the annotation
`argocd.argoproj.io/sync-options: Force=true,Replace=true` to the Job. This tells
ArgoCD to use `kubectl replace --force` — delete + recreate — instead of apply.
Also added `ttlSecondsAfterFinished: 3600` for automatic cleanup of succeeded Jobs.

**Lesson:** Jobs are a poor fit for pure GitOps reconciliation because of
immutability. The production-grade pattern is to run migrations as ArgoCD
PostSync hooks, which ArgoCD creates after sync, allows to run, then deletes —
keeping them out of the reconciled resource set. The Force+Replace annotation is
a lighter-weight alternative that makes the existing Job resource replace-safe.

## What This Lab Demonstrated

1. Stateful services in Kubernetes — StatefulSet + PVC with data durability across
   pod restarts
2. Zero-downtime schema migration — expand/contract pattern executed entirely via
   GitOps
3. Versioned schema evolution — Alembic migrations tracked in alembic_version
4. Safe failure modes — ArgoCD refuses to apply broken YAML; Kubernetes rejects
   immutable patches; the cluster stays in a known-good state

## Pending (Parts D, E)

- Part D — Migration under live load, measure RTO/RPO
- Part E — Automated backups via Kubernetes CronJob
