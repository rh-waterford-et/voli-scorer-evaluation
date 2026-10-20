#!/usr/bin/env python3
"""Dev-only stub imitating the stream_metrics.py CLI surface.

Lets the dashboard's run orchestration be tested end to end without
contacting any gateway or cluster. Enable with:

    VOLI_BENCH_CMD=dashboard/dev/stub_benchmark.py uvicorn app:app ...

Recognizes --profile, --run, --output-json and --endpoint; all other real
flags are accepted and ignored. Writes plausible result JSON in the same
shapes the real script produces (single run dict, or a suite document when
there are multiple load settings).

Set STUB_FAIL=1 to simulate a benchmark failure (nonzero exit, no JSON).
"""

import argparse
import json
import os
import random
import signal
import sys
import time
from pathlib import Path


def handle_sigterm(signum, frame):
    sys.exit(130)


signal.signal(signal.SIGTERM, handle_sigterm)

parser = argparse.ArgumentParser()
parser.add_argument("--profile", default="default")
parser.add_argument("--run", action="append", default=[])
parser.add_argument("--output-json", type=Path, required=True)
parser.add_argument("--endpoint", default="/v1/audio/speech")
args, _unknown = parser.parse_known_args()


def run_setting(text):
    total, concurrency = text.lower().split("x")
    return int(total), int(concurrency)


def summary(values):
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p99": None}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "p50": ordered[len(ordered) // 2],
        "p99": ordered[-1],
    }


def fake_values(rng, count, base):
    return [base * (0.6 + rng.random() * 0.9) for _ in range(count)]


settings = [run_setting(text) for text in args.run] or [(10, 1)]
rng = random.Random(f"{args.profile}-{args.endpoint}")
pods = ["stub-tts-a-7d9f4c", "stub-tts-b-2b6e81"]
scorer = f"stub-{args.profile}-scorer"
runs_out = []

for iterations, concurrency in settings:
    print(
        f"  {args.profile} ({scorer}): {iterations} requests, concurrency {concurrency}...",
        flush=True,
    )
    time.sleep(min(2.0, 0.15 * iterations / max(concurrency, 1)))
    e2e_values = fake_values(rng, iterations, 1200)
    ttfa_values = fake_values(rng, iterations, 350)
    routing: dict[str, int] = {}
    results = []
    failures = 0
    for index in range(1, iterations + 1):
        ok = rng.random() > 0.05
        pod = pods[index % len(pods)]
        if ok:
            routing[pod] = routing.get(pod, 0) + 1
        else:
            failures += 1
        results.append(
            {
                "iteration": index,
                "status": "ok" if ok else "failed",
                "error": None if ok else "stub simulated failure",
                "pod": pod if ok else None,
                "e2e_ms": e2e_values[index - 1],
                "ttfa_ms": ttfa_values[index - 1],
                "ttft_ms": None,
                "profile": args.profile,
                "scorer": scorer,
            }
        )
    runs_out.append(
        {
            "run_id": f"stub-{args.profile}-{iterations}x{concurrency}",
            "profile": args.profile,
            "scorer": scorer,
            "iterations": iterations,
            "concurrency": concurrency,
            "duration_seconds": 0.15 * iterations / max(concurrency, 1) + 0.4,
            "valid_responses": iterations - failures,
            "failed_responses": failures,
            "missing_output_responses": 0,
            "routing": routing,
            "metrics": {
                "e2e_ms": summary(e2e_values),
                "ttfa_ms": summary(ttfa_values),
                "ttft_ms": summary([]),
                "ttfo_ms": summary([]),
                "tpot_estimate_ms": summary([]),
                "text_gap_ms": summary([]),
                "audio_gap_ms": summary([v / 8 for v in ttfa_values]),
            },
            "results": results,
        }
    )
    print(f"  stub summary: {iterations - failures}/{iterations} valid responses", flush=True)

if os.environ.get("STUB_FAIL"):
    print("stub: simulating benchmark failure", file=sys.stderr, flush=True)
    sys.exit(3)

payload = (
    runs_out[0]
    if len(runs_out) == 1
    else {
        "model": "stub-model",
        "endpoint": "stub-endpoint",
        "modalities": ["audio"],
        "runs": runs_out,
    }
)
args.output_json.parent.mkdir(parents=True, exist_ok=True)
args.output_json.write_text(json.dumps(payload, indent=2) + "\n")
print(f"\nSaved detailed JSON: {args.output_json}", flush=True)
