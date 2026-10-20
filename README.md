# **vLLM-Omni & llm-d Integration Scorer Analysis**

# **Overview**

This document covers the usage, methodology, combinations, and findings of routing scorers in `vllm-omni` and `llmd`, coordinated via the llm-d-router coordinator.

# **Goals**

* Understand the function and characteristics of various scorers.  
* Evaluate scorer combinations for text and multimodal models.  
* Establish best practices for OpenShift deployment and testing.

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

# **Testing & Metrics**

## **Test Suite Scripts**

Use `scripts/stream_metrics.py` to send streaming requests through the inference Gateway, compare EPP scheduling profiles, and record client-observed latency and backend routing. The script lives at `~/Projects/red-hat/voli_scorers/stream_metrics.py`; its built-in map currently names 14 profiles and their scorers. Check `--list-profiles` before a run because that map must match the live EPP configuration.

## Before you start

```bash
cd ~/Projects/red-hat/voli_scorers
source .venv/bin/activate
python stream_metrics.py --list-profiles
```

For pod names in the routing results, log in with `oc` to the OpenShift cluster first. The script uses read-only `oc` pod and Gateway log queries to match each request to a backend. Without that access, latency measurements may still work, but routing can show `unknown`. The default namespace is `vllm-omni-validation`; the default endpoint is `http://10.6.62.51:31670`. Pass `--namespace` or `--url` if your environment differs.

## Common commands

**One profile, 10 sequential requests:**

```bash
python stream_metrics.py \
  --tokenizer Qwen/Qwen3-Omni-30B-A3B-Instruct \
  --profile queueProfile \
  --iterations 10 --concurrency 1 \
  --output-json queue_sequential.json
```

**Every configured profile, using the default 10 sequential requests per profile:**

```bash
python stream_metrics.py \
  --tokenizer Qwen/Qwen3-Omni-30B-A3B-Instruct \
  --suite \
  --output-json all_profiles.json
```

This is 14 profiles × 10 requests = **140 requests**.

**Every profile at two loads:**

```bash
python stream_metrics.py \
  --tokenizer Qwen/Qwen3-Omni-30B-A3B-Instruct \
  --suite --run 10x1 --run 50x10 \
  --output-json all_profiles_two_loads.json
```

`10x1` means 10 total requests with at most 1 in flight; `50x10` means 50 total with at most 10 in flight. Every profile gets both runs: 14 × (10 + 50) = **840 requests** across **28 runs**. Profiles and runs execute one after another; only requests within a run overlap.

**Compare a few profiles at the same loads:**

```bash
python stream_metrics.py \
  --tokenizer Qwen/Qwen3-Omni-30B-A3B-Instruct \
  --profiles activeRequestProfile,queueProfile,tokenLoadProfile \
  --run 10x1 --run 50x10 \
  --output-json selected_profiles.json
```

**Give profiles different run settings:**

Edit `suite_plan.example.json` to choose profiles and set each profile's `iterations` and `concurrency`, then run:

```bash
python stream_metrics.py \
  --tokenizer Qwen/Qwen3-Omni-30B-A3B-Instruct \
  --suite-file suite_plan.example.json \
  --output-json planned_profiles.json
```

The example plan includes `activeRequestProfile`, `queueProfile`, and `tokenLoadProfile`. `--suite-file` takes the place of `--suite`, `--profiles`, `--profile`, and `--run`; do not combine them.

**Inspect routing for one profile:**

```bash
python stream_metrics.py \
  --tokenizer Qwen/Qwen3-Omni-30B-A3B-Instruct \
  --profile queueProfile \
  --iterations 10 --concurrency 10 \
  --gateway-wait 30 --debug \
  --output-json queue_debug.json
```

`--debug` adds each request's status, selected pod if known, route source, latency, and error. `--gateway-wait 30` gives Gateway access logs up to 30 seconds to become available; the default is 10 seconds.

## Flag quick reference

