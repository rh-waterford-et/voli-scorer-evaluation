# VOLI Scorer Dashboard

A local web UI for running `scripts/stream_metrics.py` benchmark suites and
exploring the results: pick profiles and flags, watch live progress, sort and
compare profiles by latency metrics, and inspect per-request EPP scoring
decisions.

It is a thin layer over the existing scripts — `stream_metrics.py` and
`epp_scores.py` are **not modified**. The backend imports/reuses them and runs
the benchmark as a subprocess.

## What it does

| Area | Details |
|---|---|
| New run | Select profiles (built-in map or live cluster ConfigMap), load settings (`--run NxC`), prompts, and common flags. "Show command" previews the exact command lines. |
| Live progress | Per-profile status, the script's progress lines, and the full stdout/stderr log stream (SSE). Cancel mid-run. |
| Results | Sortable table per profile × load (TTFA/TTFT/TPOT/E2E, mean/p50/p99), expandable to full metrics, pod routing distribution, and per-request details including raw EPP scores, weighted contributions, and picker selection. |
| Charts | p50/p99 comparison bars across profile-runs; latency histograms per run. |
| Compare | Select runs in History → side-by-side matrix for a chosen metric/statistic/load, best value highlighted. |
| History | Dashboard runs stored under `dashboard/data/runs/`, plus existing `reports/*.json` shown read-only. |

The profile builder (compose scorers/weights, apply to the cluster) is planned
as a second stage and not included yet.

## Safety / access model

- The backend binds to localhost and has no authentication — run it on your
  workstation only.
- Starting a run sends benchmark requests to the configured Gateway URL, and
  (unless disabled) runs read-only `oc` queries: `oc get pods`, `oc logs` on
  Gateway pods, and with `--epp-scores` also `oc get deployment/configmap` and
  `oc logs` on EPP pods. Nothing the dashboard does modifies the cluster.
- "Load from cluster" in the profile picker runs `oc get deployment` +
  `oc get configmap` (read-only) to list the live scheduling profiles,
  including combined profiles and weights that are not in the script's
  built-in map.
- All state lives under `dashboard/data/` (gitignored). Deleting a run in the
  UI deletes only its folder there. Repository `reports/` are never written.

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

For `/v1/chat/completions` runs the benchmark needs a tokenizer, so install
`transformers` into the same venv (TTS runs need nothing extra):

```bash
dashboard/.venv/bin/pip install transformers
```

## Run

```bash
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

## Architecture

```
dashboard/
  backend/          FastAPI app (app.py) + modules
    bench.py        RunParams model -> stream_metrics.py argv construction
    runner.py       RunManager/ManagedRun: subprocess per profile, SSE events
    store.py        Run history under data/runs/<id>/, report ingestion
    cluster.py      Profile discovery: builtin map; live ConfigMap (read-only oc)
  frontend/         React + Vite + Recharts (served by the backend from dist/)
  dev/
    stub_benchmark.py  Offline stand-in for stream_metrics.py (dev/testing)
  data/runs/        Runtime state (gitignored)
```

A run executes the benchmark **once per selected profile** in single-profile
mode (`--profile NAME`), with one `--run NxC` per load setting. That mode
accepts any profile name — including cluster-discovered combined profiles that
are not in the script's `PROFILE_SCORERS` map — and the per-profile JSON
outputs are merged into one document for the UI.

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

## Testing without a cluster

```bash
VOLI_BENCH_CMD=dashboard/dev/stub_benchmark.py \
  dashboard/.venv/bin/uvicorn app:app --app-dir dashboard/backend --port 8765
```

The stub writes plausible result JSON without contacting any gateway; it also
exercises SSE progress, logs, failure handling (set `STUB_FAIL=1`), and
cancellation. The committed `reports/*.json` files appear in History for
testing the result views with real data.
