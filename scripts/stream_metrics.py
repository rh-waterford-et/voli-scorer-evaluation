#!/usr/bin/env python3
"""Measure client-observed Qwen3-Omni streaming latency through an llm-d Gateway.

SSE messages may contain several tokens, so text and audio chunk gaps are
proxies, not token-level ITL. Text TPOT is an estimate from the first and last
text messages and a token count. Gateway access logs can identify the pod that
actually served each request without changing the cluster.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from epp_scores import EppScoreCollector, print_request_scores, print_score_summary


# Profiles in the current vllm-omni-validation EPP tts.yaml. Keep this map in
# step with that ConfigMap if the deployment's profile names change.
PROFILE_SCORERS = {
    "activeRequestProfile": "active-request-scorer",
    "loadAwareProfile": "load-aware-scorer",
    "runningRequestSizeProfile": "running-requests-size-scorer",
    "queueProfile": "queue-scorer",
    "tokenLoadProfile": "token-load-scorer",
    "kvCacheUtilizationProfile": "kv-cache-utilization-scorer",
    "endpointAttributeProfile": "endpoint-attribute-scorer",
    "endpointAttributeWeightProfile": "endpoint-attribute-weight-scorer",
    "contextLengthProfile": "context-length-aware",
    "prefixCacheProfile": "prefix-cache-scorer",
    "noHitLruProfile": "no-hit-lru-scorer",
    "latencyProfile": "latency-scorer",
    "sessionAffinityProfile": "session-affinity-scorer",
    "mmEmbeddingsCacheProfile": "mm-embeddings-cache-scorer",
    "loraAffinityProfile": "lora-affinity-scorer",
    "headerLabelAffinityProfile": "header-label-affinity-scorer",
    "topologyAffinityProfile": "topology-affinity-scorer",
}


ENDPOINTS = ("/v1/chat/completions", "/v1/audio/speech")


def endpoint_url(url, endpoint="/v1/chat/completions"):
    """Join a gateway base URL (or an existing API URL) to the chosen endpoint."""
    url = url.rstrip("/")
    for known_endpoint in ENDPOINTS:
        if url.endswith(known_endpoint):
            if known_endpoint == endpoint:
                return url
            url = url[:-len(known_endpoint)]
            break
    if url.endswith("/v1"):
        return url + endpoint[len("/v1"):]
    return url + endpoint


def iter_sse_events(response):
    """Yield complete SSE data messages and their client arrival times."""
    data_lines = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if data_lines:
                yield "\n".join(data_lines), time.perf_counter()
                data_lines = []
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines), time.perf_counter()


def extract_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(extract_text(part) for part in value)
    if isinstance(value, dict) and value.get("type") == "text":
        return extract_text(value.get("text"))
    return ""


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def print_section(title):
    print(f"\n{title}")
    print("-" * len(title))


def print_latency_table(rows):
    print(f"  {'Metric':<34} {'N':>5} {'Mean':>10} {'P50':>10} {'P99':>10}  Unit")
    print("  " + "-" * 79)
    for name, values, unit in rows:
        if values:
            mean = f"{sum(values) / len(values):.2f}"
            p50 = f"{percentile(values, 0.50):.2f}"
            p99 = f"{percentile(values, 0.99):.2f}"
        else:
            mean = p50 = p99 = "n/a"
        print(f"  {name:<34} {len(values):>5} {mean:>10} {p50:>10} {p99:>10}  {unit}")


def payload_for(args, prompt, modalities):
    if args.endpoint == "/v1/audio/speech":
        return {
            "model": args.model,
            "input": prompt,
            "voice": args.voice or "vivian",
            "stream": True,
            "stream_format": "sse",
            "response_format": args.audio_format or "pcm",
        }

    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": modalities,
        "stream": True,
    }
    if not args.no_usage:
        payload["stream_options"] = {"include_usage": True}
    if "audio" in modalities and (args.voice or args.audio_format):
        payload["audio"] = {}
        if args.voice:
            payload["audio"]["voice"] = args.voice
        if args.audio_format:
            payload["audio"]["format"] = args.audio_format
    return payload


def run_request(index, args, prompt, modalities, run_id):
    sent_id = str(uuid.uuid4())
    marker = f"voli-stream-metrics/{run_id}/{index}"
    result = {
        "iteration": index,
        "request_id_sent": sent_id,
        "request_id_response": None,
        "request_id_gateway": None,
        "user_agent": marker,
        "pod": None,
        "upstream": None,
        "backend_source": None,
        "status": "failed",
        "error": None,
        "http_status": None,
        "usage": None,
        "text": "",
        "visible_text": "",
        "text_times": [],
        "visible_times": [],
        "audio_times": [],
        "e2e_ms": None,
        "response_pod_header": None,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": marker,
        "X-Request-Id": sent_id,
    }
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"
    if args.profile:
        headers["EPP-Profile"] = args.profile
    request = urllib.request.Request(
        endpoint_url(args.url, args.endpoint),
        data=json.dumps(payload_for(args, prompt, modalities)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    start = time.perf_counter()
    result["request_start"] = start
    saw_done = False
    saw_finish = False
    text_parts = []
    visible_parts = []
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            result["http_status"] = response.status
            result["request_id_response"] = response.headers.get("X-Request-Id")
            result["response_pod_header"] = response.headers.get("X-Inference-Pod")
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" not in content_type.lower():
                snippet = response.read(1000).decode("utf-8", errors="replace")
                raise RuntimeError(f"expected SSE, got {content_type!r}: {snippet}")
            for data, event_time in iter_sse_events(response):
                if data == "[DONE]":
                    saw_done = True
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError as error:
                    raise RuntimeError(f"invalid SSE JSON: {data[:160]!r}") from error
                if not isinstance(event, dict):
                    raise RuntimeError(f"unexpected SSE event: {data[:160]!r}")
                if event.get("error"):
                    raise RuntimeError(f"server error: {str(event['error'])[:500]}")
                if isinstance(event.get("usage"), dict):
                    result["usage"] = event["usage"]
                if args.endpoint == "/v1/audio/speech":
                    event_type = event.get("type")
                    if event_type == "speech.audio.delta" and event.get("audio"):
                        result["audio_times"].append(event_time)
                    elif event_type == "speech.audio.done":
                        saw_done = True
                    continue
                modality = event.get("modality")
                text_piece = ""
                visible_piece = ""
                has_audio = False
                for choice in event.get("choices") or []:
                    if choice.get("finish_reason") is not None:
                        saw_finish = True
                    delta = choice.get("delta") or {}
                    if modality == "audio":
                        has_audio = bool(delta.get("audio") or delta.get("content")) or has_audio
                        continue
                    if modality not in (None, "text"):
                        continue
                    reasoning = extract_text(
                        delta.get("reasoning_content") or delta.get("reasoning")
                    )
                    content = extract_text(delta.get("content"))
                    text_piece += reasoning + content
                    visible_piece += content
                    if modality is None and delta.get("audio"):
                        has_audio = True
                if text_piece:
                    result["text_times"].append(event_time)
                    text_parts.append(text_piece)
                if visible_piece:
                    result["visible_times"].append(event_time)
                    visible_parts.append(visible_piece)
                if has_audio:
                    result["audio_times"].append(event_time)
        if not saw_done and ("audio" in modalities or not saw_finish):
            raise RuntimeError("stream closed without a complete stream marker ([DONE])")
        if not (result["text_times"] or result["audio_times"]):
            raise RuntimeError("stream completed without text or audio data")
        result["status"] = "ok"
    except urllib.error.HTTPError as error:
        body = error.read(1000).decode("utf-8", errors="replace")
        result["http_status"] = error.code
        result["error"] = f"HTTP {error.code}: {body}"
    except urllib.error.URLError as error:
        result["error"] = f"connection error: {error.reason}"
    except Exception as error:
        result["error"] = str(error)
    finally:
        result["e2e_ms"] = (time.perf_counter() - start) * 1000
        result["text"] = "".join(text_parts)
        result["visible_text"] = "".join(visible_parts)
    return result


def add_metrics(result, tokenizer, modalities):
    request_start = result.pop("request_start")
    text_times = result.pop("text_times")
    visible_times = result.pop("visible_times")
    audio_times = result.pop("audio_times")
    result["ttft_ms"] = (text_times[0] - request_start) * 1000 if text_times else None
    result["ttfo_ms"] = (visible_times[0] - request_start) * 1000 if visible_times else None
    result["ttfa_ms"] = (audio_times[0] - request_start) * 1000 if audio_times else None
    result["text_chunks"] = len(text_times)
    result["audio_chunks"] = len(audio_times)
    result["text_gap_ms"] = [
        (b - a) * 1000 for a, b in zip(text_times, text_times[1:])
    ]
    result["audio_gap_ms"] = [
        (b - a) * 1000 for a, b in zip(audio_times, audio_times[1:])
    ]
    result["client_text_tokens"] = (
        len(tokenizer.encode(result["text"], add_special_tokens=False))
        if result["text"] and tokenizer else 0
    )
    usage = result["usage"] or {}
    server_tokens = usage.get("completion_tokens")
    if server_tokens is None:
        server_tokens = usage.get("output_tokens")
    result["server_completion_tokens"] = (
        server_tokens if isinstance(server_tokens, int) and server_tokens >= 0 else None
    )
    count = result["client_text_tokens"]
    basis = "client text tokens"
    if modalities == ["text"] and result["server_completion_tokens"] is not None:
        count = result["server_completion_tokens"]
        basis = "server completion tokens"
    result["tpot_basis"] = basis
    result["tpot_estimate_ms"] = (
        (text_times[-1] - text_times[0]) * 1000 / (count - 1)
        if len(text_times) >= 2 and count >= 2 else None
    )
    result["missing_modalities"] = [
        modality for modality, times in (("text", visible_times), ("audio", audio_times))
        if modality in modalities and not times
    ] if result["status"] == "ok" else []


def oc_output(command):
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=25, check=False
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"oc exited {completed.returncode}")
    return completed.stdout


def discover_pods(namespace, gateway_name):
    data = json.loads(oc_output(["oc", "get", "pods", "-n", namespace, "-o", "json"]))
    ip_to_pod = {}
    gateway_pods = []
    for item in data.get("items", []):
        metadata = item.get("metadata") or {}
        status = item.get("status") or {}
        name = metadata.get("name")
        ip = status.get("podIP")
        if name and ip:
            ip_to_pod[ip] = name
        labels = metadata.get("labels") or {}
        if labels.get("gateway.networking.k8s.io/gateway-name") == gateway_name:
            gateway_pods.append(name)
    return ip_to_pod, gateway_pods


def gateway_records(log_text, run_id, request_path):
    """Read Istio's default access log: user agent, request ID, host, upstream."""
    records = {}
    prefix = f"voli-stream-metrics/{run_id}/"
    for line in log_text.splitlines():
        if prefix not in line or f"POST {request_path}" not in line:
            continue
        try:
            fields = shlex.split(line)
        except ValueError:
            continue
        for position, value in enumerate(fields):
            if not value.startswith(prefix) or len(fields) <= position + 3:
                continue
            try:
                index = int(value[len(prefix):])
            except ValueError:
                continue
            record = (fields[position + 1], fields[position + 3])
            records.setdefault(index, set()).add(record)
    return records


