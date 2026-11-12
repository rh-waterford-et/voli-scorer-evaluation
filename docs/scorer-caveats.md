# Scorer Caveats

The dashboard reads the endpoint-specific, scorer-type keyed caveats in
[`scripts/profile_caveats.json`](../scripts/profile_caveats.json). Its
`verified_as_of` date records the source review, not verification of a live
cluster. Recheck the deployed router image, configuration and scorer signals
before drawing conclusions.

As of 2026-11-12, v1.0.0 is the latest published router release checked. TTS
input estimation, image prompt estimation, and uploaded image-edit input
estimation are present on newer upstream `main` builds, but must be verified
in the deployed image. The transcription parser change is still open. The
estimate backend uses pseudo-tokens and does not establish precise KV-cache
matches or actual backend cache hits.

The dashboard can check for predictor sidecar containers, but predictor servers
can also run as separate services. Missing sidecars therefore report unknown;
containers being present does not establish service health or training. Unknown
and limited caveats warn without suppressing Compare winner highlighting.
