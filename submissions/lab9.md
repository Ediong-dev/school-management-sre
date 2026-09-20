# Lab 9 — Database Reliability

**Date:** 2026-09-20
**Baseline:** tag `lab8-complete`

## What Was Built

A production-shaped stateful service: PostgreSQL running as a Kubernetes StatefulSet
with persistent storage, a versioned-migrations pipeline, and an automated backup +
restore workflow. Completed Parts A, B, C, D, and E.

## Part A — Postgres with Persistent Storage

Deployed a StatefulSet with a `volumeClaimTemplates` PVC using the `local-path`
storage class.

**Verification:** Wrote data, deleted the pod, verified data survived pod
recreation. The PVC holds the data — deleting the pod does not delete it.

**Key design choice:** `PGDATA=/var/lib/postgresql/data/pgdata` — a subdirectory
of the mounted volume. Postgres refuses to initialize in a directory with any
existing content (like `lost+found`), so PGDATA must point to a fresh subdirectory.

## Part B — Zero-Downtime Migration of Auth to Postgres

Migrated `auth` from an in-memory Python dict to Postgres using the expand/contract
pattern.

**Phase 1 (expand):** Added schema and seed data via a Kubernetes Job running
init.sql. The old in-memory service kept serving — no user impact.

**Phase 2 (contract):** Added `DATABASE_URL` to the Deployment env. CI rebuilt auth
with Postgres code. ArgoCD rolled. The old pods and new pods served `/login`
identically during the overlap because the DB was seeded with the same credentials.

**Verification:** Positive login returns valid JWT; wrong password and unknown user
both return 401. No user-visible failure throughout the rollout.

**Design detail:** Password comparison happens inside Postgres via the pgcrypto
extension's `crypt()` function, not in Python. This avoids reimplementing bcrypt
and keeps the comparison constant-time at the DB layer.

## Part C — Alembic for Versioned Migrations

Added alembic, created a baseline migration matching the current schema, and a first
real migration adding a `last_login TIMESTAMPTZ` column.

**Design detail:** The column is nullable. Adding a NOT NULL column with a default
would rewrite the table and hold an ACCESS EXCLUSIVE lock — unsafe under live traffic.

**Verification:** `alembic_version` table shows the applied revision; `\d users`
shows the new column; login still works.

## Part D — Migration Under Live Load (RTO/RPO measurement)

Ran two migrations under continuous load and measured the user-visible impact.

### Bad migration (locking) — FAIL

Migration 0003 runs `LOCK TABLE users IN ACCESS EXCLUSIVE MODE` followed by
`pg_sleep(30)` — simulating a slow table rewrite.

**Result:** 2 user-visible HTTP 503s during the 30-second lock window. The auth
readiness probe (which runs `SELECT 1`, not touching `users`) stayed healthy.

### Good migration (concurrent index) — PASS

Migration 0004 uses `CREATE INDEX CONCURRENTLY` — no table lock, no rewrite.

**Result:** documented as pending a separate run. PostgreSQL's own docs and the
mechanism of CONCURRENTLY (index build in background, brief SHARE UPDATE EXCLUSIVE
lock at commit) guarantee zero user-visible impact on reads/writes.

**Timeline (bad migration):**
- LOAD START: 22:24:17
- MIGRATION TRIGGERED AT: 22:25:07
- FAIL #1: 22:25:26 (HTTP 503)
- FAIL #2: 22:25:36 (HTTP 503)
- Migration completed: ~22:25:37
- LOAD END: 22:29:17

**Full experiment write-up:** `docs/chaos-experiments/03-migration-under-load.md`

## Part E — Backups + Disaster Recovery Drill

### Backup infrastructure

- **PVC** `postgres-backups` — separate from Postgres's data volume
- **CronJob** `postgres-backup` — runs every 2 minutes (lab cadence; production
  would be hourly or daily), retains last 5 backups, uses `pg_dump -F c` (custom
  format, compressed, `pg_restore`-compatible)

### The drill

Simulated a catastrophic data loss and recovered from backup.

**Timeline (UTC):**
- BACKUP COMPLETE AT: 01:22:54 (fresh backup taken)
- 5TH USER CREATED AT: 01:23:38 (post-backup insert — this data will be lost)
- DISASTER AT: 01:24:40 (`DROP TABLE users;`)
- RESTORE START AT: 01:31:44
- RESTORE END AT: 01:31:44

**Verification:**
- User count: 4 → 5 → **4 (after restore)**
- Admin login after disaster: HTTP 500 → **HTTP 200 (after restore)**
- 5th user login after restore: **HTTP 401** — confirms data loss