def ip_from_upstream(upstream):
    if not upstream or upstream == "-" or "," in upstream:
        return None
    if upstream.startswith("[") and "]:" in upstream:
        host = upstream[1:upstream.index("]:")]
    else:
        host = upstream.rsplit(":", 1)[0]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def resolve_backends(args, results, run_id, since_time, ip_to_pod, gateway_pods):
    if args.gateway_pod:
        gateway_pods = args.gateway_pod
    if not gateway_pods:
        print("Backend lookup: no Gateway pod found; pod names remain unknown.", file=sys.stderr)
        return
    records = {}
    deadline = time.monotonic() + args.gateway_wait
    while True:
        for gateway_pod in gateway_pods:
            try:
                output = oc_output([
                    "oc", "logs", "-n", args.namespace, gateway_pod,
                    "-c", args.gateway_container, f"--since-time={since_time}",
                ])
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                print(f"Backend lookup: {error}", file=sys.stderr)
                return
            for index, entries in gateway_records(output, run_id, args.endpoint).items():
                records.setdefault(index, set()).update(entries)
        if all(result["iteration"] in records for result in results):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    for result in results:
        matches = records.get(result["iteration"], set())
        if len(matches) != 1:
            if len(matches) > 1:
                result["backend_source"] = "ambiguous Gateway logs"
            continue
        gateway_id, upstream = next(iter(matches))
        result["request_id_gateway"] = gateway_id
        result["upstream"] = upstream
        pod_ip = ip_from_upstream(upstream)
        if pod_ip:
            result["pod"] = ip_to_pod.get(pod_ip)
            result["backend_source"] = "Gateway access log"


