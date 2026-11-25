# Scorer Caveats

The dashboard reads endpoint-specific, scorer-type keyed caveats from
[`scripts/profile_caveats.json`](../scripts/profile_caveats.json).
`verified_as_of` records a source review, not live cluster validation.

The November 23, 2026 review covers router v1.0.0 (latest published release
checked) and main at `8f372a856464be9cf6fb009b6b433d43af531ddb`. Main includes
TTS/image input estimation and the transcription parser/estimator (#3964,
merged November 16); these additions postdate v1.0.0. The estimate backend's
pseudo-tokens do not establish precise KV matches or actual backend cache hits.
The checked vLLM render backend does not handle the tool's dedicated TTS,
embeddings, image or transcription bodies.

Token-load accounting now carries a warning: output estimation defaults
off, input load can be released at first response, and prefix-match data can
discount input even without a prefix scorer in the selected profile. New main
builds optionally estimate TTS output frames (#4382); this remains a heuristic.
TTS fingerprints also depend on full input and conditioning (#4059).

The built-in Omni metric mapping (#4381) supplies pipeline waiting/running
counts but leaves KV usage unmapped. KV scoring needs verification until a meaningful
metric/stage mapping is verified. Successful scraping alone does not prove it.

Predictor servers may run as sidecars or services. Container presence does not
establish health, training or prediction coverage. Checked main skips predictions
for never-scraped endpoints, ranks endpoints without predictions behind predicted
candidates, and uses a KV/queue/prefix fallback when no predictions exist.

All scorer caveats appear as warnings with short explanations and expandable
details. They do not suppress Compare winner highlighting. A warning identifies
the affected scorer in mixed profiles; no warning does not establish operability.
Checks use the current configuration and cluster view, not a historical snapshot.
