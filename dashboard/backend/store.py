"""Persistent run store: metadata, logs, and result files under dashboard/data.

A dashboard "run" is a directory:

    dashboard/data/runs/<run-id>/
        meta.json                    run metadata (status, params, attempts)
        log.txt                      full merged stdout/stderr of every attempt
        prompts.txt                  optional multi-prompt input (if provided)
        input/<filename>             optional uploaded input file (image or audio)
        profiles/<safe-name>.json    stream_metrics.py --output-json result

Run ids from the repository's reports/ directory are exposed read-only with
the "report:" prefix and share the same normalized shape.
"""

import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from paths import REPORTS_DIR, RUNS_DIR

SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
ACTIVE_STATUSES = {"queued", "running"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def safe_profile_name(name: str) -> str:
    cleaned = SAFE_CHARS.sub("_", name).strip("._-")
    return cleaned[:80] or "unnamed"


def normalize_output(document) -> Optional[dict]:
    """Return {model, endpoint, modalities, runs} for script output.

    stream_metrics.py writes a suite document ({model, endpoint, modalities,
    runs: [...]}) when a profile has several load settings, and a bare run
    dict otherwise. Both shapes are normalized here.
    """
    if not isinstance(document, dict):
        return None
    if isinstance(document.get("runs"), list):
        return {
            "model": document.get("model"),
            "endpoint": document.get("endpoint"),
            "modalities": document.get("modalities", []),
            "image_size": document.get("image_size"),
            "edit_image": document.get("edit_image"),
            "transcribe_audio": document.get("transcribe_audio"),
            "language": document.get("language"),
            "runs": document["runs"],
        }
    if "profile" in document and "metrics" in document:
        return {
            "model": document.get("model"), "endpoint": document.get("endpoint"),
            "modalities": document.get("modalities", []), "image_size": document.get("image_size"),
            "edit_image": document.get("edit_image"),
            "transcribe_audio": document.get("transcribe_audio"),
            "language": document.get("language"),
            "runs": [document],
        }
    return None


def summarize_output(normalized: Optional[dict]) -> Optional[dict]:
    if not normalized:
        return None
    runs = normalized["runs"]
    return {
        "profiles": sorted({str(run.get("profile", "?")) for run in runs}),
        "run_count": len(runs),
        "requests": sum(int(run.get("iterations") or 0) for run in runs),
        "valid": sum(int(run.get("validated_responses", run.get("valid_responses")) or 0) for run in runs),
        "failed": sum(int(run.get("failed_responses") or 0) for run in runs),
        "unverified": sum(int(run.get("unverified_responses") or 0) for run in runs),
        "empty_transcripts": sum(int(run.get("empty_transcripts") or 0) for run in runs),
    }


class RunStore:
    def __init__(self, runs_dir: Path = RUNS_DIR):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # -- dashboard runs -----------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def meta_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "meta.json"

    def log_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "log.txt"

    def profile_result_path(self, run_id: str, profile: str) -> Path:
        return self.run_dir(run_id) / "profiles" / f"{safe_profile_name(profile)}.json"

    def prompts_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "prompts.txt"

    def save_run_input(self, run_id: str, data: bytes, filename: str) -> tuple[Path, dict]:
        """Store an uploaded run input file (image or audio) inside the run directory.

        Living with the run means run deletion removes it. The metadata dict
        (name, bytes, sha256) is kept in run params so comparisons can detect
        different inputs even after the file is gone.
        """
        safe_name = (Path(filename or "input-file").name or "input-file").replace("\x00", "_")
        if safe_name in (".", "..") or len(safe_name.encode("utf-8")) > 255:
            safe_name = "input-file"
        path = self.run_dir(run_id) / "input" / safe_name
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        info = {
            "name": safe_name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return path, info

    def create(self, run_id: str, name: str, params: dict) -> dict:
        with self._lock:
            self.run_dir(run_id).mkdir(parents=True, exist_ok=True)
            meta = {
                "id": run_id,
                "name": name,
                "created_at": now_iso(),
                "status": "queued",
                "source": "dashboard",
                "params": params,
                "profiles": [],
            }
            self._save_meta(meta)
            return meta

    def write_prompts(self, run_id: str, text: str) -> Path:
        path = self.prompts_path(run_id)
        path.write_text(text)
        return path

    def save(self, meta: dict) -> None:
        with self._lock:
            self._save_meta(meta)

    def _save_meta(self, meta: dict) -> None:
        target = self.meta_path(meta["id"])
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(meta, indent=2) + "\n")
        temporary.replace(target)

    def load_meta(self, run_id: str) -> Optional[dict]:
        path = self.meta_path(run_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def list_metas(self) -> list[dict]:
        metas = []
        for directory in self.runs_dir.iterdir():
            if not directory.is_dir():
                continue
            meta = self.load_meta(directory.name)
            if meta:
                metas.append(meta)
        metas.sort(key=lambda meta: meta.get("created_at", ""), reverse=True)
        return metas

    def mark_interrupted_on_startup(self) -> None:
        """A backend restart cannot reattach to running subprocesses."""
        for meta in self.list_metas():
            if meta.get("status") in ACTIVE_STATUSES:
                meta["status"] = "interrupted"
                meta["error"] = "dashboard backend restarted while this run was active"
                self.save(meta)

    def delete(self, run_id: str) -> bool:
        with self._lock:
            directory = self.run_dir(run_id)
            if not directory.is_dir():
                return False
            shutil.rmtree(directory)
            return True

    def load_results(self, meta: dict) -> Optional[dict]:
        """Merge every completed attempt's result file into one document."""
        runs = []
        model = endpoint = image_size = edit_image = transcribe_audio = language = None
        modalities: list = []
        for attempt in meta.get("profiles", []):
            relative = attempt.get("result_file")
            if not relative:
                continue
            path = self.run_dir(meta["id"]) / relative
            if not path.is_file():
                continue
            try:
                document = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            normalized = normalize_output(document)
            if not normalized:
                continue
            model = model or normalized["model"]
            endpoint = endpoint or normalized["endpoint"]
            image_size = image_size or normalized.get("image_size")
            edit_image = edit_image or normalized.get("edit_image")
            transcribe_audio = transcribe_audio or normalized.get("transcribe_audio")
            language = language or normalized.get("language")
            modalities = modalities or normalized["modalities"] or []
            runs.extend(normalized["runs"])
        if not runs:
            return None
        params = meta.get("params") or {}
        if model is None:
            model = params.get("model")
        if endpoint is None:
            endpoint = params.get("endpoint")
        if not modalities:
            modalities = {
                "/v1/audio/speech": ["audio"],
                "/v1/embeddings": ["embedding"],
                "/v1/images/generations": ["image"],
                "/v1/images/edits": ["image"],
                "/v1/audio/transcriptions": ["transcription"],
            }.get(params.get("endpoint"), [])
        image_size = image_size or params.get("image_size")
        edit_image = edit_image or params.get("input_info")
        transcribe_audio = transcribe_audio or params.get("input_info")
        language = language or params.get("language")
        return {"model": model, "endpoint": endpoint, "modalities": modalities,
                "image_size": image_size, "edit_image": edit_image,
                "transcribe_audio": transcribe_audio, "language": language, "runs": runs}

    def ensure_summary(self, meta: dict) -> Optional[dict]:
        summary = meta.get("summary")
        if (summary is None or "unverified" not in summary) and meta.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
            summary = summarize_output(self.load_results(meta))
            if summary is not None:
                meta["summary"] = summary
                self.save(meta)
        return summary or meta.get("summary")

    # -- repository reports (read-only) --------------------------------------

    def list_reports(self) -> list[dict]:
        items = []
        if not REPORTS_DIR.is_dir():
            return items
        for path in sorted(REPORTS_DIR.glob("*.json")):
            normalized = self._load_report_document(path)
            if normalized is None:
                continue
            summary = summarize_output(normalized) or {}
            items.append({
                "id": f"report:{path.stem}",
                "name": path.stem,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": "completed",
                "source": "report",
                "model": normalized.get("model"),
                "endpoint": normalized.get("endpoint"),
                "summary": summary,
            })
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return items

    def load_report(self, stem: str) -> Optional[dict]:
        path = REPORTS_DIR / f"{safe_profile_name(stem)}.json"
        return self._load_report_document(path)

    def delete_report(self, stem: str) -> bool:
        """Remove a committed report file from the working tree.

        The sanitization and parent check keep this inside reports/. The
        deletion is a working-tree change until committed, so it is
        recoverable via git until then.
        """
        path = REPORTS_DIR / f"{safe_profile_name(stem)}.json"
        if not path.is_file():
            return False
        resolved = path.resolve()
        if resolved.parent != REPORTS_DIR.resolve():
            return False
        resolved.unlink()
        return True

    def _load_report_document(self, path: Path) -> Optional[dict]:
        try:
            document = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return normalize_output(document)

    def read_log_tail(self, run_id: str, tail: int = 400) -> str:
        path = self.log_path(run_id)
        if not path.is_file():
            return ""
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-max(0, tail):])