def format_ms(value):
    return "n/a" if value is None else f"{value:.1f}"


def print_debug_results(results, total):
    print_section("Per-request details (ms)")
    for result in results:
        pod = result["pod"] or (
            f"unknown ({result['upstream']})" if result["upstream"] else "unknown"
        )
        state = result["status"]
        if result["missing_modalities"]:
            state = "missing " + ",".join(result["missing_modalities"])
        print(f"  Request {result['iteration']}/{total}  |  {state}  |  {pod}")
        print(
            f"    TTFT {format_ms(result['ttft_ms']):>8}   "
            f"TTFO {format_ms(result['ttfo_ms']):>8}   "
            f"TTFA {format_ms(result['ttfa_ms']):>8}   "
            f"TPOT~ {format_ms(result['tpot_estimate_ms']):>8}   "
            f"E2E {format_ms(result['e2e_ms']):>8}"
        )
        print(
            f"    Chunks: text {result['text_chunks']}, audio {result['audio_chunks']}  |  "
            f"Tokens: server {result['server_completion_tokens']}, "
            f"client text {result['client_text_tokens']}"
        )
        if result["request_id_gateway"]:
            id_label, request_id = "Gateway ID", result["request_id_gateway"]
        elif result["request_id_response"]:
            id_label, request_id = "Response ID", result["request_id_response"]
        else:
            id_label, request_id = "Sent ID", result["request_id_sent"]
        print(f"    Route: {result['backend_source'] or 'unavailable'}  |  {id_label}: {request_id}")
        if result["tpot_estimate_ms"] is not None:
            print(f"    TPOT denominator: {result['tpot_basis']}")
        if result["error"]:
            print(f"    Error: {result['error']}")
        if "epp_scores" in result:
            print_request_scores(result["epp_scores"])
        print()


