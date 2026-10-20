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
import sys

from fastapi import HTTPException

import oc
from paths import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

import epp_scores  # noqa: E402  (repository script, reused read-only)


def builtin_profiles() -> list[dict]:
    from stream_metrics import load_profile_scorers

    profiles = [
        {
            "name": name,
            "source": "builtin",
            "scorers": [{"name": None, "type": scorer, "weight": None}],
            "filters": [],
            "pickers": [],
        }
        for name, scorer in load_profile_scorers().items()
        if name != "default"
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


def map_source_info() -> dict:
    """Which profile map file stream_metrics.py will use right now."""
    local = SCRIPTS_DIR / "profile_scorers_local.json"
    if local.is_file():
        try:
            document = json.loads(local.read_text())
            profiles = document.get("profiles") or {}
            return {
                "map_source": "local",
                "map_synced_at": document.get("synced_at"),
                "map_sync_source": document.get("source"),
                "map_profiles": len(profiles),
            }
        except (OSError, ValueError):
            pass
    return {
        "map_source": "default",
        "map_synced_at": None,
        "map_sync_source": "tracked default: scripts/profile_scorers.json",
        "map_profiles": None,
    }


def _oc_json(args: list[str], timeout: float = 25.0) -> dict:
    # Goes through oc.oc_json so VOLI_OC_CMD (offline testing) applies here too.
    try:
        return oc.oc_json(args, timeout)
    except oc.OcError as error:
        raise HTTPException(status_code=502, detail=str(error))


def fetch_config(
    namespace: str,
    epp_deployment: str,
    epp_container: str,
    configmap: str | None = None,
    config_key: str | None = None,
) -> dict:
    """Read-only: locate the EPP plugin ConfigMap and fetch its content.

    Returns the deployment/configmap JSON, the resolved ConfigMap name and
    data key, the raw config text, and the ConfigMap resourceVersion.
    """
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
    resource_version = (configmap_json.get("metadata") or {}).get("resourceVersion")
    return {
        "deployment": deployment,
        "configmap": configmap_json,
        "configmap_name": name,
        "config_key": key,
        "text": text,
        "resource_version": str(resource_version) if resource_version is not None else None,
    }


def discover_profiles(
    namespace: str,
    epp_deployment: str,
    epp_container: str,
    configmap: str | None = None,
    config_key: str | None = None,
) -> dict:
    """Read-only discovery of every scheduling profile in the live EPP config."""
    fetched = fetch_config(namespace, epp_deployment, epp_container, configmap, config_key)
    text = fetched["text"]
    configmap_json = fetched["configmap"]
    name = fetched["configmap_name"]
    key = fetched["config_key"]

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
