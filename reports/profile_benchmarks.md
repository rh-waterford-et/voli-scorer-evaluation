# Routing Profile Benchmark — Two Load Levels

**Model:** `qwen3-omni`  
**Endpoint:** `http://10.6.62.51:31670/v1/chat/completions`  
**Modalities:** text, audio  
**Profiles tested:** 14 &nbsp;·&nbsp; **Total runs:** 28

Each profile was benchmarked at two concurrency levels (the "two loads"). Latency metrics are reported as **mean / p50 / p99** in milliseconds.

## Profiles

- [activeRequestProfile](#activerequestprofile)
- [loadAwareProfile](#loadawareprofile)
- [runningRequestSizeProfile](#runningrequestsizeprofile)
- [queueProfile](#queueprofile)
- [tokenLoadProfile](#tokenloadprofile)
- [kvCacheUtilizationProfile](#kvcacheutilizationprofile)
- [endpointAttributeProfile](#endpointattributeprofile)
- [contextLengthProfile](#contextlengthprofile)
- [prefixCacheProfile](#prefixcacheprofile)
- [sessionAffinityProfile](#sessionaffinityprofile)
- [mmEmbeddingsCacheProfile](#mmembeddingscacheprofile)
- [loraAffinityProfile](#loraaffinityprofile)
- [headerLabelAffinityProfile](#headerlabelaffinityprofile)
- [topologyAffinityProfile](#topologyaffinityprofile)


## activeRequestProfile

**Scorer:** `active-request-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 13.52 | 10 | 0 | 0 |
| 10 | 50 | 8.91 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 25 | 25 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 278.5 / 276.1 / 295.8 | 283.0 / 276.3 / 364.0 |
| TTFO — time to first output (ms) | 278.5 / 276.1 / 295.8 | 283.0 / 276.3 / 364.0 |
| TTFA — time to first audio (ms) | 435.7 / 435.0 / 456.8 | 473.4 / 464.4 / 639.0 |
| TPOT — time per output token (ms) | 6.8 / 6.9 / 7.3 | 8.2 / 7.6 / 12.6 |
| Text inter-chunk gap (ms) | 6.8 / 0.1 / 63.5 | 8.2 / 0.1 / 81.8 |
| Audio inter-chunk gap (ms) | 212.8 / 185.0 / 515.6 | 284.2 / 242.3 / 749.0 |
| End-to-end latency (ms) | 1,351.3 / 1,230.1 / 2,033.5 | 1,644.8 / 1,517.5 / 3,771.4 |


## loadAwareProfile

**Scorer:** `load-aware-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 13.79 | 10 | 0 | 0 |
| 10 | 50 | 9.01 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 29 | 21 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 275.7 / 274.0 / 285.6 | 278.7 / 277.1 / 295.1 |
| TTFO — time to first output (ms) | 275.7 / 274.0 / 285.6 | 278.7 / 277.1 / 295.1 |
| TTFA — time to first audio (ms) | 434.4 / 434.3 / 441.3 | 498.6 / 457.0 / 687.5 |
| TPOT — time per output token (ms) | 6.9 / 7.0 / 7.9 | 9.2 / 8.1 / 16.7 |
| Text inter-chunk gap (ms) | 6.9 / 0.1 / 66.7 | 9.2 / 0.3 / 94.1 |
| Audio inter-chunk gap (ms) | 214.4 / 229.3 / 584.5 | 270.7 / 241.5 / 743.4 |
| End-to-end latency (ms) | 1,378.4 / 1,230.0 / 2,030.3 | 1,614.6 / 1,601.5 / 2,272.8 |


## runningRequestSizeProfile

**Scorer:** `running-requests-size-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 12.05 | 10 | 0 | 0 |
| 10 | 50 | 8.81 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 25 | 25 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 274.0 / 272.4 / 284.5 | 280.1 / 279.6 / 296.5 |
| TTFO — time to first output (ms) | 274.0 / 272.4 / 284.5 | 280.1 / 279.6 / 296.5 |
| TTFA — time to first audio (ms) | 431.6 / 432.5 / 438.3 | 475.4 / 475.5 / 535.1 |
| TPOT — time per output token (ms) | 7.0 / 6.9 / 7.3 | 8.4 / 8.6 / 10.6 |
| Text inter-chunk gap (ms) | 7.0 / 0.1 / 64.1 | 8.4 / 1.4 / 80.1 |
| Audio inter-chunk gap (ms) | 184.0 / 146.9 / 394.3 | 267.9 / 221.9 / 749.8 |
| End-to-end latency (ms) | 1,205.0 / 1,178.4 / 1,533.1 | 1,593.0 / 1,528.6 / 2,416.2 |


## queueProfile

**Scorer:** `queue-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 13.79 | 10 | 0 | 0 |
| 10 | 50 | 9.66 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 7 | 3 |
| 10 | 21 | 29 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 278.5 / 277.3 / 287.5 | 281.9 / 278.3 / 321.5 |
| TTFO — time to first output (ms) | 278.5 / 277.3 / 287.5 | 281.9 / 278.3 / 321.5 |
| TTFA — time to first audio (ms) | 443.0 / 436.4 / 507.8 | 468.4 / 460.5 / 537.4 |
| TPOT — time per output token (ms) | 7.2 / 6.9 / 10.3 | 7.7 / 7.5 / 10.4 |
| Text inter-chunk gap (ms) | 7.2 / 0.1 / 77.5 | 7.7 / 0.1 / 76.2 |
| Audio inter-chunk gap (ms) | 222.6 / 133.1 / 899.0 | 302.8 / 245.1 / 780.9 |
| End-to-end latency (ms) | 1,378.5 / 1,114.7 / 3,360.6 | 1,734.8 / 1,564.5 / 3,134.6 |


## tokenLoadProfile

**Scorer:** `token-load-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 12.19 | 10 | 0 | 0 |
| 10 | 50 | 8.64 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 28 | 22 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 277.1 / 278.2 / 282.2 | 278.4 / 275.2 / 300.6 |
| TTFO — time to first output (ms) | 277.1 / 278.2 / 282.2 | 278.4 / 275.2 / 300.6 |
| TTFA — time to first audio (ms) | 437.6 / 435.8 / 450.0 | 465.5 / 456.5 / 551.8 |
| TPOT — time per output token (ms) | 6.9 / 6.9 / 7.2 | 8.0 / 7.9 / 11.4 |
| Text inter-chunk gap (ms) | 6.9 / 0.1 / 69.8 | 8.0 / 0.1 / 81.8 |
| Audio inter-chunk gap (ms) | 185.8 / 126.5 / 392.0 | 278.5 / 243.9 / 858.6 |
| End-to-end latency (ms) | 1,218.4 / 1,200.4 / 1,441.5 | 1,619.0 / 1,548.4 / 3,251.3 |


## kvCacheUtilizationProfile

**Scorer:** `kv-cache-utilization-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 11.63 | 10 | 0 | 0 |
| 10 | 50 | 11.95 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 26 | 24 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 272.6 / 270.2 / 280.3 | 285.4 / 277.9 / 426.1 |
| TTFO — time to first output (ms) | 272.6 / 270.2 / 280.3 | 285.4 / 277.9 / 426.1 |
| TTFA — time to first audio (ms) | 432.6 / 431.4 / 442.8 | 473.7 / 461.0 / 678.4 |
| TPOT — time per output token (ms) | 7.1 / 7.2 / 7.5 | 8.0 / 7.9 / 11.5 |
| Text inter-chunk gap (ms) | 7.1 / 0.1 / 64.5 | 8.0 / 0.1 / 74.9 |
| Audio inter-chunk gap (ms) | 173.7 / 126.7 / 366.8 | 300.7 / 228.2 / 965.9 |
| End-to-end latency (ms) | 1,162.6 / 1,168.9 / 1,264.6 | 1,731.2 / 1,472.2 / 4,531.1 |


## endpointAttributeProfile

**Scorer:** `endpoint-attribute-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 13.36 | 10 | 0 | 0 |
| 10 | 50 | 9.93 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 7 | 3 |
| 10 | 22 | 28 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 276.2 / 275.0 / 283.5 | 279.7 / 277.9 / 302.5 |
| TTFO — time to first output (ms) | 276.2 / 275.0 / 283.5 | 279.7 / 277.9 / 302.5 |
| TTFA — time to first audio (ms) | 433.3 / 432.6 / 445.5 | 466.7 / 457.5 / 556.8 |
| TPOT — time per output token (ms) | 6.8 / 6.9 / 7.3 | 7.7 / 7.3 / 11.3 |
| Text inter-chunk gap (ms) | 6.8 / 0.1 / 65.9 | 7.7 / 0.1 / 73.5 |
| Audio inter-chunk gap (ms) | 204.9 / 178.0 / 522.1 | 280.4 / 241.6 / 756.6 |
| End-to-end latency (ms) | 1,335.3 / 1,280.1 / 1,695.5 | 1,639.6 / 1,571.8 / 2,606.1 |


## contextLengthProfile

**Scorer:** `context-length-aware`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 13.84 | 10 | 0 | 0 |
| 10 | 50 | 10.13 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 4 | 6 |
| 10 | 27 | 23 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 276.7 / 275.3 / 288.4 | 278.5 / 274.9 / 297.8 |
| TTFO — time to first output (ms) | 276.7 / 275.3 / 288.4 | 278.5 / 274.9 / 297.8 |
| TTFA — time to first audio (ms) | 447.3 / 435.1 / 540.5 | 468.1 / 452.7 / 615.9 |
| TPOT — time per output token (ms) | 7.4 / 7.0 / 11.1 | 7.9 / 7.3 / 13.4 |
| Text inter-chunk gap (ms) | 7.4 / 0.1 / 101.4 | 7.9 / 0.1 / 73.1 |
| Audio inter-chunk gap (ms) | 212.7 / 125.6 / 569.8 | 304.2 / 245.4 / 974.3 |
| End-to-end latency (ms) | 1,383.5 / 1,152.2 / 2,632.5 | 1,740.1 / 1,544.6 / 3,330.3 |


## prefixCacheProfile

**Scorer:** `prefix-cache-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 12.09 | 10 | 0 | 0 |
| 10 | 50 | 10.09 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 22 | 28 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 277.7 / 275.6 / 288.1 | 283.6 / 279.9 / 313.9 |
| TTFO — time to first output (ms) | 277.7 / 275.6 / 288.1 | 283.6 / 279.9 / 313.9 |
| TTFA — time to first audio (ms) | 432.0 / 433.0 / 439.0 | 463.2 / 452.1 / 552.1 |
| TPOT — time per output token (ms) | 6.8 / 6.9 / 7.3 | 7.6 / 7.4 / 10.2 |
| Text inter-chunk gap (ms) | 6.8 / 0.1 / 63.5 | 7.6 / 0.1 / 82.6 |
| Audio inter-chunk gap (ms) | 180.4 / 132.6 / 383.1 | 274.9 / 234.6 / 997.3 |
| End-to-end latency (ms) | 1,208.2 / 1,157.9 / 1,748.3 | 1,602.8 / 1,503.1 / 4,227.3 |


## sessionAffinityProfile

**Scorer:** `session-affinity-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 13.59 | 10 | 0 | 0 |
| 10 | 50 | 8.87 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 24 | 26 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 376.4 / 275.0 / 1,195.7 | 278.3 / 275.8 / 299.3 |
| TTFO — time to first output (ms) | 376.4 / 275.0 / 1,195.7 | 278.3 / 275.8 / 299.3 |
| TTFA — time to first audio (ms) | 533.4 / 435.5 / 1,338.7 | 473.2 / 457.7 / 551.9 |
| TPOT — time per output token (ms) | 6.8 / 6.9 / 7.2 | 8.2 / 7.6 / 11.1 |
| Text inter-chunk gap (ms) | 6.8 / 0.1 / 62.7 | 8.2 / 0.2 / 88.9 |
| Audio inter-chunk gap (ms) | 201.2 / 174.2 / 514.5 | 271.2 / 237.6 / 802.2 |
| End-to-end latency (ms) | 1,358.6 / 1,196.5 / 2,045.1 | 1,607.3 / 1,526.0 / 3,104.8 |


## mmEmbeddingsCacheProfile

**Scorer:** `mm-embeddings-cache-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 13.51 | 10 | 0 | 0 |
| 10 | 50 | 10.41 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 4 | 6 |
| 10 | 23 | 27 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 277.2 / 276.3 / 283.8 | 282.7 / 280.4 / 328.2 |
| TTFO — time to first output (ms) | 277.2 / 276.3 / 283.8 | 282.7 / 280.4 / 328.2 |
| TTFA — time to first audio (ms) | 431.1 / 427.9 / 446.1 | 485.2 / 466.0 / 600.4 |
| TPOT — time per output token (ms) | 6.7 / 6.8 / 7.2 | 8.5 / 8.0 / 13.0 |
| Text inter-chunk gap (ms) | 6.7 / 0.1 / 63.7 | 8.5 / 0.8 / 84.9 |
| Audio inter-chunk gap (ms) | 229.8 / 211.4 / 574.3 | 305.3 / 246.3 / 868.5 |
| End-to-end latency (ms) | 1,350.7 / 1,209.6 / 2,479.2 | 1,755.8 / 1,545.8 / 3,542.8 |


## loraAffinityProfile

**Scorer:** `lora-affinity-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 13.55 | 10 | 0 | 0 |
| 10 | 50 | 8.66 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 26 | 24 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 274.3 / 272.7 / 283.3 | 279.6 / 277.0 / 299.0 |
| TTFO — time to first output (ms) | 274.3 / 272.7 / 283.3 | 279.6 / 277.0 / 299.0 |
| TTFA — time to first audio (ms) | 436.4 / 435.2 / 443.7 | 466.9 / 453.4 / 524.6 |
| TPOT — time per output token (ms) | 7.0 / 7.0 / 7.3 | 7.7 / 7.3 / 10.2 |
| Text inter-chunk gap (ms) | 7.0 / 0.1 / 65.1 | 7.7 / 0.6 / 72.1 |
| Audio inter-chunk gap (ms) | 223.8 / 243.7 / 505.8 | 260.6 / 224.5 / 754.3 |
| End-to-end latency (ms) | 1,354.5 / 1,227.9 / 2,134.6 | 1,595.8 / 1,516.2 / 2,280.5 |


## headerLabelAffinityProfile

**Scorer:** `header-label-affinity-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 12.06 | 10 | 0 | 0 |
| 10 | 50 | 8.75 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-zkqjt` | `vllm-omni-tts-68ffc5cb9f-dbm76` |
|---|---|---|
| 1 | 5 | 5 |
| 10 | 28 | 22 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 274.8 / 274.3 / 281.8 | 279.7 / 277.4 / 305.6 |
| TTFO — time to first output (ms) | 274.8 / 274.3 / 281.8 | 279.7 / 277.4 / 305.6 |
| TTFA — time to first audio (ms) | 436.6 / 436.7 / 443.8 | 462.9 / 448.3 / 539.5 |
| TPOT — time per output token (ms) | 7.0 / 6.9 / 7.6 | 7.4 / 7.1 / 10.3 |
| Text inter-chunk gap (ms) | 7.0 / 0.1 / 63.8 | 7.4 / 0.2 / 65.7 |
| Audio inter-chunk gap (ms) | 192.1 / 200.4 / 454.1 | 290.6 / 243.0 / 973.9 |
| End-to-end latency (ms) | 1,205.6 / 1,090.3 / 1,993.0 | 1,631.8 / 1,509.2 / 3,142.6 |


## topologyAffinityProfile

**Scorer:** `topology-affinity-scorer`

### Run summary

| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |
|---|---|---|---|---|---|
| 1 | 10 | 12.06 | 10 | 0 | 0 |
| 10 | 50 | 9.76 | 50 | 0 | 0 |

### Pod routing distribution

| Load (concurrency) | `vllm-omni-tts-68ffc5cb9f-dbm76` | `vllm-omni-tts-68ffc5cb9f-zkqjt` |
|---|---|---|
| 1 | 6 | 4 |
| 10 | 23 | 27 |

### Latency metrics (mean / p50 / p99 ms)

| Metric | Load 1 | Load 10 |
|---|---|---|
| TTFT — time to first text (ms) | 274.2 / 274.1 / 279.5 | 279.3 / 276.9 / 309.9 |
| TTFO — time to first output (ms) | 274.2 / 274.1 / 279.5 | 279.3 / 276.9 / 309.9 |
| TTFA — time to first audio (ms) | 432.4 / 432.5 / 439.0 | 471.1 / 454.0 / 537.5 |
| TPOT — time per output token (ms) | 6.9 / 6.9 / 7.5 | 8.0 / 7.3 / 10.9 |
| Text inter-chunk gap (ms) | 6.9 / 0.1 / 61.9 | 8.0 / 0.6 / 79.5 |
| Audio inter-chunk gap (ms) | 198.1 / 244.3 / 397.0 | 287.0 / 242.8 / 813.2 |
| End-to-end latency (ms) | 1,205.6 / 1,193.5 / 1,558.7 | 1,637.2 / 1,519.6 / 2,944.6 |