def run_setting(text, parser):
    parts = text.lower().split("x")
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        parser.error(f"invalid --run {text!r}; expected ITERATIONSxCONCURRENCY, e.g. 50x10")
    iterations, concurrency = map(int, parts)
    if iterations < 1 or concurrency < 1:
        parser.error("run iterations and concurrency must be positive")
    return iterations, concurrency


def suite_plan(args, parser):
    if args.suite_file:
        if args.suite or args.profiles or args.profile or args.run:
            parser.error("--suite-file cannot be combined with --suite, --profiles, --profile, or --run")
        try:
            document = json.loads(args.suite_file.read_text())
        except (OSError, json.JSONDecodeError) as error:
            parser.error(f"cannot read --suite-file: {error}")
        profiles = document.get("profiles") if isinstance(document, dict) else None
        if not isinstance(profiles, dict) or not profiles:
            parser.error("--suite-file needs a nonempty 'profiles' object")
        plan = []
        for profile, settings in profiles.items():
            if profile not in PROFILE_SCORERS:
                parser.error(f"unknown suite profile {profile!r}; use --list-profiles")
            if not isinstance(settings, list) or not settings:
                parser.error(f"{profile}: expected a nonempty list of run settings")
            runs = []
            for setting in settings:
                if not isinstance(setting, dict):
                    parser.error(f"{profile}: each run must be an object")
                iterations = setting.get("iterations")
                concurrency = setting.get("concurrency")
                if (type(iterations) is not int or type(concurrency) is not int
                        or iterations < 1 or concurrency < 1):
                    parser.error(f"{profile}: iterations and concurrency must be positive integers")
                runs.append((iterations, concurrency))
            plan.append((profile, PROFILE_SCORERS[profile], runs))
        return plan, True

    if args.profile and (args.suite or args.profiles):
        parser.error("--profile selects one profile; use --profiles for a suite subset")
    if args.suite and args.profiles:
        parser.error("use --suite or --profiles, not both")
    runs = [run_setting(value, parser) for value in args.run]
    if not runs:
        runs = [(args.iterations, args.concurrency)]
    if args.suite:
        selected = list(PROFILE_SCORERS)
    elif args.profiles:
        selected = [name.strip() for name in args.profiles.split(",")]
        if any(name not in PROFILE_SCORERS for name in selected):
            parser.error("--profiles contains an unknown name; use --list-profiles")
        if len(selected) != len(set(selected)):
            parser.error("--profiles contains duplicate names")
    else:
        profile = args.profile or "default"
        scorer = "active-request-scorer" if profile == "default" else PROFILE_SCORERS.get(profile, "unknown")
        return [(profile, scorer, runs)], len(runs) > 1
    return [(profile, PROFILE_SCORERS[profile], runs) for profile in selected], True


