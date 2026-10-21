# Cluster overlay: `vllm-omni-validation`

Target: `https://a2caf4d6d64fd4294ab94161cb1e6135-188853195.us-east-1.elb.amazonaws.com:6443`,
namespace `vllm-omni-validation`.

This is a **1 GPU node / 1 PVC** cluster, structurally different from WetLab
(3 node-pinned local PVs) and from the `et-voli` cluster we briefly (and
mistakenly) checked (1 zone-pinned AWS EBS PVC, zero GPU nodes). Confirmed
live via read-only `oc`/Longhorn CR inspection on 2026-10-13:

- GPU node: `l42-h06-000-xe8640.rdu3.labs.perfscale.redhat.com` -- 4x
  NVIDIA H100 80GB HBM3, no taints, 127.5 CPU / ~1TB RAM allocatable.
- Cache PVC: `qwen3-omni-model-cache`, 200Gi, RWO, StorageClass
  `longhorn-h100-cache` (Longhorn CSI, `diskSelector: h100-nvme`,
  `numberOfReplicas: 1`). Confirmed via `nodes.longhorn.io` that the only
  disk tagged `h100-nvme` on the whole cluster is on that exact GPU node's
  `/var/lib/data` -- so this PVC is functionally node-pinned there, same
  intent as WetLab's local-PV pattern, just via Longhorn instead of a static
  local PV. **RWO + 1 replica: only one pod can mount it at a time** -- by
  explicit decision (per user, 2026-10-13), we are sticking with this single
  PVC for now and revisiting multi-pod capacity later.
- Gateway API + GIE CRDs: already installed, nothing to apply.
- GatewayClass: two exist (`data-science-gateway-class`,
  `openshift-ai-inference`). **Using `data-science-gateway-class`** -- it's
  the RHOAI-operator-managed default (owned by `GatewayConfig/default-gateway`
  -> `DSCInitialization/default-dsci`), matches WetLab exactly.
  `openshift-ai-inference` is a standalone Helm release in someone else's
  namespace (`ricky-llmd`) with no platform ownership chain -- not used here.
- Namespace `vllm-omni-validation` was otherwise a clean slate: no existing
  Gateway/HTTPRoute/InferencePool/Deployment, no ResourceQuota/LimitRange/
  NetworkPolicy.

## Resolved: wrong `--model` path + wrong `--task-type`

Initial deploy (2026-10-13) scheduled and mounted cleanly but crash-looped
with `Could not determine model_type for model: /models/qwen3-omni ...`.
At that point the cache was **not** actually empty (Longhorn reported
~70GB written), so the real issue was a path mismatch: the model is
`Qwen3-Omni-30B-A3B-Instruct`, nested one directory deeper than the mount
root (`/models/qwen3-omni/Qwen3-Omni-30B-A3B-Instruct/`), not sitting flat
at `/models/qwen3-omni` itself. Fixed by pointing `--model` one level
deeper (mountPath deliberately left unchanged -- see the comment block at
the top of `20-deployment-vllm-omni-tts.yaml` for why changing both would
double the nesting). Also dropped `--task-type CustomVoice`, carried over
from WetLab's BM-003 (a dedicated TTS/voice-cloning model) -- it doesn't
apply to `Qwen3-Omni-30B-A3B-Instruct`, a general-purpose multimodal
instruct model.

Everything else -- Gateway, HTTPRoute, InferencePool, EPP -- works
independently of the cache being populated, so you can validate the full
routing path (Gateway -> HTTPRoute -> InferencePool -> EPP) and the
scheduling/mount mechanics (PVC binds, pod schedules on the GPU node) before
the cache lands, same as the "Outstanding dependency" pattern in the main
package README.

## Files

- `00-gateway.yaml` -- Gateway, namespace `vllm-omni-validation`, class `data-science-gateway-class`
- `values-vllm-omni-validation.yaml` -- same corrected EPP config as WetLab's
  `../../20-chart/values-wetlab-ai.yaml` (image tag `new-approach`,
  `tts.yaml` scheduling profile, `multimodal-inference-pool` selector) --
  these are namespace-agnostic (chart uses `.Release.Namespace`), copied here
  only so this overlay is self-contained and doesn't depend on reading the
  WetLab-named file to understand what's running.
- `10-httproute-tts.yaml` -- standalone HTTPRoute, namespace `vllm-omni-validation`
- `20-deployment-vllm-omni-tts.yaml` -- single Deployment (no node-pinning
  suffix needed -- there's only one GPU node), pinned to
  `l42-h06-000-xe8640.rdu3.labs.perfscale.redhat.com`, mounts
  `qwen3-omni-model-cache` at its root (no `subPath` -- no preload
  convention exists yet on this cluster, unlike WetLab's
  `approved/bm-003/<revision>`). `replicas: 0` by default.

## Apply order

```bash
NS=vllm-omni-validation
cd /Users/dekelly/llm-d-playg/wetlab-operations/transfer/vllm-omni-llm-d

# 1. Gateway (CRDs + GatewayClass already present on this cluster -- nothing to do there)
oc apply -f clusters/vllm-omni-validation/00-gateway.yaml -n "$NS"

# 2. Helm release (EPP + InferencePool + RBAC) -- vendored chart, no network needed
helm upgrade --install endpoint-picker ./chart-llm-d-router-gateway \
  -n "$NS" \
  -f ./clusters/vllm-omni-validation/values-vllm-omni-validation.yaml

# 3. HTTPRoute override (chart can't express the 3 exact-path rules)
oc apply -f clusters/vllm-omni-validation/10-httproute-tts.yaml -n "$NS"

# 4. Model server (replicas: 0 -- scale up only after the cache is populated)
oc apply -f clusters/vllm-omni-validation/20-deployment-vllm-omni-tts.yaml -n "$NS"

# Verify
oc get gateway,httproute,inferencepool,deployment -n "$NS"
```
