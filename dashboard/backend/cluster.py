"""Profile discovery.

Two sources:
  * builtin  -- the PROFILE_SCORERS map inside scripts/stream_metrics.py.
                No cluster access at all.
  * cluster  -- the live EPP plugin ConfigMap, via read-only `oc get`
                commands (deployment + configmap). Nothing here ever
                modifies cluster state.

The cluster path reuses scripts/epp_scores.py (config_location) to find the
ConfigMap name and key from the EPP Deployment, then parses every
schedulingProfile with its scorers, weights, filters, and picker.
"""

import json
import subprocess
import sys

from fastapi import HTTPException

from paths import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

import epp_scores  # noqa: E402  (repository script, reused read-only)


def builtin_profiles() -> list[dict]:
    from stream_metrics import PROFILE_SCORERS

    profiles = [
        {
            "name": name,
            "source": "builtin",
            "scorers": [{"name": None, "type": scorer, "weight": None}],
            "filters": [],
            "pickers": [],
        }
        for name, scorer in PROFILE_SCORERS.items()
    ]
    # "default" is special in the benchmark script's single-profile mode: it
    # sends no EPP-Profile header, so EPP applies its own configured default
    # profile. Offer it as an explicit opt-in; the UI lists it last with a
    # label that makes the no-header behavior clear.
    profiles.append(
        {
            "name": "default",
            "source": "builtin",
            "scorers": [],
            "filters": [],
            "pickers": [],
        }
    )
    return profiles


def _oc_json(args: list[str], timeout: float = 25.0) -> dict:
    completed = subprocess.run(
        ["oc", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if completed.returncode:
        detail = completed.stderr.strip()[:400] or f"oc exited {completed.returncode}"
        raise HTTPException(status_code=502, detail=f"oc {' '.join(args[:4])} failed: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=502, detail=f"oc output was not JSON: {error}") from error


def discover_profiles(
    namespace: str,
    epp_deployment: str,
    epp_container: str,
    configmap: str | None = None,
    config_key: str | None = None,
) -> dict:
    """Read-only discovery of every scheduling profile in the live EPP config."""
    deployment = _oc_json(["get", "deployment", epp_deployment, "-n", namespace, "-o", "json"])
    try:
        containers = deployment["spec"]["template"]["spec"]["containers"]
        container = next(c for c in containers if c.get("name") == epp_container)
    except (KeyError, TypeError, StopIteration):
        raise HTTPException(
            status_code=502,
            detail=f"container {epp_container!r} not found in deployment {epp_deployment!r}",
        )
    try:
        name, key = epp_scores.config_location(deployment, container, configmap, config_key)
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"cannot locate EPP config: {error}")

    configmap_json = _oc_json(["get", "configmap", name, "-n", namespace, "-o", "json"])
    text = (configmap_json.get("data") or {}).get(key)
    if text is None:
        raise HTTPException(
            status_code=502, detail=f"configmap {name} has no data key {key!r}"
        )

    try:
        import yaml
    except ImportError:
        raise HTTPException(
            status_code=500, detail="PyYAML is not installed in the dashboard venv"
        )
    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise HTTPException(status_code=502, detail=f"invalid EPP plugin YAML: {error}")
    if not isinstance(config, dict):
        raise HTTPException(status_code=502, detail="EPP plugin configuration is not a mapping")

    instances: dict[str, str] = {}
    for plugin in config.get("plugins") or []:
        if isinstance(plugin, dict) and plugin.get("type"):
            instances[plugin.get("name", plugin["type"])] = plugin["type"]

    profile_defs = config.get("schedulingProfiles")
    if not profile_defs:
        profile_defs = [
            {"name": "default", "plugins": [{"pluginRef": n} for n in instances]}
        ]

    profiles = []
    for profile in profile_defs:
        if not isinstance(profile, dict):
            continue
        scorers, filters, pickers = [], [], []
        for ref in profile.get("plugins") or []:
            if not isinstance(ref, dict) or "pluginRef" not in ref:
                continue
            ref_name = ref["pluginRef"]
            kind = instances.get(ref_name, ref_name)
            weight = ref.get("weight", 1.0)
            entry = {
                "name": ref_name,
                "type": kind,
                "weight": weight if isinstance(weight, (int, float)) else None,
            }
            if "scorer" in kind or kind == "context-length-aware":
                scorers.append(entry)
            elif "picker" in kind:
                pickers.append(entry)
            else:
                filters.append(entry)
        profiles.append(
            {
                "name": profile.get("name", "unnamed"),
                "source": "cluster",
                "scorers": scorers,
                "filters": filters,
                "pickers": pickers,
            }
        )

    return {
        "namespace": namespace,
        "epp_deployment": epp_deployment,
        "configmap": name,
        "config_key": key,
        "resource_version": (configmap_json.get("metadata") or {}).get("resourceVersion"),
        "api_version": config.get("apiVersion"),
        "profiles": profiles,
    }
