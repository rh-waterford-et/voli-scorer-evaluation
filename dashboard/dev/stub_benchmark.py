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
import hashlib
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
parser.add_argument("--size", default=None)
parser.add_argument("--image", default=None)
parser.add_argument("--audio", default=None)
parser.add_argument("--language", default=None)
parser.add_argument("--transcription-stream", action="store_true")
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
image = args.endpoint in ("/v1/images/generations", "/v1/images/edits")
edit = args.endpoint == "/v1/images/edits"
transcription = args.endpoint == "/v1/audio/transcriptions"
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
        embedding = args.endpoint == "/v1/embeddings"
        image = args.endpoint in ("/v1/images/generations", "/v1/images/edits")
        plain = embedding or image or transcription
        results.append(
            {
                "iteration": index,
                "status": "ok" if ok else "failed",
                "error": None if ok else "stub simulated failure",
                "pod": pod if ok else None,
                "e2e_ms": e2e_values[index - 1],
                "ttfa_ms": None if plain else ttfa_values[index - 1],
                "ttft_ms": ttfa_values[index - 1] if transcription and args.transcription_stream and ok else None,
                "text_gap_ms": [80.0, 110.0] if transcription and args.transcription_stream and ok else [],
                **({"embedding_dimensions": 1024} if embedding and ok else {}),
                **({
                    "image_content": "b64-validated" if ok else None,
                    "image_format": "png" if ok else None,
                    "image_bytes": 8132 if ok else None,
                    "image_dimensions": [512, 512] if ok else None,
                } if image else {}),
                **({
                    "transcript_chars": 42 if ok else None,
                    "transcript_empty": False if ok else None,
                    "transcript_format": ("sse" if args.transcription_stream else "json") if ok else None,
                    "text": "stub transcript text" if ok else "",
                } if transcription else {}),
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
            **({"validated_responses": iterations - failures, "unverified_responses": 0} if image else {}),
            **({"empty_transcripts": 0} if transcription else {}),
            "routing": routing,
            "metrics": {
                "e2e_ms": summary(e2e_values),
                "ttfa_ms": summary([] if plain else ttfa_values),
                "ttft_ms": summary([r["ttft_ms"] for r in results if r["ttft_ms"] is not None]),
                "ttfo_ms": summary([]),
                "tpot_estimate_ms": summary([]),
                "text_gap_ms": summary([gap for r in results for gap in r["text_gap_ms"]]),
                "audio_gap_ms": summary([] if plain else [v / 8 for v in ttfa_values]),
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
        "endpoint": args.endpoint,
        "modalities": {
            "/v1/embeddings": ["embedding"],
            "/v1/images/generations": ["image"],
            "/v1/images/edits": ["image"],
            "/v1/audio/transcriptions": ["transcription"],
        }.get(args.endpoint, ["audio"]),
        "runs": runs_out,
    }
)
if image:
    payload["image_size"] = args.size
if edit:
    image_path = Path(args.image)
    image_data = image_path.read_bytes()
    payload["edit_image"] = {
        "name": image_path.name,
        "bytes": len(image_data),
        "sha256": hashlib.sha256(image_data).hexdigest(),
    }
if transcription:
    audio_path = Path(args.audio)
    audio_data = audio_path.read_bytes()
    payload["transcribe_audio"] = {
        "name": audio_path.name,
        "bytes": len(audio_data),
        "sha256": hashlib.sha256(audio_data).hexdigest(),
    }
    payload["language"] = args.language
    payload["transcription_stream"] = args.transcription_stream
args.output_json.parent.mkdir(parents=True, exist_ok=True)
args.output_json.write_text(json.dumps(payload, indent=2) + "\n")
print(f"\nSaved detailed JSON: {args.output_json}", flush=True)