def metric_samples(valid):
    return {
        "ttft_ms": [r["ttft_ms"] for r in valid if r["ttft_ms"] is not None],
        "ttfo_ms": [r["ttfo_ms"] for r in valid if r["ttfo_ms"] is not None],
        "ttfa_ms": [r["ttfa_ms"] for r in valid if r["ttfa_ms"] is not None],
        "tpot_estimate_ms": [r["tpot_estimate_ms"] for r in valid if r["tpot_estimate_ms"] is not None],
        "text_gap_ms": [value for r in valid for value in r["text_gap_ms"]],
        "audio_gap_ms": [value for r in valid for value in r["audio_gap_ms"]],
        "e2e_ms": [r["e2e_ms"] for r in valid],
    }


def metric_summary(values):
    return {
        "n": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.50),
        "p99": percentile(values, 0.99),
    }


def collect_run(args, tokenizer, modalities, prompts, profile, scorer, iterations, concurrency):
    run_args = argparse.Namespace(**vars(args))
    run_args.profile = None if profile == "default" else profile
    run_args.iterations = iterations
    run_args.concurrency = concurrency
    run_id = uuid.uuid4().hex
    ip_to_pod = {}
    gateway_pods = []
    if not args.no_backend_lookup:
        try:
            ip_to_pod, gateway_pods = discover_pods(args.namespace, args.gateway_name)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
            print(f"Backend lookup unavailable: {error}", file=sys.stderr)
    since_time = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    collector = EppScoreCollector(args, profile, since_time, oc_output) if args.epp_scores else None
    if collector:
        collector.start()
        if collector.config:
            scorer = " + ".join(f"{s['type']} (weight {s['weight']:g})" for s in collector.scorers.values()) or "no scorers"
    print(f"  {profile} ({scorer}): {iterations} requests, concurrency {concurrency}...", flush=True)
    benchmark_start = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(run_request, i, run_args, prompts[(i - 1) % len(prompts)], modalities, run_id)
                for i in range(1, iterations + 1)
            ]
            results = [None] * iterations
            for future in as_completed(futures):
                result = future.result()
                results[result["iteration"] - 1] = result
    except BaseException:
        if collector:
            collector.close()
        raise
    benchmark_seconds = time.perf_counter() - benchmark_start
    try:
        for result in results:
            add_metrics(result, tokenizer, modalities)
        if not args.no_backend_lookup and (gateway_pods or args.gateway_pod):
            try:
                latest_ip_to_pod, _ = discover_pods(args.namespace, args.gateway_name)
                ip_to_pod.update(latest_ip_to_pod)
            except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
                pass
            resolve_backends(run_args, results, run_id, since_time, ip_to_pod, gateway_pods)
        score_summary = collector.finish(results) if collector else None
    finally:
        if collector:
            collector.close()
    for result in results:
        if result["pod"] is None and result["response_pod_header"]:
            result["pod"] = result["response_pod_header"]
            result["backend_source"] = "X-Inference-Pod response header"
        result["profile"] = profile
        result["scorer"] = scorer

    valid = [r for r in results if r["status"] == "ok" and not r["missing_modalities"]]
    failures = [r for r in results if r["status"] == "failed"]
    missing = [r for r in results if r["missing_modalities"]]
    counts = Counter(r["pod"] or "unknown" for r in results)
    samples = metric_samples(valid)
    run = {
        "run_id": run_id,
        "profile": profile,
        "scorer": scorer,
        "iterations": iterations,
        "concurrency": concurrency,
        "duration_seconds": benchmark_seconds,
        "valid_responses": len(valid),
        "failed_responses": len(failures),
        "missing_output_responses": len(missing),
        "routing": dict(counts),
        "metrics": {name: metric_summary(values) for name, values in samples.items()},
        "results": results,
        "_samples": samples,
        "_valid": valid,
        "_failures": failures,
        "_missing": missing,
    }
    if score_summary is not None:
        run["epp_scores"] = score_summary
    return run


