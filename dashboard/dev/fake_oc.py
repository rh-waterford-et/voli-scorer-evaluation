#!/usr/bin/env python3
"""Offline stand-in for the oc CLI, used to test the profile builder.

Run the backend with:

    VOLI_OC_CMD=dashboard/dev/fake_oc.py \
      dashboard/.venv/bin/uvicorn app:app --app-dir dashboard/backend --port 8765

State is a JSON file (FAKE_OC_STATE, default dashboard/data/fake-oc-state.json),
seeded on first run from templates/endpoint-picker-epp-configmap.yaml, so the
fake cluster starts with the same tts.yaml content as the repo template.

Supported commands (exactly the ones the dashboard issues):
  get deployment NAME -n NS -o json
  get configmap NAME -n NS -o json
  patch configmap NAME -n NS --type merge -p JSON
  rollout restart deployment/NAME -n NS
  rollout status deployment/NAME -n NS --timeout=Ns

FAKE_OC_MODE forces a failure for testing failure paths: "patch", "restart",
or "rollout".
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
STATE_PATH = Path(
    os.environ.get("FAKE_OC_STATE") or REPO / "dashboard" / "data" / "fake-oc-state.json"
)
TEMPLATE = REPO / "templates" / "endpoint-picker-epp-configmap.yaml"
MODE = os.environ.get("FAKE_OC_MODE") or ""

NAMESPACE = "vllm-omni-validation"
CONFIGMAP = "endpoint-picker-epp"
DEPLOYMENT = "endpoint-picker-epp"


def fail(message: str, code: int = 1):
    print(message, file=sys.stderr)
    sys.exit(code)


def make_configmap(name: str, namespace: str, data: dict) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "resourceVersion": "1000",
            "labels": {"app.kubernetes.io/managed-by": "Helm"},
            "annotations": {
                "meta.helm.sh/release-name": "endpoint-picker",
                "meta.helm.sh/release-namespace": namespace,
            },
        },
        "data": data,
    }


def make_deployment(name: str, namespace: str, configmap: str) -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "containers": [
                        {
                            "name": "epp",
                            "image": "fake-epp:latest",
                            "args": ["--config-file=/config/tts.yaml"],
                            "volumeMounts": [{"name": "epp-config", "mountPath": "/config"}],
                        }
                    ],
                    "volumes": [{"name": "epp-config", "configMap": {"name": configmap}}],
                },
            },
        },
        "_status": "ready",
    }


def load_or_seed() -> dict:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    import yaml  # available in the dashboard venv

    template = yaml.safe_load(TEMPLATE.read_text())
    data = template.get("data") or {}
    state = {
        "configmaps": {f"{NAMESPACE}/{CONFIGMAP}": make_configmap(CONFIGMAP, NAMESPACE, data)},
        "deployments": {f"{NAMESPACE}/{DEPLOYMENT}": make_deployment(DEPLOYMENT, NAMESPACE, CONFIGMAP)},
    }
    save(state)
    return state


def save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        fail("fake_oc: no command given", 2)
    state = load_or_seed()

    def find(flag: str, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    command = args[0]

    if command == "get":
        kind, name = args[1], args[2]
        namespace = find("-n")
        key = f"{namespace}/{name}"
        if kind == "deployment":
            deployment = state["deployments"].get(key)
            if deployment is None:
                fail(f'Error from server (NotFound): deployments.apps "{name}" not found')
            print(json.dumps(deployment))
        elif kind == "configmap":
            configmap = state["configmaps"].get(key)
            if configmap is None:
                fail(f'Error from server (NotFound): configmaps "{name}" not found')
            print(json.dumps(configmap))
        else:
            fail(f"fake_oc: unsupported get kind {kind!r}", 2)

    elif command == "patch":
        # patch configmap NAME -n NS --type merge -p PAYLOAD
        name = args[2]
        namespace = find("-n")
        payload = find("-p")
        if MODE == "patch":
            fail("fake_oc: simulated patch failure")
        key = f"{namespace}/{name}"
        configmap = state["configmaps"].get(key)
        if configmap is None:
            fail(f'Error from server (NotFound): configmaps "{name}" not found')
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as error:
            fail(f"fake_oc: invalid patch payload: {error}", 2)
        configmap.setdefault("data", {}).update(document.get("data") or {})
        configmap["metadata"]["resourceVersion"] = str(
            int(configmap["metadata"]["resourceVersion"]) + 1
        )
        save(state)
        print(f"configmap/{name} patched")

    elif command == "rollout":
        subcommand, target = args[1], args[2]
        name = target.split("/", 1)[1]
        namespace = find("-n")
        key = f"{namespace}/{name}"
        if subcommand == "restart":
            if MODE == "restart":
                fail("fake_oc: simulated rollout restart failure")
            if key not in state["deployments"]:
                fail(f'Error from server (NotFound): deployments.apps "{name}" not found')
            state["deployments"][key]["_status"] = "restarting"
            save(state)
            print(f"deployment.apps/{name} restarted")
        elif subcommand == "status":
            if MODE == "rollout":
                fail(f'error: deployment "{name}" exceeded its progress deadline')
            deployment = state["deployments"].get(key)
            if deployment is None:
                fail(f'error: deployment "{name}" not found')
            if deployment.get("_status") == "restarting":
                deployment["_status"] = "ready"
                save(state)
            print(f'deployment "{name}" successfully rolled out')
        else:
            fail(f"fake_oc: unsupported rollout subcommand {subcommand!r}", 2)

    else:
        fail(f"fake_oc: unsupported command {command!r}", 2)


if __name__ == "__main__":
    main()
