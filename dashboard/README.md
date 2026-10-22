# VOLI Scorer Dashboard

A local web UI for running `scripts/stream_metrics.py` benchmark suites and
exploring the results: pick profiles and flags, watch live progress, sort and
compare profiles by latency metrics, and inspect per-request EPP scoring
decisions. Includes a profile builder for composing, editing, and deleting
EPP scheduling profiles on the cluster.

It is a thin layer over the existing scripts — `stream_metrics.py` and
`epp_scores.py` are **not modified**. The backend imports/reuses them and runs
the benchmark as a subprocess.

## What it does

| Area | Details |
|---|---|
| New run | Select profiles (built-in map or live cluster ConfigMap), load settings (`--run NxC`), prompts, and common flags. "Show command" previews the exact command lines. Nothing is pre-selected; `default` (no `EPP-Profile` header → cluster's default profile) is an explicit opt-in listed last. |
| Live progress | Per-profile status, the script's progress lines, and the full stdout/stderr log stream (SSE). Cancel mid-run. |
| Results | Sortable table per profile × load (TTFA/TTFT/TPOT/E2E, mean/p50/p99), expandable to full metrics, pod routing distribution, and per-request details including raw EPP scores, weighted contributions, and picker selection. |
| Charts | p50/p99 comparison bars across profile-runs; latency histograms per run. |
| Compare | Select runs in History → side-by-side matrix for a chosen metric/statistic/load, best value highlighted. |
| History | Dashboard runs stored under `dashboard/data/runs/`, plus existing `reports/*.json`. Entries can be deleted individually or in bulk; deleting a report removes the file from the working tree (commit to make permanent). |
| Profile builder | Compose new profiles from scorers already instantiated in the live ConfigMap (with weights and picker), edit or delete existing profiles, preview the exact YAML diff, then apply: backup → patch one ConfigMap key → restart EPP → wait for Ready → verify → **sync the script's profile map**. Failed rollouts offer an explicit revert from the saved backup. "Copy live YAML" helps sync Helm values from the live config. |

The builder is the only part that modifies the cluster, and only through the
explicit preview → confirm → apply chain described below.

**Script profile map sync:** the map `stream_metrics.py` uses for validation
and labels lives in `scripts/profile_scorers.json` (tracked default). Every
successful apply — and the "Sync script map" button — mirrors the live
scheduling profiles into `scripts/profile_scorers_local.json` (gitignored,
takes precedence). This keeps New Run's profile list, `--list-profiles`,
`--profiles`/`--suite` validation, and result scorer labels aligned with the
cluster, with no repository churn and no `unknown` labels.

The profile builder (compose scorers/weights, apply to the cluster) is planned
as a second stage and not included yet.

## Safety / access model

- The backend binds to localhost and has no authentication — run it on your
  workstation only.
- Starting a run sends benchmark requests to the configured Gateway URL, and
  (unless disabled) runs read-only `oc` queries: `oc get pods`, `oc logs` on
  Gateway pods, and with `--epp-scores` also `oc get deployment/configmap` and
  `oc logs` on EPP pods.
- "Load from cluster" in the profile picker runs `oc get deployment` +
  `oc get configmap` (read-only) to list the live scheduling profiles,
  including combined profiles and weights that are not in the script's
  built-in map.
- **The profile builder mutates the cluster** and is the only feature that
  does. Every apply:
  1. re-fetches the ConfigMap and refuses if it changed since your preview
     (resourceVersion guard);
  2. saves the previous content as a backup under `dashboard/data/configmap-backups/`;
  3. patches exactly one data key of one ConfigMap (`oc patch --type merge`);
  4. restarts the EPP deployment (`oc rollout restart`) and waits for Ready
     (`oc rollout status`);
  5. verifies the requested change is present in the live config.
  Failed rollouts are never auto-reverted — the UI shows the error and offers
  an explicit revert from the saved backup. Restores themselves create a new
  backup first, so they can be undone too. Your oc login needs patch rights on
  the ConfigMap and rollout rights on the Deployment.
- The live ConfigMap is the builder's only source of truth (it is
  Helm-managed and diverges from the repo template; a Helm upgrade may
  overwrite builder changes — the UI warns about this).
- Profile map sync writes only the gitignored
  `scripts/profile_scorers_local.json`; tracked files (including
  `stream_metrics.py` and `profile_scorers.json`) are never modified by the
  dashboard.
- All state lives under `dashboard/data/` (gitignored). Deleting a dashboard
  run in the UI deletes only its folder there. Repository reports can also be
  deleted from History — that removes the committed file from the working
  tree, and committing the deletion makes it permanent.

## Setup

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

```bash
# cd back to the main folder
cd ../../
# launch the application
dashboard/.venv/bin/uvicorn app:app --app-dir dashboard/backend --port 8765
```

Then open <http://localhost:8765>.

### Frontend dev mode

