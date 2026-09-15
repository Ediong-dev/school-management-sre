#!/usr/bin/env bash
set -euo pipefail

echo "=== Bootstrapping school-management-sre ==="

# 1. Cluster
if ! k3d cluster list | grep -q '^school'; then
  echo "Creating k3d cluster..."
  k3d cluster create school --agents 2 \
    --port "4000:30000@loadbalancer" \
    --port "9091:30090@loadbalancer"
else
  echo "Cluster 'school' already exists."
fi

kubectl config use-context k3d-school
kubectl config set-context --current --namespace=school

# 2. ArgoCD
if ! kubectl get ns argocd >/dev/null 2>&1; then
  echo "Installing ArgoCD..."
  kubectl create namespace argocd
  kubectl apply -n argocd --server-side --force-conflicts \
    -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
  echo "Waiting for ArgoCD to be ready..."
  kubectl -n argocd wait --for=condition=available --timeout=300s \
    deployment/argocd-server
else
  echo "ArgoCD already installed."
fi

# 3. ArgoCD Application (from Git)
echo "Applying ArgoCD Application..."
kubectl apply -f k8s/argocd/application.yaml

# 4. Monitoring stack
if ! helm list -n monitoring 2>/dev/null | grep -q kube-prometheus-stack; then
  echo "Installing kube-prometheus-stack..."
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
  helm repo update >/dev/null
  kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
  helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --values monitoring/kube-prometheus-stack/values.yaml \
    --timeout 10m
else
  echo "kube-prometheus-stack already installed."
fi

echo ""
echo "=== Bootstrap complete ==="
echo "Wait ~3 minutes for ArgoCD to sync, then verify:"
echo "  curl -sS http://localhost:4000/health"