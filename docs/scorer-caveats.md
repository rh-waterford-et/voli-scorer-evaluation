# Scorer Caveats

*Verified as of: 2026-10-22*

| Scorer | Reason |
|--------|--------|
| **latency-scorer** | Router token estimator cannot process /v1/audio/speech request bodies, so the predictor receives no training data (re-verified against v0.11.0, v1.0.0 and main on 2026-10-22). |
| **prefix-cache-scorer** | Token estimator gap: no usable prefix-match data for TTS prompts, so cache reuse cannot be compared. |
| **context-length-aware** | TTS tokenization fails, so the input length reads as zero and length-based decisions are meaningless. |
| **token-load-scorer** | Missing TTS input-token estimate makes the token-load comparison across pods unreliable. |
| **no-hit-lru-scorer** | Without prefix data every request is treated as cold: this exercises LRU spreading only, not cache-aware routing. |
| **mm-embeddings-cache-scorer** | Text-input TTS produces audio but supplies no multimodal input media, so there are no embeddings to reuse. |
| **endpoint-attribute-weight-scorer** | Applies fixed label-based preferences only, and both current TTS pods share the same baseline-model label, so it cannot distinguish them. |
| **kv-cache-utilization-scorer** | Reads stage-0 KV usage only, which may not reflect whole-pipeline load; treat results as exploratory. |
