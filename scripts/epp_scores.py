"""Collect request-correlated EPP debug scores without changing the cluster."""

from collections import Counter, defaultdict
import json
import math
import posixpath
import subprocess
import tempfile
import threading
import time


MESSAGES = {
    "Before running scorer plugins", "Calculated score",
    "Candidate pods for picking", "Completed running picker plugin successfully",
}


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def endpoint(value, namespace):
    """Unwrap scored endpoints and keep rank IDs distinct from pod names."""
    while isinstance(value, dict) and isinstance(value.get("Endpoint"), dict):
        value = value["Endpoint"]
    if isinstance(value, str):
        return value if "/" in value else f"{namespace}/{value}", None, {}
    if not isinstance(value, dict):
        return None, None, {}
    identity = value.get("ID", value)
    if not isinstance(identity, dict):
        return endpoint(identity, namespace)
    name = identity.get("name", identity.get("Name"))
    ns = identity.get("namespace", identity.get("Namespace", namespace))
    pod = value.get("Name") if "ID" in value else None
    metrics = {key: value[key] for key in (
        "WaitingQueueSize", "RunningRequestsSize", "KVCacheUsagePercent", "UpdateTime"
    ) if key in value}
    return (f"{ns}/{name}" if name else None), pod, metrics


def plugin_identity(value):
    if isinstance(value, dict):
        return value.get("Name", value.get("name")), value.get("Type", value.get("type"))
    if isinstance(value, str):
        parts = value.split("/", 1)
        return parts[0], parts[1] if len(parts) == 2 else None
    return None, None


def profile_scorers(config_text, profile):
    # This dependency is only needed when the optional collector is enabled.
    import yaml
    try:
        config = yaml.safe_load(config_text)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid EPP plugin YAML: {error}") from error
    if not isinstance(config, dict):
        raise ValueError("EPP plugin configuration is not a YAML mapping")
    instances = {p.get("name", p["type"]): p["type"] for p in config.get("plugins", [])}
    profiles = config.get("schedulingProfiles")
    if profiles is None:
        profiles = [{"name": "default", "plugins": [
            {"pluginRef": name} for name in instances
        ]}]
    selected = next((p for p in profiles if p.get("name") == profile), None)
    if selected is None:
        raise ValueError(f"profile {profile!r} is absent from the EPP ConfigMap")
    scorers = {}
    for ref in selected.get("plugins", []):
        name = ref["pluginRef"]
        kind = instances.get(name, name)
        if "scorer" not in kind and kind != "context-length-aware":
            continue
        weight = number(ref.get("weight", 1.0))
        if weight is None:
            raise ValueError(f"invalid scorer weight for {name!r}")
        scorers[name] = {"type": kind, "weight": weight}
    return scorers


def config_location(deployment, container, override_name=None, override_key=None):
    args = container.get("args", [])
    config_file = next((a.split("=", 1)[1] for a in args if a.startswith("--config-file=")), None)
    if config_file is None and "--config-file" in args:
        config_file = args[args.index("--config-file") + 1]
    config_file = config_file or "/config/tts.yaml"
    volumes = {v["name"]: v for v in deployment["spec"]["template"]["spec"].get("volumes", [])}
    for mount in sorted(container.get("volumeMounts", []), key=lambda m: len(m["mountPath"]), reverse=True):
        path = mount["mountPath"].rstrip("/")
        if config_file != path and not config_file.startswith(path + "/"):
            continue
        cm = volumes.get(mount["name"], {}).get("configMap", {})
        if not cm.get("name"):
            continue
        relative = mount.get("subPath") or posixpath.relpath(config_file, path)
        key = next((item["key"] for item in cm.get("items", []) if item["path"] == relative), relative)
        return override_name or cm["name"], override_key or key
    if override_name:
        return override_name, override_key or posixpath.basename(config_file)
    raise ValueError("cannot find the EPP config volume; pass --epp-configmap and --epp-config-key")