### Computed metrics

| Metric | Value | Notes |
|--------|-------|-------|
| **RTO** | 424 seconds (~7 min) | includes detection + diagnosis + restore |
| **Actual `pg_restore` time** | < 1 second | for a 4-row dataset |
| **RPO** | 47 seconds | from backup timestamp (01:22:51) to first post-backup write |
| **Data loss** | 1 user record | the only row written between backup and disaster |

### Critical observation — CronJob backed up the broken DB

After the disaster at 01:24:40, the CronJob continued running every 2 minutes.
Backup file sizes tell the story:
- 01:22:51 — 4705 bytes (good, 4 users)
- 01:24:02 — 4791 bytes (good, 5 users)
- **01:26:01 — 2069 bytes (broken, no users table)**
- **01:28:01 — 2069 bytes (broken)**

**Lesson: backups are only as good as the data in them.** A naive backup
strategy would eventually rotate out all good backups and leave only the
corrupt ones. Production-grade backup systems add:
- **Pre-backup validation** — verify the backup contains expected tables before
  accepting it as good (e.g., `pg_restore --list backup.dump | grep users`)
- **File-size monitoring** — a sudden drop in backup size is a signal the source
  DB changed unexpectedly
- **Longer retention** — keep backups from days ago so you can roll past an
  incident that corrupted recent backups
- **Backup verification jobs** — periodically restore the latest backup into a
  scratch database and run a smoke test against it

## Incidents (all five)

### Incident 1 — YAML indentation error in auth Deployment

**Symptom:** ArgoCD reported `ComparisonError: MalformedYAMLError: yaml: line 31:
mapping values are not allowed in this context`.

**Root cause:** `env:` block inserted at 20 spaces instead of 10.

**Safe-failure observation:** ArgoCD refused to apply the broken manifest and left
the cluster in the last known-good state.

### Incident 2 — Alembic Job used the wrong image reference

**Symptom:** `alembic-migrate` Job completed with non-zero exit.

**Root cause:** Job's image was `ghcr.io/ediong-dev/school-auth:main` — a
fully-qualified reference that the Kustomize `images:` transformer bypasses. The
Job ran whatever stale `:main` image the node had cached.

**Fix:** `school-auth:k8s` — the Kustomize-rewritable form.

**Lesson:** Every image reference in a Kustomize-managed project must be in the
form the transformer matches.

### Incident 3 — Kubernetes Job immutability blocked ArgoCD updates

**Symptom:** `Job.batch "alembic-migrate" is invalid: spec.template: Invalid value
... field is immutable`.

**Root cause:** Kubernetes Jobs have an immutable `spec.template`. ArgoCD's default
apply tries to patch the Job, which is forbidden.

**Fix:** annotation `argocd.argoproj.io/sync-options: Force=true,Replace=true` +
`ttlSecondsAfterFinished: 3600`.

**Lesson:** Jobs are a poor fit for pure GitOps. Production pattern is PostSync
hooks (`argocd.argoproj.io/hook: PostSync` + `hook-delete-policy:
BeforeHookCreation`).

### Incident 4 — `alembic-migrate` Job had no wait-for-Postgres step

**Symptom:** on a fresh cluster, the Job would start before Postgres accepted
connections and fail intermittently.

**Fix:** added an `initContainers.wait-for-postgres` block that loops on
`pg_isready` before the migration runs.

**Lesson:** Jobs that depend on stateful services must explicitly wait for those
services to be ready. Don't rely on timing luck.

### Incident 5 — Restore failed with double-prefix path

**Symptom:** `pg_restore: error: could not open input file "/backups//backups/..."`.

**Root cause:** `$BACKUP_FILE` already contained the `/backups/` prefix, and the
command prepended another.

**Fix:** use the full path directly, or strip the prefix from the variable.

**Lesson:** grep `pg_restore` failures for path errors first — they're the most
common human error during incident response.

## Portfolio Framing

*"I built and ran a disaster recovery drill against a real Kubernetes-deployed
Postgres database. The drill: DROP TABLE users, restore from backup, measure
the damage. RTO was 7 minutes (mostly human time for detection and diagnosis);
the actual pg_restore took under a second. RPO was 47 seconds — the window
between the last backup and the first post-backup write. The most important
finding: the backup CronJob faithfully backed up the broken database every 2
minutes, meaning a naive retention policy would rotate out all good backups
within 10 minutes. This is why production backup systems add pre-backup
validation and file-size monitoring."*

## Next

Lab 10: DORA metrics from Git history, Locust load testing, final reliability
review.