def print_run_report(run, args, modalities):
    results = run["results"]
    valid = run["_valid"]
    failures = run["_failures"]
    missing = run["_missing"]
    counts = run["routing"]
    samples = run["_samples"]
    iterations = run["iterations"]
    print("\nStreaming results")
    print("=================")
    print(f"  Model:        {args.model}")
    print(f"  Endpoint:     {endpoint_url(args.url, args.endpoint)}")
    print(f"  EPP profile:  {run['profile']}")
    print(f"  Scorer:       {run['scorer']}")
    print(f"  Output:       {', '.join(modalities)}")
    print(f"  Requests:     {iterations} total, up to {run['concurrency']} concurrent")
    print(f"  Responses:    {len(valid)} valid, {len(failures)} failed, {len(missing)} missing requested output")
    print(f"  Duration:     {run['duration_seconds']:.2f} s  ({iterations / run['duration_seconds']:.2f} requests/s)")

    print_section("Latency (valid responses)")
    if args.endpoint == "/v1/audio/speech":
        print_latency_table([
            ("TTFA (first audio event)", samples["ttfa_ms"], "ms"),
            ("Audio chunk gap", samples["audio_gap_ms"], "ms"),
            ("End-to-end", samples["e2e_ms"], "ms"),
        ])
    else:
        print_latency_table([
            ("TTFT (first text/reasoning)", samples["ttft_ms"], "ms"),
            ("TTFO (first visible text)", samples["ttfo_ms"], "ms"),
            ("TTFA (first audio data)", samples["ttfa_ms"], "ms"),
            ("Text TPOT estimate", samples["tpot_estimate_ms"], "ms/token"),
            ("Text chunk gap (ITL proxy)", samples["text_gap_ms"], "ms"),
            ("Audio chunk gap", samples["audio_gap_ms"], "ms"),
            ("End-to-end", samples["e2e_ms"], "ms"),
        ])

    print_section("Routing (all requests)")
    print(f"  {'Pod':<59} {'Count':>6} {'Share':>7}")
    print("  " + "-" * 74)
    for pod, count in sorted(counts.items()):
        print(f"  {pod:<59} {count:>6} {count / iterations:>6.1%}")

    if "epp_scores" in run:
        print_section("EPP scoring")
        print_score_summary(run["epp_scores"])

    if len(counts) > 1:
        print_section("Latency by pod (valid responses)")
        for pod in sorted(counts):
            pod_results = [r for r in valid if (r["pod"] or "unknown") == pod]
            if not pod_results:
                continue
            print(f"  {pod}")
            if args.endpoint == "/v1/audio/speech":
                print_latency_table([
                    ("TTFA", [r["ttfa_ms"] for r in pod_results if r["ttfa_ms"] is not None], "ms"),
                    ("End-to-end", [r["e2e_ms"] for r in pod_results], "ms"),
                ])
            else:
                print_latency_table([
                    ("TTFT", [r["ttft_ms"] for r in pod_results if r["ttft_ms"] is not None], "ms"),
                    ("End-to-end", [r["e2e_ms"] for r in pod_results], "ms"),
                ])
            print()

    print_issues(run)
    print_section("Notes")
    if args.endpoint == "/v1/audio/speech":
        print("  TTFA and audio chunk gaps are client-observed from streamed SSE events.")
        print("  Audio chunk gaps are a streaming proxy, not token-level ITL.")
    else:
        print("  TTFT, TTFO and TTFA are client-observed. Text chunk gaps approximate ITL.")
        print("  Text TPOT is an estimate because streamed chunks may contain multiple tokens.")
    if len(valid) < 100:
        print("  P99 with fewer than 100 valid requests is a rough tail indicator.")
    if args.debug:
        print_debug_results(results, iterations)


def print_issues(run):
    failures = run["_failures"]
    missing = run["_missing"]
    if not failures and not missing:
        return
    print_section("Issues")
    reasons = Counter((r["error"] or "unknown error").replace("\n", " ")[:120] for r in failures)
    for reason, count in reasons.most_common(5):
        print(f"  {count} failed: {reason}")
    if len(reasons) > 5:
        print(f"  {len(reasons) - 5} more failure types; use --debug or --output-json for details")
    missing_counts = Counter(", ".join(r["missing_modalities"]) for r in missing)
    for modalities_missing, count in missing_counts.most_common():
        print(f"  {count} missing: {modalities_missing}")


def suite_value(run, metric, statistic):
    value = run["metrics"][metric][statistic]
    return "n/a" if value is None else f"{value:.1f}"


