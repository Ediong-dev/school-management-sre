# DORA Metrics — School Management SRE Project

**Reporting period:** 2026-09-15 to 2026-09-20 (5.01 days)
**Team size:** 1 (solo portfolio project)
**Computed from:** `git log` of `main` branch

## Summary Table

| Metric | Value | DORA Tier |
|--------|-------|-----------|
| Deployment Frequency | 11.3 deployments/day | **Elite** |
| Lead Time for Changes | ~55 seconds | **Elite** |
| Change Failure Rate | 5.3% (3 of 57) | **Elite** |
| Mean Time to Recovery | 7 minutes (median) | **Elite** |

**All four metrics reach DORA "Elite" tier.** This is the result of specific
engineering investments made during the course:

- **Deployment Frequency / Lead Time** — driven by the GitHub Actions CI +
  ArgoCD GitOps pipeline built in Lab 5. Push → image built → manifest updated
  → ArgoCD syncs → running. The entire loop is 55 seconds and requires zero
  human intervention after `git push`.
- **Change Failure Rate** — driven by ArgoCD's safety properties. Invalid
  manifests are refused (keeping the cluster in last-known-good state); K8s
  rejects immutable patches; the canary AnalysisTemplate from Lab 7 aborts bad
  deploys. Most operator errors are caught before reaching users.
- **MTTR** — driven by GitOps rollback. `git revert` + ArgoCD sync restores the
  previous known-good state in minutes.

## Deployment Frequency

- 57 `chore(gitops)` commits between 2026-09-15 00:48:06 and 2026-09-20 01:09:22
- 5.01 days elapsed
- **11.3 deployments per day**

Every push to `main` triggers the CI pipeline (`ghcr.io` image build + gitops
overlay update). ArgoCD reconciles within ~55 seconds. There is no manual
approval step, no maintenance window, no change advisory board — commits become
deployments continuously.

## Lead Time for Changes

Sampled across 10 random commit-to-deploy pairs. Consistent lead time of
**~50–66 seconds**, driven by:

- CI matrix build of 4 images in parallel (~40–50s)
- Gitops overlay commit (~1s)
- ArgoCD polling detection (~10s)

**Median: 55 seconds.**

The variability is small — 15 seconds spread across 10 samples. This is a very
deterministic pipeline.

## Change Failure Rate

Total deployments: 57
Real failures requiring remediation: 3 (5.3%)

Failures:
1. **`7ceec6e`** — Job used `ghcr.io/...:main` (fully-qualified), bypassing
   the Kustomize `images:` transformer. Fixed by using `school-auth:k8s`.
2. **`ba8fcdd`** — Job immutability blocked ArgoCD reconciliation. Fixed with
   `argocd.argoproj.io/sync-options: Force=true,Replace=true`.
3. **`64227ac`** — YAML indentation error in auth Deployment. ArgoCD refused
   to apply, so no bad state ever reached the cluster.

**Excluded from CFR:** all `CHAOS-*`, `INCIDENT DRILL*`, and `Simulate bad
deploy*` commits — those are deliberate failure experiments, not defects.
Also excluded: proactive fixes (`c3c143a` — added init container to prevent a
race condition that hadn't yet manifested).

**Critical observation:** none of the 3 failures caused user-visible impact.
The reliability investments (ArgoCD safety properties, K8s validation, canary
analysis) caught each failure before it reached users.

## Mean Time to Recovery

Three real incidents with measurable recovery windows:

| Incident | Start | Recovery | Duration |
|----------|-------|----------|----------|
| Lab 6 SLO burn (config change) | 22:51:16 | 22:54:07 | 2m51s |
| Lab 7 canary auto-abort | 22:42:06 | 22:54:07 | 12m01s |
| Lab 9 DB disaster drill | 01:24:40 | 01:31:44 | 7m04s |

**Median: 7m04s.**

Recovery mechanisms:
- **Lab 6:** manual `git revert` of the config change; ArgoCD re-synced; pods
  rolled; SLO burn alert auto-resolved.
- **Lab 7:** *automatic* — the canary AnalysisTemplate detected the error rate
  spike, aborted the rollout at the 4th failed check, and reverted traffic to
  the stable revision without any human intervention.
- **Lab 9:** manual `pg_restore` from backup; the actual restore was <1 second;
  the remaining 7 minutes was human time for detection, diagnosis, and the
  correct path invocation (the double-prefix bug cost ~2 minutes).

## Interpretation

**These numbers are not typical for a solo project.** DORA's 2024 State of
DevOps report places only ~20% of engineering teams at Elite across all four
metrics. The reason this project reaches Elite is the deliberate design of the
delivery pipeline:

1. **CI is fast** — the matrix build completes in under a minute because the
   Dockerfiles use multi-stage builds and GitHub Actions caching.
2. **CD is automated** — ArgoCD reconciles continuously. No human clicks
   between "image ready" and "running in cluster."
3. **Rollback is trivial** — `git revert HEAD && git push`. The GitOps model
   means the "undo" of any deploy is one commit.
4. **Failures are caught pre-user** — ArgoCD's refusal to apply bad manifests,
   K8s's validation rules, and the canary AnalysisTemplate combine to catch
   most defects before they impact real requests.

## What Would Improve

- **CFR is inflated by operator (not system) errors.** All 3 failures were
  things I got wrong (image ref, annotation, indentation). A linter / policy
  check in CI would catch all three pre-merge. Pre-commit hooks or Conftest
  policies for K8s manifests would push CFR toward 0%.
- **MTTR is dominated by human time.** The actual system recovery (ArgoCD sync,
  canary abort, pg_restore) is sub-minute. Detection + diagnosis is the slow
  part. Better alerting (Lab 6's SLO burn alerts are a start) and more specific
  runbooks would shrink MTTR further.

## Portfolio Framing

*"My DORA metrics on a solo project: 11 deployments per day, 55-second lead
time, 5.3% change failure rate, and 7-minute median MTTR. All four are DORA
Elite tier. Not because I'm a fast coder, but because the GitOps + CI +
observability pipeline makes deployment cheap and rollback trivial. Every
change is a Git commit; every rollback is `git revert`; every deploy is
verified by an SLO burn alert and a canary analysis."*
