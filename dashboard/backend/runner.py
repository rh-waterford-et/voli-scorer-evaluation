"""Benchmark orchestration.

One dashboard "run" executes scripts/stream_metrics.py once per selected
profile, sequentially, in single-profile mode. Each invocation writes its
--output-json file under the run directory; the store merges them into one
document for the UI.

Subprocess output is appended to <run>/log.txt and streamed live to SSE
subscribers. Progress lines printed by the script (one per profile/attempt
load setting) are parsed and forwarded as structured progress events.

The benchmark command can be overridden for development/testing:
    VOLI_BENCH_PYTHON  interpreter used to run the benchmark (default: the
                       interpreter running this backend)
    VOLI_BENCH_CMD     path to a benchmark script to run instead of
                       scripts/stream_metrics.py (e.g. dashboard/dev/stub_benchmark.py)
"""

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from paths import BENCHMARK_SCRIPT, REPO_DIR
from store import new_run_id, now_iso, summarize_output

# Greedy scorer group + end anchor: scorer labels may themselves contain
# parentheses, e.g. "queue-scorer (weight 2) + running-requests-size-scorer (weight 1)".
PROGRESS = re.compile(
    r"^\s*(?P<profile>\S+)\s+\((?P<scorer>.*)\):\s+"
    r"(?P<iterations>\d+)\s+requests,\s+concurrency\s+(?P<concurrency>\d+)\.\.\.\s*$"
)

ACTIVE_STATUSES = {"queued", "running"}
LOG_TAIL_LINES = 1000


def benchmark_command() -> list[str]:
    python = os.environ.get("VOLI_BENCH_PYTHON") or sys.executable
    override = os.environ.get("VOLI_BENCH_CMD")
    if override:
        return [python, override]
    return [python, str(BENCHMARK_SCRIPT)]