class ScoreRecords:
    """Group by request ID and EPP pod; never associate concurrent logs by order."""

    def __init__(self, namespace):
        self.namespace = namespace
        self.records = defaultdict(list)
        self.lock = threading.Lock()
        self.uncorrelated = 0

    def feed(self, line, pod):
        if not any(message in line for message in MESSAGES):
            return
        try:
            row = json.loads(line[line.index("{"):])
        except (ValueError, TypeError):
            return
        message = row.get("body", row.get("msg"))
        if message not in MESSAGES:
            return
        request_id = row.get("x-request-id", row.get("requestID", row.get("requestId")))
        with self.lock:
            if not request_id:
                self.uncorrelated += 1
                return
            decisions = self.records[(pod, request_id)]
            if (not decisions or decisions[-1]["picker_seen"] or
                    (message == "Before running scorer plugins" and decisions[-1]["endpoints"])):
                decisions.append({"epp_pod": pod, "request_id": request_id,
                                  "timestamp": row.get("timestamp", row.get("ts")),
                                  "endpoints": {}, "totals_seen": False, "picker_seen": False})
            decision = decisions[-1]
            if message == "Calculated score":
                identity, _, _ = endpoint(row.get("endpoint"), self.namespace)
                name, kind = plugin_identity(row.get("plugin"))
                if identity and name:
                    candidate = decision["endpoints"].setdefault(identity, {"scores": {}})
                    candidate["scores"][name] = {"type": kind, "raw": number(row.get("score"))}
            elif message == "Candidate pods for picking":
                candidates = row.get("endpoints-weighted-score")
                if isinstance(candidates, list):
                    decision["totals_seen"] = True
                    for item in candidates:
                        if not isinstance(item, dict):
                            continue
                        identity, name, metrics = endpoint(item, self.namespace)
                        if identity:
                            candidate = decision["endpoints"].setdefault(identity, {"scores": {}})
                            candidate.update(pod=name, metrics=metrics, weighted_total=number(item.get("Score")))
            elif message == "Completed running picker plugin successfully":
                result = row.get("result")
                targets = result.get("TargetEndpoints") if isinstance(result, dict) else None
                if isinstance(targets, list):
                    decision["picker_seen"] = True
                    for candidate in decision["endpoints"].values():
                        candidate["selected"] = False
                    for item in targets:
                        identity, name, _ = endpoint(item, self.namespace)
                        if identity:
                            candidate = decision["endpoints"].setdefault(identity, {"scores": {}})
                            candidate.update(selected=True)
                            if name:
                                candidate["pod"] = name

    def matched(self, result, scorers, config_known):
        ids = {result.get(key) for key in ("request_id_gateway", "request_id_response", "request_id_sent")}
        ids.discard(None)
        with self.lock:
            decisions = [json.loads(json.dumps(d)) for (pod, rid), values in self.records.items()
                         if rid in ids for d in values]
        for decision in decisions:
            issues = []
            if not decision.pop("totals_seen"):
                issues.append("missing candidate totals")
            if not decision.pop("picker_seen"):
                issues.append("missing picker result")
            if not config_known:
                issues.append("scorer weights unavailable")
            endpoints = []
            for identity, candidate in sorted(decision["endpoints"].items()):
                candidate["endpoint_id"] = identity
                candidate.setdefault("pod", None)
                candidate.setdefault("selected", None)
                candidate.setdefault("weighted_total", None)
                names = set(scorers) | set(candidate["scores"])
                complete = config_known and bool(names)
                for name in sorted(names):
                    score = candidate["scores"].setdefault(name, {"raw": None})
                    settings = scorers.get(name, {})
                    score["type"] = score.get("type") or settings.get("type")
                    score["weight"] = settings.get("weight")
                    raw, weight = score["raw"], score["weight"]
                    score["weighted"] = min(1.0, max(0.0, raw)) * weight if raw is not None and weight is not None else None
                    complete = complete and score["weighted"] is not None
                candidate["computed_total"] = sum(s["weighted"] for s in candidate["scores"].values()) if complete else None
                if not complete:
                    issues.append(f"incomplete scorer data for {identity}")
                total = candidate["weighted_total"]
                if total is None:
                    issues.append(f"missing weighted total for {identity}")
                elif complete and not math.isclose(total, candidate["computed_total"], rel_tol=1e-6, abs_tol=1e-6):
                    issues.append(f"logged total differs from ConfigMap weights for {identity}")
                endpoints.append(candidate)
            if not endpoints:
                issues.append("no candidate endpoints")
            decision["endpoints"] = endpoints
            decision["issues"] = issues
            decision["status"] = "partial" if issues else "matched"
        status = "missing" if not decisions else "ambiguous" if len(decisions) > 1 else decisions[0]["status"]
        return {"status": status, "decisions": decisions}


