# Routing Profile Benchmark — Two Load Levels

**Model:** `qwen3-tts`  
**Endpoint:** `http://10.6.62.51:31670/v1/audio/speech`  
**Modalities:** audio  
**Profiles tested:** 17 &nbsp;·&nbsp; **Total runs:** 34

Each profile was benchmarked at two concurrency levels (the "two loads"). Latency metrics are reported as **mean / p50 / p99** in milliseconds.

## Profiles

- [activeRequestProfile](#activerequestprofile)
- [loadAwareProfile](#loadawareprofile)
- [runningRequestSizeProfile](#runningrequestsizeprofile)
- [queueProfile](#queueprofile)
- [kvCacheUtilizationProfile](#kvcacheutilizationprofile)
- [endpointAttributeProfile](#endpointattributeprofile)
- [sessionAffinityProfile](#sessionaffinityprofile)
- [loraAffinityProfile](#loraaffinityprofile)
- [headerLabelAffinityProfile](#headerlabelaffinityprofile)
- [topologyAffinityProfile](#topologyaffinityprofile)

### Profiles with TTS caveats

- [tokenLoadProfile](#tokenloadprofile) (token-load-scorer): no usable TTS token-load estimate
- [endpointAttributeWeightProfile](#endpointattributeweightprofile) (endpoint-attribute-weight-scorer): fixed manual preferences, not performance learning
- [contextLengthProfile](#contextlengthprofile) (context-length-aware): no actual TTS input token count
- [prefixCacheProfile](#prefixcacheprofile) (prefix-cache-scorer): no tokenized prompt-prefix data
- [noHitLruProfile](#nohitlruprofile) (no-hit-lru-scorer): LRU spreading only; requests appear cold
- [latencyProfile](#latencyprofile) (latency-scorer): no TTS token data; predictor sidecars currently removed
- [mmEmbeddingsCacheProfile](#mmembeddingscacheprofile) (mm-embeddings-cache-scorer): no input media embeddings in text-input TTS

## activeRequestProfile

**Scorer:** `active-request-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 11.52 | 10 | 0 | 0 |
| 10 | 50 | 6.98 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 25 | 25 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 277.5 / 274.3 / 307.1 | 301.2 / 283.2 / 681.1 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 301.2 / 240.0 / 1,038.6 | 327.4 / 238.6 / 1,014.3 |
| End-to-end latency (ms) | 1,151.5 / 945.1 / 2,476.9 | 1,211.9 / 987.9 / 2,966.4 |

## loadAwareProfile

**Scorer:** `load-aware-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.61 | 10 | 0 | 0 |
| 10 | 50 | 6.30 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 26 | 24 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 273.5 / 273.5 / 275.9 | 324.0 / 284.4 / 762.3 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 254.1 / 120.5 / 705.4 | 286.4 / 121.6 / 1,000.3 |
| End-to-end latency (ms) | 960.3 / 925.6 / 1,360.6 | 1,132.2 / 973.4 / 2,678.1 |

## runningRequestSizeProfile

**Scorer:** `running-requests-size-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.50 | 10 | 0 | 0 |
| 10 | 50 | 6.35 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 24 | 26 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 274.7 / 273.9 / 279.8 | 309.0 / 280.7 / 734.7 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 249.6 / 123.3 / 535.0 | 298.6 / 236.5 / 1,108.2 |
| End-to-end latency (ms) | 949.3 / 930.5 / 1,155.6 | 1,169.6 / 1,059.8 / 2,788.0 |

## queueProfile

**Scorer:** `queue-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 10.67 | 10 | 0 | 0 |
| 10 | 50 | 6.00 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 28 | 22 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 274.3 / 274.1 / 282.6 | 313.0 / 285.7 / 724.0 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 273.0 / 120.5 / 846.1 | 271.9 / 121.8 / 716.2 |
| End-to-end latency (ms) | 1,066.5 / 925.0 / 1,826.9 | 1,102.1 / 1,059.4 / 2,027.5 |

## kvCacheUtilizationProfile

**Scorer:** `kv-cache-utilization-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.39 | 10 | 0 | 0 |
| 10 | 50 | 6.76 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 10 | 0 |
| 10 | 24 | 26 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 273.2 / 273.1 / 277.7 | 402.0 / 293.5 / 1,121.7 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 229.1 / 120.7 / 536.4 | 281.2 / 121.5 / 782.2 |
| End-to-end latency (ms) | 938.2 / 926.3 / 1,046.5 | 1,212.3 / 1,086.9 / 2,267.7 |

## endpointAttributeProfile

**Scorer:** `endpoint-attribute-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.61 | 10 | 0 | 0 |
| 10 | 50 | 6.06 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 23 | 27 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 275.5 / 274.9 / 286.4 | 327.4 / 283.8 / 751.4 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 263.2 / 121.9 / 537.6 | 293.9 / 236.9 / 918.6 |
| End-to-end latency (ms) | 960.4 / 928.3 / 1,143.0 | 1,133.1 / 1,007.7 / 2,278.9 |

## sessionAffinityProfile

**Scorer:** `session-affinity-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.74 | 10 | 0 | 0 |
| 10 | 50 | 6.66 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 26 | 24 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 274.7 / 274.3 / 280.6 | 303.2 / 284.2 / 701.8 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 249.4 / 120.6 / 614.2 | 322.5 / 239.3 / 1,062.2 |
| End-to-end latency (ms) | 973.7 / 936.4 / 1,155.0 | 1,155.1 / 985.0 / 2,778.4 |

## loraAffinityProfile

**Scorer:** `lora-affinity-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.86 | 10 | 0 | 0 |
| 10 | 50 | 6.74 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 4 | 6 |
| 10 | 26 | 24 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 276.7 / 276.1 / 283.0 | 301.1 / 281.8 / 695.0 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 253.0 / 180.4 / 537.7 | 293.9 / 143.7 / 938.3 |
| End-to-end latency (ms) | 985.7 / 930.7 / 1,249.1 | 1,124.7 / 1,054.4 / 2,543.6 |

## headerLabelAffinityProfile

**Scorer:** `header-label-affinity-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.86 | 10 | 0 | 0 |
| 10 | 50 | 6.78 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 28 | 22 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 275.3 / 275.5 / 277.2 | 317.6 / 282.3 / 988.5 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 236.6 / 121.4 / 532.9 | 333.3 / 240.0 / 1,182.5 |
| End-to-end latency (ms) | 985.7 / 984.0 / 1,155.0 | 1,244.7 / 1,033.0 / 3,225.4 |

## topologyAffinityProfile

**Scorer:** `topology-affinity-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 10.45 | 10 | 0 | 0 |
| 10 | 50 | 8.39 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 4 | 6 |
| 10 | 29 | 21 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 276.4 / 275.4 / 289.2 | 314.4 / 283.2 / 749.4 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 264.8 / 120.9 / 617.9 | 336.7 / 239.5 / 1,008.8 |
| End-to-end latency (ms) | 1,044.9 / 930.0 / 1,705.8 | 1,264.5 / 1,045.8 / 3,475.6 |

## tokenLoadProfile

**Scorer:** `token-load-scorer`

**TTS caveat:** The missing TTS token estimate means this does not test token-aware load balancing.

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 10.81 | 10 | 0 | 0 |
| 10 | 50 | 6.15 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-4ntld` | `vllm-omni-tts-79fb95db54-shmjt` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 25 | 25 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 274.2 / 274.5 / 278.0 | 311.3 / 286.9 / 697.4 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 310.0 / 244.9 / 728.8 | 284.9 / 122.5 / 837.9 |
| End-to-end latency (ms) | 1,080.9 / 1,035.3 / 1,646.1 | 1,075.5 / 997.5 / 2,008.2 |

## endpointAttributeWeightProfile

**Scorer:** `endpoint-attribute-weight-scorer`

**TTS caveat:** Works with TTS, but uses manually configured fixed preferences and does not learn backend performance.

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 11.02 | 10 | 0 | 0 |
| 10 | 50 | 6.52 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 27 | 23 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 274.8 / 275.3 / 276.4 | 309.5 / 286.9 / 736.3 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 330.5 / 241.6 / 931.7 | 304.8 / 122.6 / 1,038.3 |
| End-to-end latency (ms) | 1,101.7 / 983.7 / 1,914.5 | 1,145.3 / 984.6 / 2,370.5 |

## contextLengthProfile

**Scorer:** `context-length-aware`

**TTS caveat:** Without TTS input token counts, it cannot compare actual request lengths.

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 14.89 | 10 | 0 | 0 |
| 10 | 50 | 6.75 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 22 | 28 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 274.1 / 274.8 / 275.7 | 311.7 / 282.0 / 767.9 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 379.5 / 240.9 / 1,091.6 | 331.1 / 237.7 / 1,198.7 |
| End-to-end latency (ms) | 1,489.0 / 1,344.8 / 2,799.0 | 1,212.9 / 981.9 / 3,303.8 |

## prefixCacheProfile

**Scorer:** `prefix-cache-scorer`

**TTS caveat:** Without tokenized TTS prompts, it cannot assess prefix reuse.

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.48 | 10 | 0 | 0 |
| 10 | 50 | 6.11 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 30 | 20 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 277.6 / 276.4 / 288.0 | 314.7 / 282.9 / 643.2 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 257.5 / 119.2 / 530.1 | 293.9 / 122.5 / 858.4 |
| End-to-end latency (ms) | 947.7 / 923.6 / 1,154.6 | 1,120.4 / 1,008.0 / 2,029.1 |

## noHitLruProfile

**Scorer:** `no-hit-lru-scorer`

**TTS caveat:** It can test LRU spreading, but missing cache data makes requests appear cold.

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 11.14 | 10 | 0 | 0 |
| 10 | 50 | 6.33 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-4ntld` | `vllm-omni-tts-79fb95db54-shmjt` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 26 | 24 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 301.5 / 273.4 / 523.5 | 298.6 / 283.1 / 609.5 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 279.7 / 121.0 / 1,016.3 | 296.8 / 122.6 / 1,137.9 |
| End-to-end latency (ms) | 1,113.2 / 921.9 / 2,368.6 | 1,201.4 / 1,048.3 / 2,924.5 |

## latencyProfile

**Scorer:** `latency-scorer`

**TTS caveat:** The v0.11.0 estimator provides no TTS token data, and the predictor sidecars are currently removed; this profile cannot provide meaningful latency scores.

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 10.10 | 10 | 0 | 0 |
| 10 | 50 | 7.58 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 26 | 24 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 274.8 / 275.6 / 281.0 | 304.9 / 284.1 / 610.5 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 253.3 / 122.7 / 534.0 | 332.3 / 237.9 / 1,213.2 |
| End-to-end latency (ms) | 1,009.9 / 923.8 / 1,417.7 | 1,202.7 / 977.5 / 3,271.7 |

## mmEmbeddingsCacheProfile

**Scorer:** `mm-embeddings-cache-scorer`

**TTS caveat:** Standard text-input TTS has no input media embeddings for this scorer to reuse.

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 9.60 | 10 | 0 | 0 |
| 10 | 50 | 8.07 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-79fb95db54-shmjt` | `vllm-omni-tts-79fb95db54-4ntld` |
|---|---|---|
| 1 | 3 | 7 |
| 10 | 23 | 27 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | — / — / — | — / — / — |
| TTFO — time to first output (ms) | — / — / — | — / — / — |
| TTFA — time to first audio (ms) | 275.9 / 276.3 / 279.0 | 301.5 / 282.5 / 725.2 |
| TPOT — time per output token (ms) | — / — / — | — / — / — |
| Text inter-chunk gap (ms) | — / — / — | — / — / — |
| Audio inter-chunk gap (ms) | 235.6 / 120.6 / 531.6 | 314.3 / 238.8 / 1,143.3 |
| End-to-end latency (ms) | 959.5 / 927.4 / 1,049.4 | 1,182.2 / 979.4 / 2,914.6 |

## TTS scorer caveats

These caveats apply to standard text-input `/v1/audio/speech` requests on router v0.11.0. Its token estimator does not handle this request body, which removes a key signal from latency, prefix-cache, context-length, and token-load scoring. The caveated profiles and their impact are listed above.

The latency predictor sidecars have since been removed. `latencyProfile` remains configured, but cannot provide meaningful latency scoring until the sidecars are restored. The latency figures in this report are client-observed request timings and do not validate the latency scorer.
