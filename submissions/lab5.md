# Lab 5 — CI/CD and GitOps

**Date:** 2026-09-15
**Baseline:** tag `lab4-complete`

## What Was Built

- **Kustomize restructure:** `k8s/base/` (environment-agnostic) + `k8s/overlays/gitops/` (image tags set by CI)
- **GitHub Actions CI** (`.github/workflows/ci.yaml`): matrix build of 4 services → push to ghcr.io → update gitops overlay with commit SHA → commit and push
- **ArgoCD Application** watching `k8s/overlays/gitops` on `main`, with `automated.prune: true` and `automated.selfHeal: true`
- **Public ghcr.io packages** so k3d can pull without registry credentials
- **configMapGenerator** for auto-rollout on config change

## The Loop
git push
→ GitHub Actions builds 4 images in parallel (matrix)
→ pushes to ghcr.io with :SHA and :main tags
→ kustomize edit set image ...SHA in k8s/overlays/gitops/kustomization.yaml
→ commits as github-actions[bot]
→ ArgoCD polls main, sees new commit, renders Kustomize, diffs, syncs
→ K8s rolls pods one at a time (readiness-gated)

text

## Timing

- First CI run: 51s (parallel matrix — auth 17s, gateway 17s, dashboard 18s, academics 18s; update-gitops 5s)
- ArgoCD sync: under 3 minutes from push
- End-to-end lead time: **under 4 minutes from commit to deployed image**

## Incidents

### Incident 1 — ArgoCD CRD exceeds annotation size
`kubectl apply` failed:
The CustomResourceDefinition "applicationsets.argoproj.io" is invalid:
metadata.annotations: Too long: may not be more than 262144 bytes

text

**Root cause:** client-side apply stores the entire manifest in a `last-applied-configuration` annotation. ApplicationSet CRD's schema exceeds 256 KiB.

**Fix:** `kubectl apply --server-side --force-conflicts`. Server-side apply tracks field ownership on the API server, not in an annotation.

**Lesson:** Client-side apply has a hard 256 KiB limit. Server-side apply is the future for large CRDs (ArgoCD, Istio, Prometheus Operator all require it).

### Incident 2 — Literal `<password>` in shell
Bash interpreted `<password>` as stdin redirection, not a placeholder. Fix: use the actual retrieved value.

**Lesson:** `<...>` and `$...` placeholders must be substituted, not typed.

### Incident 3 — ConfigMap changes do NOT trigger pod rollout
After GitOps sync, ArgoCD reported the ConfigMap as `Synced`. The `academics-WRONG` URL from the bad deploy was deployed — but the running pods kept succeeding, because their env vars were read from the *old* ConfigMap at container start.

**Root cause:** Kubernetes reads env vars from ConfigMaps at container start. It does not watch ConfigMaps and restart pods when they change. GitOps syncs resources, but pods restart only when the pod template changes.

**Fix:** `configMapGenerator` in Kustomize. Appends a hash of the ConfigMap contents to its name. When contents change, the name changes, which changes the Deployment's `envFrom.configMapRef.name`, which changes the pod template, which triggers a rolling update.

**Verification:** After the fix, changing the ConfigMap caused exactly **2 of 4** Deployments (dashboard, gateway — the only ones referencing the ConfigMap) to roll. Auth and academics stayed at 18m age. **Correct, minimal blast radius.**

**Lesson:** "ConfigMap changed" ≠ "pods picked up the change." The hash-suffix pattern makes pod template changes automatic when config changes.

### Incident 4 — Push rejected by CI bot race
After pushing a commit, GitHub Actions' bot pushed its own `chore(gitops)` commit. Subsequent `git push` was rejected as non-fast-forward.

**Fix:** `git pull --rebase && git push`. Because the bot's commit and ours touched different files, rebase is clean.

**Lesson:** In GitOps repos where bots commit, `git pull --rebase` is standard. Set `git config --global pull.rebase true` to avoid the pattern entirely.

### Incident 5 — Self-heal speed surprised
Manual `kubectl scale deploy gateway --replicas=5` was reverted to 2 replicas **within ~5 seconds**. ArgoCD's controller detects drift continuously, not on a 3-minute polling cycle.

**Observation:** GitOps closes the drift class that bit us in Lab 2 (orphan container). No manual intervention, no ambiguity — desired state always wins.

## DORA Metrics (measured)

| Metric | Value |
|--------|-------|
| Deployment frequency | Every push to main |
| Lead time for changes | ~4 min (51s CI + ~3 min ArgoCD) |
| Change failure rate | 0 recorded (all "bad" deploys were intentional) |
| MTTR | `git revert` + ArgoCD sync ≈ 3 min |

## Self-Heal Demo

- Manual: `kubectl scale deploy gateway --replicas=5`
- Within ~5 seconds: back to 2 replicas
- No manual intervention, no scheduled run — ArgoCD reconciled continuously

## Rollback Demo

- Bad deploy: change `ACADEMICS_URL` in `k8s/base/config.env`, push
- ArgoCD syncs, ConfigMap hash changes, dashboard and gateway pods roll with bad URL
- `/api/dashboard/admin/overview` returns 503
- Rollback: `git revert HEAD && git push`
- ArgoCD syncs revert, pods roll back, endpoint healthy again
- Total recovery time: under 3 minutes

## Portfolio Framing

*"I have a full CI/CD + GitOps pipeline. Pushing to main builds 4 container images in parallel (51s), publishes them to ghcr.io, and commits the new SHAs to a Kustomize overlay. ArgoCD watches that overlay and reconciles the cluster continuously — I verified manual drift is reverted within 5 seconds. Deploys are `git push`, rollbacks are `git revert`, end-to-end lead time is under 4 minutes. I also debugged and fixed the Kubernetes ConfigMap-doesn't-roll-pods problem using Kustomize's `configMapGenerator` with content-hash suffixes."*

## What This Does NOT Protect Against

- Git as SPOF (if GitHub is down, no new deploys)
- Bad commits that pass tests but break production (need canary — Lab 7)
- Secrets in Git (JWT secret hardcoded — needs SealedSecrets)
- No behavioral tests in CI (only verifies images build)

## Next

Lab 6: SLO-burn-rate alerting, Alertmanager, runbooks, and a blameless postmortem.