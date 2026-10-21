# Prerequisites

Check these on the **new** cluster before applying anything else. Everything
in this `transfer/` directory assumes they are already satisfied.

## 1. GPU-capable nodes

The model server needs a node that can schedule `nvidia.com/gpu: 1` and
tolerates the standard GPU taint:

```yaml
tolerations:
- key: nvidia.com/gpu
  operator: Exists
  effect: NoSchedule
```

This means the NVIDIA GPU Operator (or equivalent device plugin) must already
be installed and the node(s) must be labeled/tainted accordingly. Verify with:

```bash
oc get nodes -o json | jq '.items[].status.allocatable | select(."nvidia.com/gpu")'
```

## 2. Gateway API CRDs + Gateway API Inference Extension CRDs

Check:

```bash
oc get crd | grep -E 'gateway.networking.k8s.io|inference.networking.k8s.io'
```

If missing, apply:

```bash
oc apply -k 00-prereqs/gateway-api-crds
oc apply -k 00-prereqs/gateway-inference-extension-crds
```

These are cluster-scoped. Coordinate with cluster admins before applying on a
shared cluster.

## 3. A working GatewayClass

On the WetLab cluster, the `GatewayClass` used (`data-science-gateway-class`,
controller `openshift.io/gateway-controller/v1`) is **not created by this
package or by the Helm chart** — it's provisioned automatically by **Red Hat
OpenShift AI (RHOAI)** when a `GatewayConfig` custom resource
(`services.platform.opendatahub.io/v1alpha1`) exists on the cluster. Under the
hood that installs OpenShift Service Mesh / Istio and wires up the Gateway
controller.

For the new cluster, you need **one** of:

- **RHOAI installed** with a `GatewayConfig` (easiest if this is another
  OpenShift AI-managed cluster) — it will create a `GatewayClass` for you.
  Confirm with `oc get gatewayclass`.
- **Or** any other working Gateway API provider (e.g. Istio installed
  directly, or a cloud provider's native Gateway API implementation) — in
  which case update `gatewayClassName` in `10-gateway/gateway.yaml` to match.

Without a GatewayClass whose controller is actually running, the `Gateway`
object will sit in `Accepted: False` / never get `Programmed: True`.

## 4. Namespace + guardrail baseline (optional but recommended)

The WetLab `wetlab-ai` namespace runs with a default-deny `NetworkPolicy`
baseline. If the new cluster should behave the same way, apply the baseline
namespace manifests first:

```bash
oc apply -f ../../manifests/wetlab-ai/
```

This also creates the namespace itself. If you don't want the same quotas /
network policies on the new cluster, just create the bare namespace instead:

```bash
oc new-project wetlab-ai   # or whatever name you want
```

> If you keep the default-deny network policy baseline, also apply
> `10-namespace/network-policy-allow-epp-kube-api.yaml` (see note in that
> file — the as-shipped WetLab policy's pod selector doesn't actually match
> the EPP pods it's meant to cover).

## 5. Persistent model cache — owned by another team, not yet delivered

**Correction:** this package does *not* pull the model from Hugging Face.
The model server manifests in `40-model-server/` (`deployment-vllm-omni-tts-node-{32,42,5c}.yaml`)
mount the approved, pinned BM-003 artifact read-only from a node-local PVC —
exactly the way `bm-003-vllm-omni` does on WetLab. That's a deliberate fix:
an earlier draft of this package replicated WetLab's live HF-download
behaviour, which turned out to violate `docs/guardrails/model-onboarding-policy.md`
and has since been corrected both here and on WetLab itself.

What that means operationally: **the cache infrastructure is a hard
dependency, not an optional nice-to-have.** Another team is building it for
the new cluster. Until they deliver it, the three `vllm-omni-tts-node-*`
Deployments will sit at `Pending` — that's expected and correct (see
"Outstanding dependency" in the main `README.md` for the exact integration
contract). `vllm-tts-sim` remains available in the meantime for routing
smoke-tests, since it needs neither a GPU nor the cache.

## 6. RBAC to install the Helm chart (step 3) — do not over-grant this

The `llm-d-router-gateway` chart creates its own `ServiceAccount` plus two
namespaced `Role`/`RoleBinding` pairs (scoped only to that one ServiceAccount,
read-only verbs on `pods`/`inferencepools`/`inferenceobjectives`) — see
`chart-routerlib/templates/_rbac.yaml` and
`chart-llm-d-router-gateway/templates/rbac.yaml`. Whoever runs
`helm upgrade --install` in step 3 needs `create` on `serviceaccounts`,
`roles.rbac.authorization.k8s.io` and `rolebindings.rbac.authorization.k8s.io`
in the target namespace at that moment.

**Do not** resolve this the way it was resolved on WetLab: a standing Role
(`llm-d-router-helm-rbac`) was found granting ordinary operators blanket
`create`/`update`/`patch`/`delete` on `roles`/`rolebindings` namespace-wide,
specifically so Helm installs wouldn't fail — this is the exact anti-pattern
`docs/guardrails/authentication-and-rbac.md` warns against ("RBAC for Helm
and Shared Infrastructure", Security Principle #9), and it's already been
flagged as a violation to fix on WetLab. Don't reintroduce it on the new
cluster.

Instead, per that doc's own recommended workflow: have an administrator
either (a) run step 3 themselves once, using their own elevated session, or
(b) review the two Role manifests above and pre-create just those two
`ServiceAccount`/`Role`/`RoleBinding` sets, scoped only to the
`endpoint-picker-epp` ServiceAccount, before an ordinary operator runs
`apply.sh`.
