#!/bin/bash
set -euo pipefail

echo "=== Installing git-lfs ==="
sudo apt-get update -qq
sudo apt-get install -y -qq git-lfs
git lfs install

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

echo "=== Installing apache2-utils (ab load tester) ==="
sudo apt-get update -qq
sudo apt-get install -y -qq apache2-utils

echo ""
echo "=== Versions installed ==="
echo "k3d:      $(k3d version | head -1)"
echo "kubectl:  $(kubectl version --client -o yaml | grep gitVersion | head -1 | tr -d ' ')"
echo "argocd:   $(argocd version --client --short 2>/dev/null | head -1 || echo 'installed')"
echo "ab:       $(ab -V 2>&1 | head -1)"
echo ""
echo "=== Setup complete ==="