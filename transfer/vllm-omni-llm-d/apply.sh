#!/usr/bin/env bash
# Applies this transfer package to whatever cluster/namespace your current
# `oc`/`kubectl` context points at, in the correct order.
#
# Usage:
#   oc login --token=... --server=https://api.<new-cluster>:6443
#   ./apply.sh                 # interactive, pauses between stages
#   ./apply.sh --yes           # no pauses
#
# Re-read 00-prereqs/README.md before running this for the first time.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

AUTO_YES="${1:-}"
pause() {
  if [[ "$AUTO_YES" != "--yes" ]]; then
    read -r -p "-- press enter to continue (or Ctrl-C to stop) -- "
  fi
}

echo "== Target context =="
oc whoami --show-server
oc project -q 2>/dev/null || true
pause

echo
echo "== [1/5] Prereq CRDs (skip if already present on this cluster) =="
echo "Checking for Gateway API / Inference Extension CRDs..."
if oc get crd gateways.gateway.networking.k8s.io >/dev/null 2>&1 && \
   oc get crd inferencepools.inference.networking.k8s.io >/dev/null 2>&1; then
  echo "Already present, skipping."
else
  oc apply -k 00-prereqs/gateway-api-crds
  oc apply -k 00-prereqs/gateway-inference-extension-crds
fi
pause

echo
echo "== [2/5] Namespace baseline + Gateway =="
echo "If you want the WetLab guardrail baseline (quotas/network policies/RBAC),"
echo "apply it yourself first: oc apply -f ../../manifests/wetlab-ai/"
echo "Otherwise make sure the 'wetlab-ai' namespace exists: oc new-project wetlab-ai"
pause
oc apply -f 10-namespace/gateway.yaml
# Uncomment if running with the default-deny NetworkPolicy baseline:
# oc apply -f 10-namespace/network-policy-allow-epp-kube-api.yaml
pause

echo
echo "== [3/5] llm-d-router-gateway Helm chart (EPP + InferencePool + RBAC) =="
# The routerlib sub-chart is already vendored as a .tgz under
# chart-llm-d-router-gateway/charts/, so `helm template`/`install` works with
# ZERO network/helm-repo access. We deliberately do NOT run
# `helm dependency build` here -- it tries to refresh every helm repo in your
# *local* helm config (bitnami, gitlab, etc., whatever you happen to have
# added), which is unrelated to this chart and can hang or fail outright on
# an air-gapped/restricted new cluster's bastion host. If you ever edit
# chart-routerlib/ and need to re-vendor it, run
# `helm dependency build ./chart-llm-d-router-gateway` by hand from a machine
# with network access, then re-copy the resulting charts/*.tgz + Chart.lock.
if [[ ! -f ./chart-llm-d-router-gateway/charts/router-0.0.0.tgz ]]; then
  echo "charts/router-0.0.0.tgz missing -- attempting to rebuild (needs network)..."
  helm dependency build ./chart-llm-d-router-gateway
fi
helm upgrade --install endpoint-picker ./chart-llm-d-router-gateway \
  -n wetlab-ai \
  -f ./20-chart/values-wetlab-ai.yaml
pause

echo
echo "== [4/5] HTTPRoute override (chart can't express the live path matches) =="
oc apply -f 30-overrides/httproute-tts.yaml
pause

echo
echo "== [5/5] Model server =="
echo "Applying node-pinned, cache-backed vllm-omni deployments at replicas: 0"
echo "(these require the model-cache PVCs to exist first -- see 00-prereqs/README.md"
echo "item 5 -- otherwise they'll sit at Pending) plus the optional CPU simulator,"
echo "which needs neither a GPU nor the cache and is good for smoke-testing the"
echo "routing path before the cache is ready."
oc apply -f 40-model-server/deployment-vllm-omni-tts-node-32.yaml
oc apply -f 40-model-server/deployment-vllm-omni-tts-node-42.yaml
oc apply -f 40-model-server/deployment-vllm-omni-tts-node-5c.yaml
oc apply -f 40-model-server/deployment-vllm-tts-sim.yaml
echo
echo "Scale up when ready, e.g.:"
echo "  oc scale deployment/vllm-omni-tts-node-32 -n wetlab-ai --replicas=1"
echo
echo "Done. Verify with:"
echo "  oc get gateway,httproute,inferencepool,deployment -n wetlab-ai"