def print_suite_report(runs, args, modalities):
    print("\nProfile suite results")
    print("=====================")
    print(f"  Model:     {args.model}")
    print(f"  Endpoint:  {endpoint_url(args.url, args.endpoint)}")
    print(f"  Output:    {', '.join(modalities)}")
    print(f"  Runs:      {len(runs)} across {len(set(r['profile'] for r in runs))} profiles")
    for number, run in enumerate(runs, 1):
        print(f"\n  {number}. {run['profile']}  [{run['scorer']}]")
        print(
            f"     Load {run['iterations']} requests x {run['concurrency']} concurrent  |  "
            f"valid {run['valid_responses']}/{run['iterations']}  |  "
            f"failed {run['failed_responses']}  |  {run['duration_seconds']:.1f} s"
        )
        if args.endpoint == "/v1/audio/speech":
            print(
                f"     TTFA p50/p99 {suite_value(run, 'ttfa_ms', 'p50')}/{suite_value(run, 'ttfa_ms', 'p99')} ms  |  "
                f"audio gap p50/p99 {suite_value(run, 'audio_gap_ms', 'p50')}/{suite_value(run, 'audio_gap_ms', 'p99')} ms"
            )
            print(
                f"     E2E p50/p99 {suite_value(run, 'e2e_ms', 'p50')}/{suite_value(run, 'e2e_ms', 'p99')} ms"
            )
        else:
            print(
                f"     TTFT p50/p99 {suite_value(run, 'ttft_ms', 'p50')}/{suite_value(run, 'ttft_ms', 'p99')} ms  |  "
                f"TTFA p50/p99 {suite_value(run, 'ttfa_ms', 'p50')}/{suite_value(run, 'ttfa_ms', 'p99')} ms"
            )
            print(
                f"     TPOT~ mean {suite_value(run, 'tpot_estimate_ms', 'mean')} ms/token  |  "
                f"text gap p50/p99 {suite_value(run, 'text_gap_ms', 'p50')}/{suite_value(run, 'text_gap_ms', 'p99')} ms  |  "
                f"E2E p50/p99 {suite_value(run, 'e2e_ms', 'p50')}/{suite_value(run, 'e2e_ms', 'p99')} ms"
            )
        route = ", ".join(f"{pod}: {count}" for pod, count in sorted(run["routing"].items()))
        print(f"     Pods: {route}")
        if "epp_scores" in run:
            print_score_summary(run["epp_scores"])
        if run["_failures"] or run["_missing"]:
            print(f"     Issues: use --debug or --output-json for request details")
    print_section("Notes")
    print("  Profiles run sequentially; requests within each run use the stated concurrency.")
    if args.endpoint == "/v1/audio/speech":
        print("  TTFA and audio chunk gaps are client-observed from streamed SSE events.")
        print("  Audio chunk gaps are a streaming proxy, not token-level ITL.")
    else:
        print("  TTFT and TTFA are client-observed; text gaps approximate ITL; TPOT is an estimate.")
    print("  P99 from fewer than 100 valid requests is a rough tail indicator.")
    if args.debug:
        for run in runs:
            print(f"\n{run['profile']} ({run['iterations']}x{run['concurrency']})")
            print_debug_results(run["results"], run["iterations"])


