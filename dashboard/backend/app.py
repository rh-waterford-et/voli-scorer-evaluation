"""FastAPI application for the VOLI scorer-evaluation dashboard.

Run from the repository root:

    dashboard/.venv/bin/uvicorn app:app --app-dir dashboard/backend --port 8765

Serves the built frontend (dashboard/frontend/dist) if present, plus the
JSON API under /api. All state lives under dashboard/data.
"""

import json
import queue
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

import bench
import builder
import cluster
import runner
from paths import FRONTEND_DIST
from store import RunStore, normalize_output, summarize_output

app = FastAPI(title="VOLI scorer-evaluation dashboard")
store = RunStore()
manager = runner.RunManager(store)
builder_manager = builder.BuilderManager()
store.mark_interrupted_on_startup()


class CreateRunRequest(BaseModel):
    name: Optional[str] = None
    params: bench.RunParams


# -- health --------------------------------------------------------------------


@app.get("/api/health")
def health():
    return {"status": "ok", "benchmark_command": manager.command}


# -- profiles ------------------------------------------------------------------


@app.get("/api/profiles")
def profiles():
    """Script profile map (local synced file if present, else tracked default)."""
    return {
        "source": "builtin",
        **cluster.map_source_info(),
        "profiles": cluster.builtin_profiles(),
    }


@app.get("/api/profiles/cluster")
def profiles_cluster(
    namespace: str = "vllm-omni-validation",
    epp_deployment: str = "endpoint-picker-epp",
    epp_container: str = "epp",
    configmap: Optional[str] = None,
    config_key: Optional[str] = None,
):
    """Live EPP scheduling profiles. Read-only: `oc get deployment/configmap`."""
    return cluster.discover_profiles(namespace, epp_deployment, epp_container, configmap, config_key)


# -- profile builder --------------------------------------------------------------


@app.get("/api/builder/state")
def builder_state(
    namespace: str = "vllm-omni-validation",
    epp_deployment: str = "endpoint-picker-epp",
    epp_container: str = "epp",
    configmap: Optional[str] = None,
    config_key: Optional[str] = None,
):
    """Live config for the builder: instances, profiles, picker, warnings. Read-only."""
    fetched = cluster.fetch_config(namespace, epp_deployment, epp_container, configmap, config_key)
    state = builder.build_state(fetched)
    state["namespace"] = namespace
    state["epp_deployment"] = epp_deployment
    return state


@app.post("/api/builder/preview")
def builder_preview(request: builder.BuilderRequest):
    """Validate an operation and return the diff. No cluster change."""
    return builder.preview_operation(request)


@app.post("/api/builder/apply")
def builder_apply(request: builder.BuilderRequest):
    """Apply an operation: backup -> patch ConfigMap -> restart EPP -> verify."""
    preview = builder.preview_operation(request)
    if not preview["ok"]:
        raise HTTPException(status_code=400, detail="; ".join(preview["errors"]))
    job_id = builder_manager.start_apply(request)
    return {"job_id": job_id}


@app.get("/api/builder/jobs")
def builder_jobs():
    return builder_manager.list_jobs()


@app.get("/api/builder/jobs/{job_id}")
def builder_job(job_id: str):
    view = builder_manager.get_job(job_id)
    if view is None:
        raise HTTPException(status_code=404, detail="job not found")
    return view


@app.get("/api/builder/backups")
def builder_backups():
    return builder.list_backups()


@app.post("/api/builder/revert")
def builder_revert(request: builder.RevertRequest):
    """Restore a saved backup (itself going through the full apply chain)."""
    job_id = builder_manager.start_revert(request.backup_id)
    return {"job_id": job_id}


@app.get("/api/builder/live-yaml")
def builder_live_yaml(
    namespace: str = "vllm-omni-validation",
    epp_deployment: str = "endpoint-picker-epp",
    epp_container: str = "epp",
    configmap: Optional[str] = None,
    config_key: Optional[str] = None,
):
    """Raw live plugin YAML (read-only), e.g. for syncing Helm values."""
    fetched = cluster.fetch_config(namespace, epp_deployment, epp_container, configmap, config_key)
    return {
        "text": fetched["text"],
        "configmap": fetched["configmap_name"],
        "config_key": fetched["config_key"],
        "resource_version": fetched["resource_version"],
    }


