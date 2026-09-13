#!/bin/bash
set -euo pipefail

echo "=== Installing k3d ==="
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash

echo "=== Installing ArgoCD CLI ==="
ARGOCD_VERSION=$(curl -sL https://api.github.com/repos/argoproj/argo-cd/releases/latest \
  | grep -oP '"tag_name":\s*"\K[^"]+')
sudo curl -sSL -o /usr/local/bin/argocd \
  "https://github.com/argoproj/argo-cd/releases/download/${ARGOCD_VERSION}/argocd-linux-amd64"
sudo chmod +x /usr/local/bin/argocd

echo "=== Installing Argo Rollouts plugin ==="
curl -sL -o /tmp/kubectl-argo-rollouts \
  https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64
chmod +x /tmp/kubectl-argo-rollouts
sudo mv /tmp/kubectl-argo-rollouts /usr/local/bin/kubectl-argo-rollouts

echo "=== Installing hey (load testing) ==="
curl -sL -o /tmp/hey \
  https://github.com/rakyll/hey/releases/download/v0.1.4/hey_linux_amd64
chmod +x /tmp/hey
sudo mv /tmp/hey /usr/local/bin/hey

echo ""
echo "=== Versions installed ==="
echo "k3d:      $(k3d version | head -1)"
echo "kubectl:  $(kubectl version --client -o yaml | grep gitVersion | head -1 | tr -d ' ')"
echo "argocd:   $(argocd version --client --short 2>/dev/null | head -1 || echo 'installed')"
echo "hey:      $(hey -n 1 https://example.com 2>&1 | grep -m1 Total || echo 'installed')"
echo ""
echo "=== Setup complete ==="