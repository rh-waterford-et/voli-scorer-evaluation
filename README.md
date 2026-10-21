# **vLLM-Omni & llm-d Integration Scorer Analysis**

# **Overview**

This document covers the usage, methodology, combinations, and findings of routing scorers in `vllm-omni` and `llmd`, via the llm-d-router coordinator.

We have included a web console GUI tool for evaluation of the scorers please refer to README  [dashboard](dashboard/README.md)

# **Goals**

* Understand the function and characteristics of various scorers.  
* Evaluate scorer combinations for text and multimodal models.  
* Establish evaluation benchmarks and best practices for OpenShift deployment and testing, using the webconsole utility.

# **OpenShift Implementation & Deployment**

## **EPP Profile Handler**

The `llm-d-router` utilizes an Endpoint Picker Pod (EPP) instance to handle scheduling profiles. Using the headerprofile handler allows running exactly one scheduling profile per request based on a header value. This enables a single EPP instance to serve multi-stage disaggregated inference pipelines (encode, prefill, decode) whose callers know which profile each request is for.

### **Example Configuration**

```
plugins:
  - name: my-custom-profile-handler
    type: custom-profile-handler # Must implement framework.ProfileHandler
    parameters:
      # ... handler specific configuration ...
  - name: filter-a
    type: some-filter
  - name: filter-b
    type: another-filter
  - name: scorer-1
    type: some-scorer

schedulingProfiles:
  - name: profile-a
    plugins:
      - pluginRef: filter-a
      - pluginRef: scorer-1
  - name: profile-b
    plugins:
      - pluginRef: filter-b
      - pluginRef: scorer-1
```

### **Operational Notes**

* Only 1 profile handler plugin is allowed per configuration.  
* If no profile handler or scheduling profiles are declared, top-level plugins run under a default profile (`single-profile-handler`) for every request.

# **Scorer Reference Guide**

All scorers implement scheduling.Scorer (Score() \-\> map\[Endpoint\]float64). Each declares a category: Affinity, Distribution, or Balance. The scheduler combines weighted scorers as a weighted sum (Σ(score × weight)) to compose overall routing behavior.

## **1\. Affinity Scorers (Prefer endpoints with existing state)**

| Plugin | Type String | Description |
| :---- | :---- | :---- |
| `prefix` | `prefix-cache-scorer` | Scores endpoints based on prefix-cache match ratio (`MatchBlocks / TotalBlocks`). Optional `matchLengthWeight` blends in squared absolute match length. Consumes `PrefixCacheMatchInfo`. |
| `preciseprefixcache` | `precise-prefix-cache-scorer` | Deprecated composite bundling producer and scorer. Use producer \+ `prefix-cache-scorer` with `prefixMatchInfoProducerName` instead. |
| `sessionaffinity` | `session-affinity-scorer` | Pins requests to the same pod via `encoded_endpoint_header` or `session_id`. Implements `PreRequest` \+ `ResponseHeaderProcessor`. |
| `loraaffinity` | `lora-affinity-scorer` | Routes for LoRA adapters: `1.0` if active, `0.8` if capacity exists to load, `0.6` if queued for load, `0.0` if full. |
| `contextlengthaware` | `context-length-aware` | Matches tokenized request length against pod label `llm-d.ai/context-length-range` (`min-max`). Tighter matches score higher; out-of-range pods get proximity fallback (\<0.3). |
| `mmcacheaffinity` | `mm-embeddings-cache-scorer` | Multimodal encoder-cache affinity (`matched item size / total item size per endpoint`). |
| `topologyaffinity` | `topology-affinity-scorer` | Grades candidates by topology proximity to peer endpoint (Disaggregated Prefill/Decode): same host `1.0`, rack `0.2`, zone `0.05`, region `0.02`. |
| `headerlabelaffinity` | `header-label-affinity-scorer` | Soft affinity matching endpoint label (`labelKey`) with request header (`headerName`). Scores `1.0` on match, `0` otherwise. |

## **2\. Distribution Scorers (Spread Load)**