@app.post("/api/builder/sync-map")
def builder_sync_map(request: builder.SyncMapRequest):
    """Mirror the live scheduling profiles into the script's local profile map."""
    fetched = cluster.fetch_config(
        request.namespace, request.epp_deployment, request.epp_container,
        request.configmap, request.config_key,
    )
    state = builder.build_state(fetched)
    document = builder.sync_profile_map(state, request.namespace)
    return {
        "synced": len(document["profiles"]),
        "synced_at": document["synced_at"],
        "source": document["source"],
        "file": builder.SCRIPT_MAP_LOCAL.name,
    }


# -- runs ----------------------------------------------------------------------


@app.post("/api/runs/preview")
def preview_run(request: CreateRunRequest):
    """Show the exact command lines a run would execute, without running them."""
    return manager.preview(request.params)


@app.post("/api/runs")
def create_run(request: CreateRunRequest):
    run = manager.create(request.name, request.params)
    return {"id": run.run_id}


@app.get("/api/runs")
def list_runs(include_reports: bool = True):
    items = []
    for meta in store.list_metas():
        item = {
            "id": meta["id"],
            "name": meta.get("name"),
            "created_at": meta.get("created_at"),
            "status": meta.get("status"),
            "source": "dashboard",
            "model": (meta.get("params") or {}).get("model"),
        }
        summary = store.ensure_summary(meta)
        if summary:
            item["summary"] = summary
        items.append(item)
    if include_reports:
        items.extend(store.list_reports())
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return items


def _report_detail(run_id: str) -> dict:
    stem = run_id[len("report:"):]
    normalized = store.load_report(stem)
    if normalized is None:
        raise HTTPException(status_code=404, detail="report not found")
    summary = summarize_output(normalized) or {}
    return {
        "id": run_id,
        "name": stem,
        "created_at": None,
        "status": "completed",
        "source": "report",
        "summary": summary,
        "model": normalized.get("model"),
        "endpoint": normalized.get("endpoint"),
        "results": normalized,
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    if run_id.startswith("report:"):
        return _report_detail(run_id)
    live = manager.get(run_id)
    meta = live.meta if live is not None else store.load_meta(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="run not found")
    detail = dict(meta)
    results = store.load_results(meta)
    if results is not None:
        detail["results"] = results
    return detail


@app.get("/api/runs/{run_id}/log")
def get_run_log(run_id: str, tail: int = Query(default=400, ge=1, le=5000)):
    if run_id.startswith("report:"):
        raise HTTPException(status_code=404, detail="reports have no run log")
    if store.load_meta(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return PlainTextResponse(store.read_log_tail(run_id, tail))


def _sse_event(kind: str, data) -> str:
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str):
    live = manager.get(run_id)
    if live is None:
        meta = store.load_meta(run_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="run not found")

        def finished():
            yield _sse_event("snapshot", {"meta": meta, "log_tail": []})
            yield _sse_event("done", {"status": meta.get("status")})

        return StreamingResponse(finished(), media_type="text/event-stream")

    def stream():
        subscriber, snapshot = live.subscribe()
        try:
            yield _sse_event("snapshot", snapshot)
            while True:
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield _sse_event(event["kind"], event["data"])
                if event["kind"] == "done":
                    break
        finally:
            live.unsubscribe(subscriber)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    if run_id.startswith("report:"):
        raise HTTPException(status_code=400, detail="reports cannot be cancelled")
    live = manager.get(run_id)
    if live is None or not live.cancel():
        raise HTTPException(status_code=409, detail="run is not active")
    return {"status": "cancelling"}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    if run_id.startswith("report:"):
        # Deletes the committed file from the working tree; committing the
        # removal makes it permanent.
        if not store.delete_report(run_id[len("report:"):]):
            raise HTTPException(status_code=404, detail="report not found")
        return {"status": "deleted"}
    live = manager.get(run_id)
    if live is not None and live.status in runner.ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="cancel the run before deleting it")
    if not store.delete(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    if live is not None:
        manager.runs.pop(run_id, None)
    return {"status": "deleted"}


# -- frontend (registered last; SPA fallback for client-side routes) ------------
# Always registered: serves dist files if they exist, so the frontend can be
# (re)built without restarting the backend.

FRONTEND_ROOT = FRONTEND_DIST.resolve()


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    candidate = (FRONTEND_DIST / full_path).resolve() if full_path else None
    if candidate is not None and candidate.is_file() and candidate.is_relative_to(FRONTEND_ROOT):
        return FileResponse(candidate)
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "frontend is not built yet; run npm install && npm run build in dashboard/frontend"
        },
    )
