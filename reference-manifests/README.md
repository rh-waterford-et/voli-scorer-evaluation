# Current cluster reference manifests

Captured on 2026-10-21 from namespace `vllm-omni-validation`.
These snapshots describe the running scorer evaluation environment.

The setup uses EPP `v0.11.0` with JSON logging and `--v=4`, 27 scheduling
profiles (including `default`), and two Qwen3-TTS replicas on vLLM-Omni
`v0.28.0`. The simulator is scaled to zero.

| Resources | Files |
| --- | --- |
| EPP Deployment, ConfigMap, and Service | [Deployment](endpoint-picker-epp.yaml), [ConfigMap](endpoint-picker-epp-configmap.yaml), [Service](endpoint-picker-epp-service.yaml) |
| TTS backend | [Qwen3-TTS Deployment](qwen3-tts-deployment.yaml) |
| Optional simulator | [Simulator Deployment](vllm-tts-sim.yaml) |
| Gateway and its generated resources | [Gateway](gateway.yaml), [Deployment](inference-gateway.yaml), [Service](inference-gateway-service.yaml) |
| Request routing and backend pool | [HTTPRoute](httproute.yaml), [InferencePool](inferencepool.yaml) |
| Shared model cache | [PVC](pvc.yaml) |
| Completed cache preload Jobs | [Qwen3-TTS](preload-qwen3-tts.yaml), [Qwen3-Omni](preload-qwen3-omni.yaml) |

Resource specifications and ConfigMap contents are preserved. Status and
API bookkeeping metadata are omitted. The Gateway Deployment and Service
are managed by the Gateway controller.

These are cluster-specific references: Service addresses and NodePorts, PVC
binding, node placement, and security identities reflect this cluster.
Adapt them before reuse. Both preload Jobs remain on the cluster as completed
setup resources; Qwen3-TTS is the model currently served.
