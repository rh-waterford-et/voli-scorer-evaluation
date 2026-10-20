"""Profile builder: compose, edit, and delete EPP scheduling profiles.

This is the only dashboard module that mutates cluster state, and every
mutation goes through an explicit apply chain:

  1. re-fetch the ConfigMap and refuse if it changed since the preview
  2. save the previous content as a backup under dashboard/data
  3. patch exactly one data key of one ConfigMap
  4. restart the EPP deployment and wait for it to become Ready
  5. verify the requested change is present in the live config

Failed rollouts are never auto-reverted; the UI offers an explicit revert
from the saved backup. The live ConfigMap is the only source of truth --
nothing here reads the repository templates.

YAML is round-tripped with ruamel.yaml so comments, ordering, and quoting
in the live config are preserved; only the requested change is written.
"""

import difflib
import io
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

import oc
from cluster import fetch_config
from paths import DATA_DIR, SCRIPTS_DIR

PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
BACKUP_ID = re.compile(r"^[A-Za-z0-9._-]+$")

BACKUP_DIR = DATA_DIR / "configmap-backups"
JOB_DIR = DATA_DIR / "builder-jobs"

# The gitignored local mirror of the live profile map, read by
# scripts/stream_metrics.py (takes precedence over profile_scorers.json).
SCRIPT_MAP_LOCAL = SCRIPTS_DIR / "profile_scorers_local.json"