For UI development with hot reload (backend must be running on 8765):

```bash
cd dashboard/frontend
npm run dev       # http://localhost:5173, proxies /api to :8765
```

### Environment overrides

| Variable | Purpose |
|---|---|
| `VOLI_BENCH_PYTHON` | Interpreter used to run the benchmark (default: the backend venv's python). |
| `VOLI_BENCH_CMD` | Replace `scripts/stream_metrics.py` with another script — used with `dashboard/dev/stub_benchmark.py` for testing without a cluster. |
| `VOLI_OC_CMD` | Replace the `oc` binary with a script (used with `dashboard/dev/fake_oc.py` to test the builder without a cluster). |

## Architecture

```
dashboard/
  backend/          FastAPI app (app.py) + modules
    bench.py        RunParams model -> stream_metrics.py argv construction
    runner.py       RunManager/ManagedRun: subprocess per profile, SSE events
    store.py        Run history under data/runs/<id>/, report ingestion
    cluster.py      Read-only profile discovery + live ConfigMap fetching
    oc.py           oc command wrapper (VOLI_OC_CMD override for offline tests)
    builder.py      Profile builder: validation, YAML compose (ruamel), apply
                    jobs (backup -> patch -> rollout -> verify), backups
  frontend/         React + Vite + Recharts (served by the backend from dist/)
  dev/
    stub_benchmark.py  Offline stand-in for stream_metrics.py (dev/testing)
    fake_oc.py         Offline stand-in for oc, for builder apply testing
  data/runs/        Runtime state (gitignored)
  data/configmap-backups/  Pre-apply ConfigMap snapshots (gitignored)
  data/builder-jobs/       Apply job records (gitignored)
```

A run executes the benchmark **once per selected profile** in single-profile
mode (`--profile NAME`), with one `--run NxC` per load setting. That mode
accepts any profile name — including cluster-discovered combined profiles that
are not in the script's `PROFILE_SCORERS` map — and the per-profile JSON
outputs are merged into one document for the UI.

The builder round-trips the live ConfigMap's plugin YAML with `ruamel.yaml`
so comments, ordering, and quoting are preserved; only the requested change
is written. It composes profiles from plugin instances already instantiated
in the live config (e.g. `queue`, `activeRequest`, `maxScore`); instantiating
brand-new plugin types with parameters is out of scope for now.

Each stored run keeps `meta.json`, the full `log.txt`, and the per-profile
result JSON, so history survives backend restarts. If the backend restarts
while a run is active, the run is marked `interrupted` (the orphaned
subprocess is not tracked); avoid restarting the backend mid-run.

## API summary

| Endpoint | Purpose |
|---|---|
| `GET /api/profiles` | Built-in profile map (no cluster access). |
| `GET /api/profiles/cluster?namespace=…` | Live EPP profiles from the ConfigMap (read-only). |
| `POST /api/runs` | Start a run; body `{name?, params}`. |
| `POST /api/runs/preview` | Show the command lines without running. |
| `GET /api/runs` | History (dashboard runs + `reports/*.json`). |
| `GET /api/runs/{id}` | Run detail with merged results. |
| `GET /api/runs/{id}/events` | SSE progress stream. |
| `GET /api/runs/{id}/log?tail=N` | Captured benchmark log. |
| `POST /api/runs/{id}/cancel` / `DELETE /api/runs/{id}` | Cancel / delete. |
| `GET /api/builder/state` | Live config for the builder (read-only). |
| `POST /api/builder/preview` | Validate an operation and return the YAML diff (no change). |
| `POST /api/builder/apply` | Start an apply job (backup → patch → rollout → verify). |
| `GET /api/builder/jobs[/{id}]` | Apply job status / history. |
| `GET /api/builder/backups` · `POST /api/builder/revert` | List backups / restore one. |
| `POST /api/builder/sync-map` | Mirror live profiles into the script's local map. |
| `GET /api/builder/live-yaml` | Raw live plugin YAML (read-only). |

## Testing without a cluster

```bash
VOLI_BENCH_CMD=dashboard/dev/stub_benchmark.py \
  dashboard/.venv/bin/uvicorn app:app --app-dir dashboard/backend --port 8765
```

The stub writes plausible result JSON without contacting any gateway; it also
exercises SSE progress, logs, failure handling (set `STUB_FAIL=1`), and
cancellation. The committed `reports/*.json` files appear in History for
testing the result views with real data.

The builder's apply chain can be tested the same way against a fake oc backed
by the repo template:

```bash
VOLI_OC_CMD=dashboard/dev/fake_oc.py \
  dashboard/.venv/bin/uvicorn app:app --app-dir dashboard/backend --port 8765
```

The fake cluster state lives in `dashboard/data/fake-oc-state.json` (delete it
to re-seed). `FAKE_OC_MODE=patch|restart|rollout` forces a failure at that
step to exercise the failure and revert paths.