| Flag | What it does |
|---|---|
| `--tokenizer NAME_OR_PATH` | Required for benchmark runs; counts generated text tokens for the TPOT estimate. Use the matching model tokenizer. |
| `--list-profiles` | Print the script's profile → scorer map and exit. No tokenizer needed. |
| `--profile NAME` | Run one EPP profile. Without it or a suite flag, the script uses `default`. |
| `--suite` | Run all 14 profiles in the built-in map. |
| `--profiles A,B` | Run only the named profiles, with the same load settings for each. |
| `--suite-file FILE` | Read per-profile load settings from a JSON plan. |
| `--iterations N` / `-n N` | Total requests in a run; default 10. Also sets the suite default when no `--run` is given. |
| `--concurrency N` / `-c N` | Maximum requests in flight in a run; default 1. |
| `--run NxC` | One load setting: N total requests, at most C concurrent. Repeat for multiple runs per selected profile; these settings replace `--iterations` and `--concurrency`. |
| `--output-json FILE` | Save run summaries and per-request details for later comparison. |
| `--debug` | Print per-request details in the terminal; summaries are shown without it. |
| `--gateway-wait SECONDS` | Wait for Gateway access log records used to identify backend pods. |
| `--url URL` / `--model NAME` | Override the default Gateway address or model name. |
| `--modalities text,audio` | Request both outputs (default); use `text` or `audio` for a single modality. |
| `--prompt TEXT` / `--prompts-file FILE` | Use one prompt or cycle through nonempty lines in a file. |
| `--namespace NAME` | Namespace for pod and Gateway log lookup. |
| `--no-backend-lookup` | Skip `oc` queries when pod routing is not needed. |

Run `python stream_metrics.py --help` for less common options such as API key, voice, audio format, Gateway pod/container override, and request timeout.

*Note: When testing with `running-requests-size-scorer`, ensure `"injectDefaults": true` is configured to allow metrics consumption in the pod.*

## Read the results

Each run reports the requested **profile and scorer**, valid/failed response counts, latency summaries, and **Routing (all requests)**. The routing counts include failed requests; use the valid response count when comparing latency. A split such as 9 requests to one pod and 1 to the other is a real observed split, though a small run cannot establish that the scorer caused it.

`unknown` means the script could not resolve that request to a pod. It is not a pod name. With `--debug` or the JSON output, check the request's `status`, `error`, `upstream`, and `backend_source`. A failed request may never reach a backend; a successful request can still be `unknown` if its Gateway log record or IP-to-pod match is missing. Confirm `oc` login and try a longer `--gateway-wait` before interpreting the split.

TTFT, TTFA, and end-to-end latency are observed at the client. Text chunk gaps are an ITL proxy, and text TPOT is an estimate because one streamed chunk can contain multiple tokens. P99 from fewer than 100 valid responses is only a rough tail indicator. The profile/scorer label comes from the script's map and requested header; routing and latency alone do not prove that a scorer made a particular decision.

## EPP raw scores and weighted totals

EPP must run with `--v=4` and JSON logging (`--zap-encoder json`).

```bash
python scripts/stream_metrics.py \
  --endpoint /v1/audio/speech --model qwen3-tts \
  --profile queueRunningProfile \
  --run 10x1 --run 50x10 \
  --epp-scores --debug \
  --output-json queue_running_scores.json
```

- `--epp-scores`: collect raw scores, weighted totals, and picker selections.
- `--debug`: display per-request score tables.
- `--output-json`: save results, including scores, to a JSON file.

## Session-affinity testing

```bash
python scripts/stream_metrics.py \
  --endpoint /v1/audio/speech --model qwen3-tts \
  --profile sessionAffinityProfile \
  --iterations 30 --concurrency 2 --session-length 5 \
  --epp-scores --debug --output-json /tmp/tts_sessions.json
```

- `--session-length N`: replay `x-session-token` within each group of up to N requests. The example runs six sessions, up to two concurrently, with five sequential requests each. The last session may be shorter.
- `--session-header NAME`: override the token header if EPP uses a different name.

Reports and JSON include token coverage, pod continuity, and separate latency results for initial and replayed requests. Use the same session settings when comparing profiles.

## Create a Mardown report

The stream_metrics.py script creates a json file for reference.

use the script `gen_profile_md.py` to create a markdown report for easier viewing and analysis 