def serializable_run(run):
    return {key: value for key, value in run.items() if not key.startswith("_")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://10.6.62.51:31670")
    parser.add_argument(
        "--endpoint",
        choices=ENDPOINTS,
        default="/v1/chat/completions",
        help="OpenAI-compatible API endpoint (default: /v1/chat/completions).",
    )
    parser.add_argument("--model", default="qwen3-omni")
    parser.add_argument("--prompt", default="Say hello and introduce yourself in one sentence.")
    parser.add_argument("--prompts-file", type=Path, help="One prompt per nonempty line; cycles through them.")
    parser.add_argument("--modalities", default="text,audio", help="Chat-completions output: text, audio, or text,audio.")
    parser.add_argument("--voice", help="Optional audio voice passed to the API.")
    parser.add_argument("--audio-format", help="Optional audio format passed to the API.")
    parser.add_argument("--no-usage", action="store_true", help="Omit stream_options.include_usage.")
    parser.add_argument("--iterations", "-n", type=int, default=10, help="Total requests for a single run or default suite run.")
    parser.add_argument("--concurrency", "-c", type=int, default=1, help="Maximum simultaneous requests per run.")
    parser.add_argument("--run", action="append", default=[], metavar="NxC", help="Run setting, e.g. 10x1; repeat to benchmark each selected profile at several loads.")
    parser.add_argument("--suite", action="store_true", help="Run every profile in the built-in profile/scorer map.")
    parser.add_argument("--profiles", help="Comma-separated subset of built-in profiles to run.")
    parser.add_argument("--suite-file", type=Path, help="JSON plan assigning runs to individual profiles.")
    parser.add_argument("--list-profiles", action="store_true", help="Show built-in profile/scorer map and exit.")
    parser.add_argument("--timeout", type=float, default=600, help="Socket timeout in seconds.")
    parser.add_argument("--api-key")
    parser.add_argument("--profile", help="EPP scheduling profile for a single-profile run.")
    parser.add_argument("--tokenizer", help="Tokenizer name or local model directory.")
    parser.add_argument("--namespace", default="vllm-omni-validation")
    parser.add_argument("--gateway-name", default="inference-gateway")
    parser.add_argument("--gateway-pod", action="append", help="Gateway pod name; repeat for multiple pods.")
    parser.add_argument("--gateway-container", default="istio-proxy")
    parser.add_argument("--gateway-wait", type=float, default=10, help="Seconds to wait for access logs.")
    parser.add_argument("--epp-scores", action="store_true", help="Collect EPP raw scores and weighted totals; EPP needs JSON logging and --v=4. Requires PyYAML for weights. Use --debug for per-request tables.")
    parser.add_argument("--epp-deployment", default="endpoint-picker-epp", help="Deployment whose EPP logs and configuration are read.")
    parser.add_argument("--epp-container", default="epp", help="EPP container name.")
    parser.add_argument("--epp-configmap", help="Override the plugin ConfigMap name (otherwise discovered from the EPP Deployment).")
    parser.add_argument("--epp-config-key", help="Override the plugin ConfigMap data key (otherwise discovered from --config-file).")
    parser.add_argument("--epp-wait", type=float, default=5, help="Seconds to wait for missing EPP score records after requests and Gateway lookup finish.")
    parser.add_argument("--no-backend-lookup", action="store_true", help="Skip pod/Gateway backend lookup. --epp-scores still reads EPP resources and logs.")
    parser.add_argument("--output-json", type=Path, help="Save per-request results and run summaries as JSON.")
    parser.add_argument("--debug", action="store_true", help="Show details for every request.")
    args = parser.parse_args()
    if args.list_profiles:
        print("Available EPP profiles (built-in map):")
        for profile, scorer in PROFILE_SCORERS.items():
            print(f"  {profile:<31} {scorer}")
        return
    if args.endpoint == "/v1/chat/completions" and not args.tokenizer:
        parser.error("--tokenizer is required for chat-completions runs")
    if args.iterations < 1 or args.concurrency < 1 or args.timeout <= 0 or args.gateway_wait < 0:
        parser.error("iterations and concurrency must be positive; timeout must be positive; gateway-wait cannot be negative")
    if not math.isfinite(args.epp_wait) or args.epp_wait < 0:
        parser.error("--epp-wait must be finite and nonnegative")
    if args.profile is not None and (not args.profile.strip() or "\r" in args.profile or "\n" in args.profile):
        parser.error("--profile must be a nonempty profile name without line breaks")
    plan, suite_mode = suite_plan(args, parser)
    if args.endpoint == "/v1/audio/speech":
        modalities = ["audio"]
    else:
        modalities = [part.strip() for part in args.modalities.split(",")]
        if not modalities or len(set(modalities)) != len(modalities) or any(
            part not in {"text", "audio"} for part in modalities
        ):
            parser.error("--modalities must be text, audio, or text,audio")
    prompts = [args.prompt]
    if args.prompts_file:
        try:
            prompts = [line.strip() for line in args.prompts_file.read_text().splitlines() if line.strip()]
        except OSError as error:
            parser.error(f"cannot read --prompts-file: {error}")
        if not prompts:
            parser.error("--prompts-file has no nonempty lines")

    tokenizer = None
    if args.endpoint == "/v1/chat/completions":
        try:
            from transformers import AutoTokenizer
        except ImportError as error:
            raise SystemExit("Install transformers in the venv first.") from error
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)

    runs = []
    for profile, scorer, settings in plan:
        for iterations, concurrency in settings:
            runs.append(collect_run(args, tokenizer, modalities, prompts,
                                    profile, scorer, iterations, concurrency))
    if suite_mode:
        print_suite_report(runs, args, modalities)
    else:
        print_run_report(runs[0], args, modalities)
    if args.output_json:
        if suite_mode:
            payload = {
                "model": args.model,
                "endpoint": endpoint_url(args.url, args.endpoint),
                "modalities": modalities,
                "runs": [serializable_run(run) for run in runs],
            }
        else:
            payload = serializable_run(runs[0])
        args.output_json.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nSaved detailed JSON: {args.output_json}")


if __name__ == "__main__":
    main()