class ManagedRun:
    """A run in flight (or recently finished), with an SSE event bus."""

    def __init__(self, meta: dict, store):
        self.meta = meta
        self.store = store
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []
        self._log_tail: deque = deque(maxlen=LOG_TAIL_LINES)
        self._log_file = None
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._thread: Optional[threading.Thread] = None

    @property
    def run_id(self) -> str:
        return self.meta["id"]

    @property
    def status(self) -> str:
        return self.meta.get("status", "unknown")

    # -- event bus -----------------------------------------------------------

    def _emit(self, kind: str, data: dict) -> None:
        event = {"kind": kind, "data": data}
        for subscriber in list(self._subscribers):
            subscriber.put(event)

    def _append_log(self, stream: str, line: str) -> None:
        with self._lock:
            self._log_tail.append(line)
            if self._log_file is not None and not self._log_file.closed:
                try:
                    self._log_file.write(line + "\n")
                    self._log_file.flush()
                except OSError:
                    pass
        self._emit("log", {"stream": stream, "line": line})

    def subscribe(self):
        """Register a subscriber; returns (queue, snapshot)."""
        subscriber: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
            snapshot = {
                "meta": json.loads(json.dumps(self.meta)),
                "log_tail": list(self._log_tail),
            }
        return subscriber, snapshot

    def unsubscribe(self, subscriber) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    # -- meta helpers ---------------------------------------------------------

    def _meta_copy(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self.meta))

    def _save(self) -> None:
        self.store.save(self._meta_copy())

    def _update_attempt(self, attempt: dict, **fields) -> None:
        with self._lock:
            attempt.update(fields)
            view = dict(attempt)
            index = self.meta["profiles"].index(attempt) + 1
            total = len(self.meta["profiles"])
        view["index"] = index
        view["total"] = total
        self._emit("profile", view)

    def _log_tail_text(self, lines: int) -> list[str]:
        with self._lock:
            return list(self._log_tail)[-lines:]

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._execute, name=f"run-{self.run_id}", daemon=True
        )
        self._thread.start()

    def cancel(self) -> bool:
        if self.status not in ACTIVE_STATUSES:
            return False
        self._cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.terminate()
                except OSError:
                    pass
        return True

    def _execute(self) -> None:
        log_path = self.store.log_path(self.run_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(log_path, "a", encoding="utf-8")
        try:
            with self._lock:
                self.meta["status"] = "running"
            self._save()
            for attempt in self.meta["profiles"]:
                if self._cancelled:
                    self._update_attempt(attempt, status="skipped")
                    continue
                self._update_attempt(attempt, status="running")
                self._run_attempt(attempt)
            statuses = {attempt["status"] for attempt in self.meta["profiles"]}
            if self._cancelled:
                overall = "cancelled"
            elif "failed" in statuses or "skipped" in statuses:
                overall = "failed"
            elif statuses == {"completed"}:
                overall = "completed"
            else:
                overall = "failed"
            with self._lock:
                self.meta["status"] = overall
                self.meta["finished_at"] = now_iso()
                self.meta["summary"] = summarize_output(self.store.load_results(self.meta))
            self._save()
        finally:
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None
            self._emit("done", {"status": self.meta.get("status")})

    def _run_attempt(self, attempt: dict) -> None:
        argv = attempt["argv"]
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(REPO_DIR),
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
            )
        except OSError as error:
            self._update_attempt(attempt, status="failed", error=f"cannot start benchmark: {error}")
            return
        self._proc = proc

        def pump(stream, tag: str) -> None:
            try:
                for line in iter(stream.readline, ""):
                    line = line.rstrip("\n")
                    self._append_log(tag, line)
                    if tag == "stdout":
                        match = PROGRESS.match(line)
                        if match:
                            data = match.groupdict()
                            data["iterations"] = int(data["iterations"])
                            data["concurrency"] = int(data["concurrency"])
                            self._emit("progress", data)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        readers = [
            threading.Thread(target=pump, args=(proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=pump, args=(proc.stderr, "stderr"), daemon=True),
        ]
        for reader in readers:
            reader.start()
        returncode = proc.wait()
        for reader in readers:
            reader.join(timeout=5)
        self._proc = None

        with self._lock:
            attempt["returncode"] = returncode
        result_path = self.store.run_dir(self.run_id) / attempt["result_file"]
        if self._cancelled and returncode != 0:
            status, error = "cancelled", "cancelled by user"
        elif returncode == 0 and result_path.is_file():
            status, error = "completed", None
        else:
            tail = "\n".join(self._log_tail_text(15))
            status = "failed"
            error = (tail or f"benchmark exited with code {returncode}")[-800:]
        self._update_attempt(attempt, status=status, error=error)
        self._save()


class RunManager:
    def __init__(self, store):
        self.store = store
        self.command = benchmark_command()
        self.runs: dict[str, ManagedRun] = {}
        self._lock = threading.Lock()

    def get(self, run_id: str) -> Optional[ManagedRun]:
        with self._lock:
            return self.runs.get(run_id)

    def plan(self, params, run_id: Optional[str] = None) -> tuple[str, list[dict]]:
        """Build run id and per-profile attempts without starting anything.

        Does not touch disk: result and prompts paths are computed only.
        """
        run_id = run_id or new_run_id()
        attempts = []
        prompts_path = None
        if (params.prompts_text or "").strip():
            prompts_path = self.store.prompts_path(run_id)
        for profile in params.profile_names:
            result_path = self.store.profile_result_path(run_id, profile)
            argv = self.command + params.attempt_argv(profile, result_path, prompts_path)
            attempts.append({
                "name": profile,
                "status": "queued",
                "argv": argv,
                "returncode": None,
                "result_file": str(result_path.relative_to(self.store.run_dir(run_id))),
                "error": None,
            })
        return run_id, attempts

    def preview(self, params) -> dict:
        run_id, attempts = self.plan(params)
        return {
            "run_id": run_id,
            "profiles": [{"name": a["name"], "argv": a["argv"]} for a in attempts],
        }

    def create(self, name: Optional[str], params) -> ManagedRun:
        run_id, attempts = self.plan(params)
        label = (name or "").strip() or ", ".join(params.profile_names)[:80]
        meta = self.store.create(run_id, label, params.model_dump())
        profiles_dir = self.store.run_dir(run_id) / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        if (params.prompts_text or "").strip():
            self.store.write_prompts(run_id, params.prompts_text)
        with self._lock:
            meta["profiles"] = attempts
        self.store.save(meta)
        run = ManagedRun(meta, self.store)
        with self._lock:
            self.runs[run_id] = run
        run.start()
        return run