| Plugin | Type String | Description |
| :---- | :---- | :---- |
| `activerequest` | `active-request-scorer` | Scores by in-flight request count. Pods \<= `idleThreshold` get `1.0`; busy pods scale `0 -> maxBusyScore`. |
| `tokenload` | `token-load-scorer` | Token-based load: in-flight tokens \+ uncached tokens normalized against `queueThresholdTokens` (default 4M). |
| `kvcacheutilization` | `kv-cache-utilization-scorer` | `Score = 1 - KVCacheUsagePercent`. |
| `loadaware` | `load-aware-scorer` | Waiting-queue based: empty queue \= `0.5`, scales down to `0` at threshold (default 128). |
| `queuedepth` | `queue-scorer` | Min-max normalization on waiting queue size: shortest queue `1.0`, longest `0.0`. |
| `runningrequests` | `running-requests-size-scorer` | Min-max normalization on running (executing) requests count. |
| `nohitlru` | `no-hit-lru-scorer` | Prefers Least Recently Used (LRU) endpoints for cold requests (no prefix hit) to spread KV-cache growth. Warm requests get neutral `0.5`. |
| `endpointattribute` | `endpoint-attribute-scorer` | Scores any custom numeric metric published by custom metrics layer using linear normalization. |

*Note: Multicluster variants (`multicluster-queue-scorer`, `multicluster-kv-cache-utilization-scorer`) score cluster pool-level aggregate attributes.*

## **3\. Balance Scorers**

| Plugin | Type String | Description |
| :---- | :---- | :---- |
| `latency` | `latency-scorer` | Uses TTFT/TPOT SLO headroom predictions. Includes strategies like `least` (bin-pack toward SLO) and `most` (conservative max-headroom). |

# **Recommended Configuration Strategies**

| Use Case | Recommended Configuration Strategy |
| :---- | :---- |
| **Chat / Multi-turn Workloads** | `prefix` (or precise producer \+ prefix scorer) \+ `sessionaffinity` \+ lower-weighted distribution scorer. |
| **Disaggregated Inference (PD)** | `topologyaffinity` (co-locate prefill/decode transfers) \+ `latency` (headroom-aware placement). |
| **LoRA Serving** | `loraaffinity` \+ `kvcacheutilization` / `tokenload`. |
| **Heterogeneous Capacity** | `contextlengthaware` (with filtering enabled). |
| **Homogeneous High-Throughput** | `queuedepth` / `activerequest` / `tokenload` \+ `kvcacheutilization`. Add `nohitlru` for cold requests. |
| **Multimodal (VLM) Workloads** | `mmcacheaffinity` to keep image/video embeddings warm. |
| **Tenant / Region Pinning** | `headerlabelaffinity` (e.g., `X-Tenant: acme` \-\> pod label `tenant=acme`). |
| **Custom / External Metrics** | `endpointattribute` for telemetry like DCGM GPU metrics. |

# **Configuration Architecture Rules**

1. **Top-Level Plugins**: Functions strictly as an instantiation set. Order does not matter; names and types referenced by profiles must be unique and resolvable.  
2. **`schedulingProfiles[].plugins` Execution Order**:  
   * **Filters** run first to narrow candidate set.  
   * **Scorers** run next as a commutative weighted sum: `Σ(score × weight)`. Order of listing does not affect execution result.  
   * **Picker** runs last on final scored list (strictly one picker per profile).  
3. **Request Handler Parsers**: Order-sensitive. First configured parser claiming the path handles the request.

⚠️ **Deprecation Warning**: Configuration files using `apiVersion: llm-d.ai/v1alpha1` should be updated to `apiVersion: llm-d.ai/v1`.

**N.B** We have copied our current deployments, configmaps etc into the directory reference-templates, these may change depnending on your deployment,
they are used for reference only.

# **Testing Metrics & Scoring Evaluation**

## **Web Console GUI**

As mentioned we have included a simple webconsole to assist in the benchmarking and evaluation of scorers.

Refer to the dashboard README [dashboard](dashboard/README.md) for detailed usage

### Quick Start

Requirements: Python 3.11+ and Node 18+.

```bash
# backend venv (inside the repo)
python3 -m venv dashboard/.venv
dashboard/.venv/bin/pip install -r dashboard/backend/requirements.txt

# frontend
cd dashboard/frontend
npm install
npm run build
```

For `/v1/chat/completions` runs, the benchmark needs a tokenizer, so install
`transformers` into the same venv (TTS runs need nothing extra):

```bash
dashboard/.venv/bin/pip install transformers
```

## Run

**N.B** Pplease ensure you are logged into the OpenShift cluster, as the webconsole service makes use og the `oc` command

```bash
dashboard/.venv/bin/uvicorn app:app --app-dir dashboard/backend --port 8765
```

Then open <http://localhost:8765>.