STEP_LABELS = [
    ("check", "Re-checking the live ConfigMap"),
    ("backup", "Saving the current config as a backup"),
    ("patch", "Patching the ConfigMap"),
    ("restart", "Restarting the EPP deployment"),
    ("wait", "Waiting for EPP to become Ready"),
    ("verify", "Verifying the change in the live config"),
    ("sync", "Updating the script profile map"),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


# --- YAML round-trip -----------------------------------------------------------


_yaml = YAML()
_yaml.preserve_quotes = True


def load_config(text: str):
    try:
        return _yaml.load(text)
    except Exception as error:  # ruamel raises a variety of parser errors
        raise HTTPException(status_code=502, detail=f"cannot parse EPP plugin YAML: {error}")


def dump_config(config) -> str:
    stream = io.StringIO()
    _yaml.dump(config, stream)
    return stream.getvalue()


def plain(value):
    """Convert ruamel structures to plain JSON-serializable values."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return str(value)


# --- reading the live config ---------------------------------------------------


def classify(kind: str) -> str:
    kind = kind or ""
    if "scorer" in kind or kind == "context-length-aware":
        return "scorer"
    if "picker" in kind:
        return "picker"
    return "other"


def instances_of(config) -> list[dict]:
    result = []
    for plugin in config.get("plugins") or []:
        if not isinstance(plugin, dict) or not plugin.get("type"):
            continue
        result.append(
            {
                "name": plugin.get("name", plugin["type"]),
                "type": str(plugin["type"]),
                "kind": classify(str(plugin["type"])),
                "has_parameters": bool(plugin.get("parameters")),
            }
        )
    return result


def profiles_of(config) -> list[dict]:
    kinds = {item["name"]: item["kind"] for item in instances_of(config)}
    result = []
    for profile in config.get("schedulingProfiles") or []:
        if not isinstance(profile, dict):
            continue
        scorers, others, picker = [], [], None
        for ref in profile.get("plugins") or []:
            if not isinstance(ref, dict) or "pluginRef" not in ref:
                continue
            name = ref["pluginRef"]
            weight = ref.get("weight", 1)
            weight = weight if isinstance(weight, (int, float)) else None
            kind = kinds.get(name, "other")
            if kind == "picker":
                picker = name
            elif kind == "scorer":
                scorers.append({"name": name, "weight": weight})
            else:
                others.append({"name": name, "weight": weight})
        result.append(
            {
                "name": profile.get("name", "unnamed"),
                "scorers": scorers,
                "others": others,
                "picker": picker,
            }
        )
    return result


def default_profile_of(config) -> Optional[str]:
    for plugin in config.get("plugins") or []:
        if isinstance(plugin, dict) and plugin.get("type") == "header-profile-handler":
            value = (plugin.get("parameters") or {}).get("defaultProfile")
            if value:
                return str(value)
    return None


def helm_managed(configmap_json) -> bool:
    meta = configmap_json.get("metadata") or {}
    labels = meta.get("labels") or {}
    annotations = meta.get("annotations") or {}
    return (
        labels.get("app.kubernetes.io/managed-by") == "Helm"
        or "meta.helm.sh/release-name" in annotations
    )


def default_picker(profiles: list[dict], instances: list[dict]) -> Optional[str]:
    pickers = [item["name"] for item in instances if item["kind"] == "picker"]
    if not pickers:
        return None
    counts: dict[str, int] = {}
    for profile in profiles:
        if profile["picker"] in pickers:
            counts[profile["picker"]] = counts.get(profile["picker"], 0) + 1
    if counts:
        return max(counts.items(), key=lambda item: item[1])[0]
    if len(pickers) == 1:
        return pickers[0]
    if "maxScore" in pickers:
        return "maxScore"
    return pickers[0]


def build_state(fetched: dict) -> dict:
    config = load_config(fetched["text"])
    instances = instances_of(config)
    profiles = profiles_of(config)
    state = {
        "configmap": fetched["configmap_name"],
        "config_key": fetched["config_key"],
        "resource_version": fetched["resource_version"],
        "api_version": str(config.get("apiVersion") or ""),
        "default_profile": default_profile_of(config),
        "helm_managed": helm_managed(fetched["configmap"]),
        "picker_default": default_picker(profiles, instances),
        "instances": plain(instances),
        "profiles": plain(profiles),
    }
    warnings = []
    api = state["api_version"]
    if api and not api.startswith("llm-d.ai/v1"):
        warnings.append(
            f"apiVersion {api} is not llm-d.ai/v1 (v1alpha1 is marked deprecated upstream); "
            "the builder preserves it exactly as it is."
        )
    if state["helm_managed"]:
        warnings.append(
            "This ConfigMap is Helm-managed; a later Helm upgrade may overwrite "
            "profiles created or edited here."
        )
    state["warnings"] = warnings
    return state


# --- operations ----------------------------------------------------------------


class ScorerRefIn(BaseModel):
    name: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0, le=1000)


class BuilderOperation(BaseModel):
    action: Literal["create", "edit", "delete"]
    profile: str = Field(min_length=1, max_length=80)
    scorers: list[ScorerRefIn] = Field(default_factory=list)
    picker: Optional[str] = None


class BuilderRequest(BaseModel):
    namespace: str = "vllm-omni-validation"
    epp_deployment: str = "endpoint-picker-epp"
    epp_container: str = "epp"
    configmap: Optional[str] = None
    config_key: Optional[str] = None
    expected_resource_version: Optional[str] = None
    operation: BuilderOperation
    rollout_timeout: int = Field(default=240, ge=30, le=900)


class RevertRequest(BaseModel):
    backup_id: str = Field(min_length=1)


class SyncMapRequest(BaseModel):
    namespace: str = "vllm-omni-validation"
    epp_deployment: str = "endpoint-picker-epp"
    epp_container: str = "epp"
    configmap: Optional[str] = None
    config_key: Optional[str] = None


def validate_operation(state: dict, operation: BuilderOperation):
    """Return (errors, warnings, picker) for the operation against live state."""
    errors: list[str] = []
    warnings: list[str] = []
    existing = {profile["name"]: profile for profile in state["profiles"]}
    scorer_names = {i["name"] for i in state["instances"] if i["kind"] == "scorer"}
    picker_names = {i["name"] for i in state["instances"] if i["kind"] == "picker"}

    if not PROFILE_NAME.match(operation.profile):
        errors.append(
            "Profile name must start with a letter or digit and contain only "
            "letters, digits, dots, underscores, and dashes."
        )
    if operation.action == "create":
        if operation.profile in existing:
            errors.append(f"A profile named {operation.profile!r} already exists.")
        if not operation.scorers:
            errors.append("A new profile needs at least one scorer.")
    elif operation.action == "edit":
        if operation.profile not in existing:
            errors.append(f"Profile {operation.profile!r} does not exist.")
        if not operation.scorers:
            errors.append("A profile needs at least one scorer.")
    elif operation.action == "delete":
        if operation.profile not in existing:
            errors.append(f"Profile {operation.profile!r} does not exist.")
        if operation.profile == state.get("default_profile"):
            errors.append(
                f"{operation.profile!r} is the header profile handler's default "
                "profile and cannot be deleted."
            )
        if len(existing) <= 1:
            errors.append("The last remaining profile cannot be deleted.")

    seen: set[str] = set()
    for ref in operation.scorers:
        if ref.name not in scorer_names:
            errors.append(f"{ref.name!r} is not a scorer instance in the live config.")
        if ref.name in seen:
            errors.append(f"Scorer {ref.name!r} is listed more than once.")
        seen.add(ref.name)

    picker = operation.picker or state.get("picker_default")
    if operation.action in ("create", "edit"):
        if picker is None:
            errors.append("No picker plugin instance is available in the live config.")
        elif picker not in picker_names:
            errors.append(f"{picker!r} is not a picker instance in the live config.")
        if operation.action == "edit":
            others = existing.get(operation.profile, {}).get("others") or []
            if others:
                warnings.append(
                    f"{len(others)} non-scorer plugin ref(s) in this profile are preserved unchanged."
                )
    return errors, warnings, picker


def compose_text(text: str, operation: BuilderOperation, picker: Optional[str], preserved: list) -> str:
    config = load_config(text)
    profiles = config.get("schedulingProfiles")
    if profiles is None:
        profiles = config["schedulingProfiles"] = []
    index = next(
        (i for i, p in enumerate(profiles) if isinstance(p, dict) and p.get("name") == operation.profile),
        None,
    )
    if operation.action == "delete":
        if index is None:
            raise ValueError(f"profile {operation.profile!r} not found")
        del profiles[index]
        return dump_config(config)

    refs = []
    for ref in operation.scorers:
        weight = int(ref.weight) if float(ref.weight).is_integer() else ref.weight
        refs.append({"pluginRef": ref.name, "weight": weight})
    for other in preserved or []:
        entry = {"pluginRef": other["name"]}
        if other.get("weight") is not None:
            entry["weight"] = other["weight"]
        refs.append(entry)
    if picker:
        refs.append({"pluginRef": picker})
    entry = {"name": operation.profile, "plugins": refs}
    if index is None:
        profiles.append(entry)
    else:
        profiles[index] = entry
    return dump_config(config)


def operation_summary(operation: BuilderOperation, picker: Optional[str]) -> str:
    if operation.action == "delete":
        return f"delete profile {operation.profile}"
    parts = [f"{ref.name} (w{ref.weight:g})" for ref in operation.scorers]
    detail = " + ".join(parts) or "no scorers"
    return f"{operation.action} profile {operation.profile}: {detail}" + (
        f", picker {picker}" if picker else ""
    )


def resolve_operation(fetched: dict, operation: BuilderOperation) -> tuple[str, Optional[str]]:
    """Validate against the fetched live config and compose the new text."""
    state = build_state(fetched)
    errors, _warnings, picker = validate_operation(state, operation)
    if errors:
        raise ValueError("; ".join(errors))
    preserved = []
    if operation.action == "edit":
        existing = next((p for p in state["profiles"] if p["name"] == operation.profile), None)
        preserved = (existing or {}).get("others") or []
    return compose_text(fetched["text"], operation, picker, preserved), picker


def diff_texts(old: str, new: str, key: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"live/{key}",
            tofile=f"new/{key}",
            lineterm="",
        )
    )


def preview_operation(request: BuilderRequest) -> dict:
    fetched = fetch_config(
        request.namespace,
        request.epp_deployment,
        request.epp_container,
        request.configmap,
        request.config_key,
    )
    base = {
        "resource_version": fetched["resource_version"],
        "configmap": fetched["configmap_name"],
        "config_key": fetched["config_key"],
    }
    if (
        request.expected_resource_version
        and fetched["resource_version"] != request.expected_resource_version
    ):
        return {
            **base,
            "ok": False,
            "errors": [
                "The ConfigMap changed since it was loaded "
                f"(resourceVersion {request.expected_resource_version} -> "
                f"{fetched['resource_version']}). Refresh the profiles and try again."
            ],
            "warnings": [],
            "diff": "",
            "new_text": "",
            "picker": None,
            "summary": "",
        }
    try:
        new_text, picker = resolve_operation(fetched, request.operation)
    except ValueError as error:
        return {
            **base,
            "ok": False,
            "errors": [str(error)],
            "warnings": [],
            "diff": "",
            "new_text": "",
            "picker": None,
            "summary": "",
        }
    state = build_state(fetched)
    _errors, warnings, _picker = validate_operation(state, request.operation)
    return {
        **base,
        "ok": True,
        "errors": [],
        "warnings": warnings,
        "diff": diff_texts(fetched["text"], new_text, fetched["config_key"]),
        "new_text": new_text,
        "picker": picker,
        "summary": operation_summary(request.operation, picker),
    }


# --- script profile map sync ------------------------------------------------------


def _format_weight(weight) -> str:
    value = float(weight) if weight is not None else 1.0
    return str(int(value)) if value.is_integer() else f"{value:g}"


def sync_profile_map(state: dict, namespace: str) -> dict:
    """Mirror the live scheduling profiles into scripts/profile_scorers_local.json.

    Keeps stream_metrics.py's PROFILE_SCORERS (suite validation,
    --list-profiles, result scorer labels) in step with the live config
    without touching tracked repository files. The file is gitignored, so
    syncing never creates repo churn.
    """
    types = {item["name"]: item["type"] for item in state["instances"]}
    profiles: dict[str, str] = {}
    for profile in state["profiles"]:
        scorers = profile.get("scorers") or []
        if not scorers:
            profiles[profile["name"]] = "no scorers"
            continue
        parts = []
        for scorer in scorers:
            kind = types.get(scorer["name"], scorer["name"])
            weight = scorer["weight"] if scorer["weight"] is not None else 1
            if len(scorers) == 1 and float(weight) == 1.0:
                parts.append(kind)
            else:
                parts.append(f"{kind} ({_format_weight(weight)})")
        profiles[profile["name"]] = " + ".join(parts)
    document = {
        "synced_at": _now(),
        "source": (
            f"{state['configmap']}/{state['config_key']} in {namespace} "
            f"(resourceVersion {state['resource_version']})"
        ),
        "profiles": profiles,
    }
    SCRIPT_MAP_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    temporary = SCRIPT_MAP_LOCAL.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n")
    temporary.replace(SCRIPT_MAP_LOCAL)
    return document


# --- backups --------------------------------------------------------------------


def save_backup(fetched: dict, namespace: str, epp_deployment: str, summary: str) -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = {
        "id": _new_id(),
        "created_at": _now(),
        "namespace": namespace,
        "epp_deployment": epp_deployment,
        "configmap": fetched["configmap_name"],
        "config_key": fetched["config_key"],
        "resource_version": fetched["resource_version"],
        "operation": summary,
        "text": fetched["text"],
    }
    (BACKUP_DIR / f"{backup['id']}.json").write_text(json.dumps(backup, indent=2) + "\n")
    return backup


def load_backup(backup_id: str) -> dict:
    if not BACKUP_ID.match(backup_id):
        raise HTTPException(status_code=404, detail="backup not found")
    path = BACKUP_DIR / f"{backup_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="backup not found")
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail=f"cannot read backup: {error}")


def list_backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return []
    items = []
    for path in BACKUP_DIR.glob("*.json"):
        try:
            document = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        document.pop("text", None)
        items.append(document)
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return items


# --- apply jobs -----------------------------------------------------------------


class _StepFailed(Exception):
    pass


class ApplyJob:
    """Executes the preview -> backup -> patch -> restart -> wait -> verify chain."""

    def __init__(
        self,
        kind: str,
        summary: str,
        *,
        namespace: str,
        epp_deployment: str,
        epp_container: str,
        configmap: Optional[str] = None,
        config_key: Optional[str] = None,
        expected_resource_version: Optional[str] = None,
        operation: Optional[BuilderOperation] = None,
        restore_text: Optional[str] = None,
        rollout_timeout: int = 240,
    ):
        self.id = _new_id()
        self.kind = kind  # "apply" | "revert"
        self.summary = summary
        self.status = "running"
        self.error: Optional[str] = None
        self.revert_available = False
        self.backup_id: Optional[str] = None
        self.created_at = _now()
        self.steps = [
            {"key": key, "label": label, "status": "pending", "detail": None}
            for key, label in STEP_LABELS
        ]
        self._namespace = namespace
        self._epp_deployment = epp_deployment
        self._epp_container = epp_container
        self._configmap = configmap
        self._config_key = config_key
        self._expected_rv = expected_resource_version
        self._operation = operation
        self._restore_text = restore_text
        self._rollout_timeout = rollout_timeout
        self._lock = threading.Lock()

    # -- plumbing ------------------------------------------------------------

    def start(self) -> None:
        thread = threading.Thread(target=self._execute, name=f"builder-{self.id}", daemon=True)
        thread.start()

    def view(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "error": self.error,
                "summary": self.summary,
                "created_at": self.created_at,
                "steps": json.loads(json.dumps(self.steps)),
                "backup_id": self.backup_id,
                "revert_available": self.revert_available,
            }

    def _persist(self) -> None:
        JOB_DIR.mkdir(parents=True, exist_ok=True)
        (JOB_DIR / f"{self.id}.json").write_text(json.dumps(self.view(), indent=2) + "\n")

    def _set(self, key: str, status: str, detail: Optional[str] = None) -> None:
        with self._lock:
            for step in self.steps:
                if step["key"] == key:
                    step["status"] = status
                    if detail is not None:
                        step["detail"] = detail
        self._persist()

    def _step(self, key: str, action):
        """Run one step; mark failed and abort the job on any exception."""
        self._set(key, "running")
        try:
            detail = action()
        except Exception as error:  # noqa: BLE001 - surfaced to the UI as-is
            message = str(getattr(error, "detail", None) or error)
            with self._lock:
                for step in self.steps:
                    if step["key"] == key:
                        step["status"] = "failed"
                        step["detail"] = message
                self.status = "failed"
                self.error = message
            self._persist()
            raise _StepFailed(message)
        self._set(key, "done", detail)

    # -- the chain --------------------------------------------------------------

    def _execute(self) -> None:
        fetched: dict = {}
        new_text: Optional[str] = None

        def do_check() -> Optional[str]:
            nonlocal fetched, new_text
            fetched = fetch_config(
                self._namespace,
                self._epp_deployment,
                self._epp_container,
                self._configmap,
                self._config_key,
            )
            rv = fetched["resource_version"]
            if (
                self.kind == "apply"
                and self._expected_rv
                and rv != self._expected_rv
            ):
                raise RuntimeError(
                    "The ConfigMap changed since the preview "
                    f"(live resourceVersion {rv}, previewed {self._expected_rv}). "
                    "Refresh the profiles and preview again."
                )
            if self.kind == "revert":
                return None
            assert self._operation is not None
            new_text, _picker = resolve_operation(fetched, self._operation)
            return None

        def do_backup() -> str:
            backup = save_backup(
                fetched, self._namespace, self._epp_deployment, self.summary
            )
            with self._lock:
                self.backup_id = backup["id"]
            return f"backup {backup['id']}"

        def do_patch() -> str:
            text = self._restore_text if self.kind == "revert" else new_text
            oc.oc_run(
                [
                    "patch",
                    "configmap",
                    fetched["configmap_name"],
                    "-n",
                    self._namespace,
                    "--type",
                    "merge",
                    "-p",
                    json.dumps({"data": {fetched["config_key"]: text}}),
                ]
            )
            with self._lock:
                self.revert_available = True
            return f"{fetched['configmap_name']} / {fetched['config_key']}"

        def do_restart() -> str:
            oc.oc_run(["rollout", "restart", f"deployment/{self._epp_deployment}", "-n", self._namespace])
            return f"deployment/{self._epp_deployment}"

        def do_wait() -> str:
            oc.oc_run(
                [
                    "rollout",
                    "status",
                    f"deployment/{self._epp_deployment}",
                    "-n",
                    self._namespace,
                    "--timeout",
                    f"{self._rollout_timeout}s",
                ],
                timeout=self._rollout_timeout + 60,
            )
            return "Ready"

        def do_verify() -> str:
            after = fetch_config(
                self._namespace,
                self._epp_deployment,
                self._epp_container,
                self._configmap,
                self._config_key,
            )
            if self.kind == "revert":
                if after["text"] != self._restore_text:
                    raise RuntimeError("The live config does not match the restored backup content.")
                return "matches the backup"
            assert self._operation is not None
            state = build_state(after)
            names = [profile["name"] for profile in state["profiles"]]
            operation = self._operation
            if operation.action == "delete":
                if operation.profile in names:
                    raise RuntimeError(f"{operation.profile!r} is still present in the live config.")
                return f"{operation.profile!r} removed"
            profile = next(
                (p for p in state["profiles"] if p["name"] == operation.profile), None
            )
            if profile is None:
                raise RuntimeError(f"{operation.profile!r} not found in the live config after apply.")
            expected = sorted([ref.name, round(float(ref.weight), 6)] for ref in operation.scorers)
            actual = sorted(
                [ref["name"], round(float(ref["weight"] or 1), 6)] for ref in profile["scorers"]
            )
            if expected != actual:
                raise RuntimeError(
                    f"Live scorers for {operation.profile!r} do not match the requested ones."
                )
            return f"{operation.profile!r} present with the requested scorers"

        def do_sync() -> str:
            fetched_after = fetch_config(
                self._namespace,
                self._epp_deployment,
                self._epp_container,
                self._configmap,
                self._config_key,
            )
            state = build_state(fetched_after)
            document = sync_profile_map(state, self._namespace)
            return f"{len(document['profiles'])} profiles -> {SCRIPT_MAP_LOCAL.name}"

        try:
            self._step("check", do_check)
            self._step("backup", do_backup)
            self._step("patch", do_patch)
            self._step("restart", do_restart)
            self._step("wait", do_wait)
            self._step("verify", do_verify)
            self._step("sync", do_sync)
            with self._lock:
                self.status = "done"
            self._persist()
        except _StepFailed:
            pass  # step already marked failed and persisted


class BuilderManager:
    def __init__(self):
        self._live: dict[str, ApplyJob] = {}
        self._persisted: dict[str, dict] = {}
        JOB_DIR.mkdir(parents=True, exist_ok=True)
        for path in JOB_DIR.glob("*.json"):
            try:
                view = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if view.get("status") == "running":
                view["status"] = "interrupted"
                view["error"] = "dashboard backend restarted during this job"
                path.write_text(json.dumps(view, indent=2) + "\n")
            self._persisted[view["id"]] = view

    def start_apply(self, request: BuilderRequest) -> str:
        job = ApplyJob(
            "apply",
            operation_summary(request.operation, request.operation.picker),
            namespace=request.namespace,
            epp_deployment=request.epp_deployment,
            epp_container=request.epp_container,
            configmap=request.configmap,
            config_key=request.config_key,
            expected_resource_version=request.expected_resource_version,
            operation=request.operation,
            rollout_timeout=request.rollout_timeout,
        )
        self._live[job.id] = job
        job._persist()
        job.start()
        return job.id

    def start_revert(self, backup_id: str) -> str:
        backup = load_backup(backup_id)
        job = ApplyJob(
            "revert",
            f"restore backup {backup_id} ({backup.get('operation') or 'unknown operation'})",
            namespace=backup["namespace"],
            epp_deployment=backup["epp_deployment"],
            epp_container="epp",
            restore_text=backup["text"],
        )
        self._live[job.id] = job
        job._persist()
        job.start()
        return job.id

    def get_job(self, job_id: str) -> Optional[dict]:
        job = self._live.get(job_id)
        if job is not None:
            view = job.view()
            if view["status"] in ("done", "failed", "interrupted"):
                self._persisted[job_id] = view
            return view
        return self._persisted.get(job_id)

    def list_jobs(self, limit: int = 30) -> list[dict]:
        views = {view["id"]: view for view in self._persisted.values()}
        for job in self._live.values():
            views[job.id] = job.view()
        ordered = sorted(views.values(), key=lambda view: view.get("created_at", ""), reverse=True)
        return ordered[:limit]
