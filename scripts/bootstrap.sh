#!/usr/bin/env bash
#
# bootstrap.sh — Rebuild the entire School Management SRE cluster from Git.
#
# This script assumes:
#   - Docker is running
#   - k3d, kubectl, helm are installed
#   - You are in the repository root
#
# It does NOT need a pre-existing cluster. It creates one, installs the
# cluster-level components (ArgoCD, Argo Rollouts, kube-prometheus-stack),
# then hands off to ArgoCD for application-level resources.
#
# Idempotent: safe to re-run. Each step checks for existing state.

set -euo pipefail

CLUSTER_NAME="school"
ARGOCD_NAMESPACE="argocd"
ARGO_ROLLOUTS_NAMESPACE="argo-rollouts"
MONITORING_NAMESPACE="monitoring"
APP_NAMESPACE="school"

log()  { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
warn() { printf "\n\033[1;33m!!  %s\033[0m\n" "$*"; }
die()  { printf "\n\033[1;31mXX  %s\033[0m\n" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
log "Checking prerequisites"

for cmd in docker k3d kubectl helm; do
  command -v "$cmd" >/dev/null 2>&1 || die "Required command '$cmd' not found in PATH."
done

docker info >/dev/null 2>&1 || die "Docker daemon is not running."

if ! command -v argocd >/dev/null 2>&1; then
  warn "argocd CLI not found. The bootstrap will still work, but you'll want"
  warn "to install the CLI later for interacting with the ArgoCD Application."
fi

[[ -f k8s/argocd/application.yaml ]] || die "Not in the repo root (k8s/argocd/application.yaml not found)."

# ---------------------------------------------------------------------------
# Cluster
# ---------------------------------------------------------------------------
log "Creating k3d cluster '$CLUSTER_NAME' (no-op if it already exists)"

if k3d cluster list 2>/dev/null | awk '{print $1}' | grep -qx "$CLUSTER_NAME"; then
  echo "Cluster '$CLUSTER_NAME' already exists."
else
  k3d cluster create "$CLUSTER_NAME" \
    --agents 2 \
    --port "4000:30000@loadbalancer" \
    --port "9091:30090@loadbalancer"
fi

kubectl config use-context "k3d-${CLUSTER_NAME}" >/dev/null
kubectl config set-context --current --namespace="$APP_NAMESPACE" >/dev/null

log "Waiting for nodes to be Ready"
kubectl wait --for=condition=Ready nodes --all --timeout=120s

# ---------------------------------------------------------------------------
# ArgoCD
# ---------------------------------------------------------------------------
log "Installing ArgoCD"

if kubectl get ns "$ARGOCD_NAMESPACE" >/dev/null 2>&1; then
  echo "Namespace '$ARGOCD_NAMESPACE' already exists. Skipping install."
else
  kubectl create namespace "$ARGOCD_NAMESPACE"
  kubectl apply -n "$ARGOCD_NAMESPACE" --server-side --force-conflicts \
    -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

  echo "Waiting for ArgoCD server to be available..."
  kubectl -n "$ARGOCD_NAMESPACE" wait \
    --for=condition=available \
    --timeout=300s \
    deployment/argocd-server
fi

# ---------------------------------------------------------------------------
# Argo Rollouts
# ---------------------------------------------------------------------------
log "Installing Argo Rollouts"

if kubectl get ns "$ARGO_ROLLOUTS_NAMESPACE" >/dev/null 2>&1; then
  echo "Namespace '$ARGO_ROLLOUTS_NAMESPACE' already exists. Skipping install."
else
  kubectl create namespace "$ARGO_ROLLOUTS_NAMESPACE"
  kubectl apply -n "$ARGO_ROLLOUTS_NAMESPACE" --server-side --force-conflicts \
    -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

  echo "Waiting for Argo Rollouts controller..."
  kubectl -n "$ARGO_ROLLOUTS_NAMESPACE" wait \
    --for=condition=available \
    --timeout=180s \
    deployment/argo-rollouts
fi

# ---------------------------------------------------------------------------
# kube-prometheus-stack
# ---------------------------------------------------------------------------
log "Installing kube-prometheus-stack"

if ! helm repo list 2>/dev/null | grep -q prometheus-community; then
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
fi
helm repo update >/dev/null

if helm list -n "$MONITORING_NAMESPACE" 2>/dev/null | grep -q kube-prometheus-stack; then
  echo "kube-prometheus-stack already installed. Skipping."
else
  kubectl create namespace "$MONITORING_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
  helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
    --namespace "$MONITORING_NAMESPACE" \
    --values monitoring/kube-prometheus-stack/values.yaml \
    --timeout 10m
fi

# ---------------------------------------------------------------------------
# Hand off to ArgoCD for application resources
# ---------------------------------------------------------------------------
log "Applying ArgoCD Application manifest (this bootstraps everything else from Git)"

kubectl apply -f k8s/argocd/application.yaml

log "Waiting for ArgoCD to sync the application stack"
echo "Polling for 'school' namespace..."

for i in $(seq 1 60); do
  if kubectl get ns "$APP_NAMESPACE" >/dev/null 2>&1; then
    echo "Namespace '$APP_NAMESPACE' exists."
    break
  fi
  sleep 5
done

echo "Waiting for app pods to become Ready..."
kubectl -n "$APP_NAMESPACE" wait \
  --for=condition=Ready \
  --timeout=300s \
  pods -l 'app in (gateway,auth,academics,dashboard)' 2>/dev/null || true

echo "Waiting for Postgres StatefulSet..."
kubectl -n "$APP_NAMESPACE" rollout status statefulset/postgres --timeout=180s 2>/dev/null || true

# ---------------------------------------------------------------------------
# Post-bootstrap: suspend the backup CronJob for lab usability
# ---------------------------------------------------------------------------
log "Suspending backup CronJob (avoids CPU churn during lab work)"

if kubectl -n "$APP_NAMESPACE" get cronjob postgres-backup >/dev/null 2>&1; then
  kubectl -n "$APP_NAMESPACE" patch cronjob postgres-backup \
    -p '{"spec":{"suspend":true}}' >/dev/null
  echo "postgres-backup CronJob suspended. Resume with:"
  echo "  kubectl -n $APP_NAMESPACE patch cronjob postgres-backup -p '{\"spec\":{\"suspend\":false}}'"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
ARGOCD_PASSWORD=$(kubectl -n "$ARGOCD_NAMESPACE" get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" 2>/dev/null | base64 -d || echo "<not yet available>")

cat <<EOF

============================================================================
  Bootstrap complete.
============================================================================

Next steps:

  1. Port-forward the UIs you want to use:

       kubectl -n $ARGOCD_NAMESPACE     port-forward svc/argocd-server 8090:443 >/dev/null 2>&1 &
       kubectl -n $MONITORING_NAMESPACE port-forward svc/kube-prometheus-stack-prometheus   9090:9090 >/dev/null 2>&1 &
       kubectl -n $MONITORING_NAMESPACE port-forward svc/kube-prometheus-stack-grafana      3030:80   >/dev/null 2>&1 &
       kubectl -n $MONITORING_NAMESPACE port-forward svc/kube-prometheus-stack-alertmanager 9093:9093 >/dev/null 2>&1 &

  2. Access the UIs:

       Gateway       http://localhost:4000
       ArgoCD        http://localhost:8090  (admin / $ARGOCD_PASSWORD)
       Grafana       http://localhost:3030
       Prometheus    http://localhost:9090

  3. Verify the full request chain:

       curl -X POST "http://localhost:4000/api/auth/login?email=admin@school.edu&password=admin123"
       curl http://localhost:4000/api/dashboard/admin/overview

     Expected: {"total_students":5,"total_teachers":3,"total_sections":3,"total_classes":3}

  4. One thing NOT in Git — the Discord webhook Secret (a credential):

       kubectl -n $MONITORING_NAMESPACE create secret generic alertmanager-discord \\
         --from-literal=webhook-url="<your-webhook-url>"

       kubectl -n $APP_NAMESPACE create secret generic alertmanager-discord \\
         --from-literal=webhook-url="<your-webhook-url>"

     Without it, alerts fire in Prometheus but Discord delivery fails.

  5. Tear down:

       k3d cluster delete $CLUSTER_NAME

============================================================================
EOF