class EppScoreCollector:
    def __init__(self, args, profile, since_time, oc_output):
        self.args, self.profile, self.since_time, self.oc_output = args, profile, since_time, oc_output
        self.records = ScoreRecords(args.namespace)
        self.scorers, self.config, self.warnings, self.followers = {}, None, [], []

    def start(self):
        try:
            deployment = json.loads(self.oc_output(["oc", "get", "deployment", self.args.epp_deployment,
                                                   "-n", self.args.namespace, "-o", "json"]))
            containers = deployment["spec"]["template"]["spec"]["containers"]
            container = next(c for c in containers if c["name"] == self.args.epp_container)
            try:
                name, key = config_location(deployment, container, self.args.epp_configmap, self.args.epp_config_key)
                cm = json.loads(self.oc_output(["oc", "get", "configmap", name, "-n", self.args.namespace, "-o", "json"]))
                self.scorers = profile_scorers(cm["data"][key], self.profile)
                self.config = {"configmap": name, "key": key, "resource_version": cm["metadata"].get("resourceVersion"),
                               "profile": self.profile, "scorers": self.scorers}
            except ImportError:
                self.warnings.append("Install PyYAML to read scorer weights: python -m pip install PyYAML")
            except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
                self.warnings.append(f"Cannot read scorer weights: {error}")
            # Use the Deployment's complete selector, including matchExpressions.
            selector = deployment["spec"]["selector"]
            terms = [f"{k}={v}" for k, v in selector.get("matchLabels", {}).items()]
            for expr in selector.get("matchExpressions", []):
                key, op, values = expr["key"], expr["operator"], expr.get("values", [])
                terms.append(f"{key} {'in' if op == 'In' else 'notin'} ({','.join(values)})" if op in ("In", "NotIn")
                             else key if op == "Exists" else f"!{key}")
            if not terms:
                raise ValueError("EPP Deployment has no pod selector")
            pods = json.loads(self.oc_output(["oc", "get", "pods", "-n", self.args.namespace,
                                             "-l", ",".join(terms), "-o", "json"]))
            for pod in pods.get("items", []):
                if pod.get("metadata", {}).get("deletionTimestamp") or pod.get("status", {}).get("phase") != "Running":
                    continue
                name = pod["metadata"]["name"]
                errors = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
                try:
                    proc = subprocess.Popen(["oc", "logs", "-n", self.args.namespace, name, "-c", self.args.epp_container,
                                             f"--since-time={self.since_time}", "--follow"], stdout=subprocess.PIPE,
                                            stderr=errors, text=True, bufsize=1)
                except OSError:
                    errors.close()
                    raise
                thread = threading.Thread(target=self._read, args=(proc, name), daemon=True)
                self.followers.append((proc, thread, errors))
                thread.start()
            if not self.followers:
                self.warnings.append("No running EPP pods found")
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, StopIteration, subprocess.TimeoutExpired) as error:
            self.warnings.append(f"Cannot start EPP score collection: {error}")

    def _read(self, proc, pod):
        try:
            for line in proc.stdout:
                self.records.feed(line, pod)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.warnings.append(f"Cannot parse EPP logs from {pod}: {error}")

    def finish(self, results):
        deadline = time.monotonic() + self.args.epp_wait
        while self.followers:
            matched = [self.records.matched(r, self.scorers, self.config is not None) for r in results]
            if all(r["status"] == "matched" for r in matched) or time.monotonic() >= deadline:
                break
            if all(proc.poll() is not None for proc, _, _ in self.followers):
                break
            time.sleep(0.1)
        self.close()
        counts = Counter()
        for result in results:
            result["epp_scores"] = self.records.matched(result, self.scorers, self.config is not None)
            counts[result["epp_scores"]["status"]] += 1
        if counts["missing"]:
            self.warnings.append("Missing score records: check EPP --v=4, JSON logging, pod restarts, and request IDs")
        return {"profile": self.profile, "config": self.config, "coverage": {
            status: counts[status] for status in ("matched", "partial", "missing", "ambiguous")
        }, "uncorrelated_records": self.records.uncorrelated, "warnings": list(dict.fromkeys(self.warnings))}

    def close(self):
        followers, self.followers = self.followers, []
        for proc, thread, errors in followers:
            stopped = proc.poll() is None
            if stopped:
                proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            thread.join(timeout=3)
            proc.stdout.close()
            errors.seek(0)
            message = errors.read().strip()
            errors.close()
            if not stopped and proc.returncode:
                self.warnings.append(f"EPP log reader failed: {message[:400] or proc.returncode}")


def print_score_summary(summary):
    counts = summary["coverage"]
    print("  EPP scores: " + ", ".join(f"{counts[k]} {k}" for k in ("matched", "partial", "missing", "ambiguous")))
    config = summary["config"]
    if config:
        weights = ", ".join(f"{name}={settings['weight']:g}" for name, settings in config["scorers"].items())
        print(f"    Weights: {weights or 'no scorers'} ({config['configmap']} / {config['key']})")
    if summary["uncorrelated_records"]:
        print(f"    {summary['uncorrelated_records']} score records lacked a request ID")
    for warning in summary["warnings"]:
        print(f"    Warning: {warning}")
    print("    Per-request score tables: --debug; full decisions are saved with --output-json")


def print_request_scores(data):
    print(f"    EPP scores: {data['status']}")
    for index, decision in enumerate(data["decisions"], 1):
        if len(data["decisions"]) > 1:
            print(f"    Decision {index} ({decision['epp_pod']}, {decision['request_id']})")
        rows = decision["endpoints"]
        names = sorted({name for row in rows for name in row["scores"]})
        width = max([8] + [len(row["endpoint_id"].split("/", 1)[-1]) for row in rows])
        labels = [f"{name} raw/weighted" for name in names]
        widths = [max(18, len(label)) for label in labels]
        print("    " + f"{'Endpoint':<{width}}  " + "  ".join(f"{label:>{size}}" for label, size in zip(labels, widths)) + "     Total  Picked")
        def fmt(value):
            return "n/a" if value is None else f"{value:.3f}"
        for row in rows:
            values = []
            for name in names:
                score = row["scores"].get(name, {})
                values.append(f"{fmt(score.get('raw'))}/{fmt(score.get('weighted'))}")
            chosen = "yes" if row["selected"] is True else "no" if row["selected"] is False else "n/a"
            print("    " + f"{row['endpoint_id'].split('/', 1)[-1]:<{width}}  " +
                  "  ".join(f"{value:>{size}}" for value, size in zip(values, widths)) +
                  f"  {fmt(row['weighted_total']):>8}  {chosen}")
        for issue in decision["issues"]:
            print(f"    Warning: {issue}")
