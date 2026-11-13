# Changelog

Manual log of released dashboard versions. To cut a release: bump `version`
in `dashboard/frontend/package.json`, add a section here in the same commit,
and tag that commit (e.g. `git tag -a v0.1.14 -m "Dashboard v0.1.14"`).
Fixes accumulate under **Unreleased** until the next version is cut.

The version label in the dashboard's top bar identifies the built frontend;
when reporting issues, include it.

## Unreleased

## 0.1.15 — 2026-11-16

- Update scorer caveats and improve predictor prerequisite checks.
- Persist New Run and Builder form entries as browser-local drafts; fresh browsers start with placeholder-only fields instead of hardcoded defaults.
- Re-attach to a running Builder apply job after view switches or reloads; finished job panels can be dismissed.
- Require a model name and show endpoint-specific examples when creating a run.

## 0.1.14 — 2026-11-09

- Support text embeddings with non-streaming response validation and end-to-end latency.
- Support image generation with response validation and size checks in Compare.
- Support image editing with an uploaded input image and comparison checks.
- Support batch transcription with an audio upload, optional language and prompt, and comparison checks.
- Support streaming transcription with an audio upload, first-text latency and comparison checks.
- Add endpoint-specific scorer caveats for image and transcription workloads.
- File input alignment fix.

## 0.1.13 — 2026-10-23

- Improve profile comparison logic to correctly differentiate selected profiles across runs

## 0.1.12 — 2026-10-23

- Fix comparison view bug when selecting profiles from multiple runs; apply minor UI polish

## 0.1.11 — 2026-10-23

- Enable individual profile selection and comparison for compound runs

## 0.1.10 — 2026-10-22

- Add comparison view constraint on runs with multiple profiles; remove source column and note

## 0.1.9 — 2026-10-22

- Fix winner highlighting in compare view

## 0.1.8 — 2026-10-22

- Implement scorer operability checks and caveats in the dashboard

## 0.1.7 — 2026-10-21

- Flag incomparable runs in Compare view

## 0.1.6 — 2026-10-21

- Fix missing model names in dashboard history view

## 0.1.5 — 2026-10-21

- Add dark/light theme toggle

## 0.1.4 — 2026-10-20

- Add profile builder to the dashboard

## 0.1.3 — 2026-10-20

- Add popover hints to dashboard

## 0.1.2 — 2026-10-20

- Remove pre-selected default profile from dashboard, offered as opt-in; profile selection now required

## 0.1.1 — 2026-10-20

- Implement scorer benchmarking dashboard for profile comparisons
