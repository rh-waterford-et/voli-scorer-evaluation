"""Embedding requests and dashboard integration without a live cluster."""

import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "dashboard" / "backend")]

import stream_metrics as metrics
from bench import RunParams
import app as dashboard_app
from fastapi import HTTPException


class Response:
    def __init__(self, body, content_type="application/json"):
        self.body = body
        self.headers = {"Content-Type": content_type, "X-Request-Id": "response-id"}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size=-1):
        return self.body[:size] if size >= 0 else self.body

    def __iter__(self):
        return iter(self.body.splitlines(keepends=True))


def run_with(body, content_type="application/json"):
    args = argparse.Namespace(
        endpoint="/v1/embeddings", model="embed-model", url="http://localhost:8000",
        api_key=None, profile=None, session_length=0, timeout=5,
    )
    with patch.object(metrics.urllib.request, "urlopen", return_value=Response(body, content_type)) as opened:
        result = metrics.run_request(1, args, "hello", ["embedding"], "test-run")
    request = opened.call_args.args[0]
    metrics.add_metrics(result, None, ["embedding"])
    return result, request


class EmbeddingTests(unittest.TestCase):
    def test_valid_response_and_request(self):
        result, request = run_with(json.dumps({
            "data": [{"index": 0, "embedding": [0.25, -1.5, 0]}],
            "usage": {"prompt_tokens": 2, "total_tokens": 2},
        }).encode())
        self.assertEqual(json.loads(request.data), {
            "model": "embed-model", "input": "hello", "encoding_format": "float",
        })
        self.assertEqual(request.full_url, "http://localhost:8000/v1/embeddings")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["embedding_dimensions"], 3)
        self.assertEqual(result["usage"]["prompt_tokens"], 2)
        self.assertNotIn("embedding", result)
        self.assertGreaterEqual(result["e2e_ms"], 0)
        self.assertIsNone(result["ttft_ms"])
        self.assertIsNone(result["ttfa_ms"])
        self.assertEqual(result["missing_modalities"], [])

    def test_invalid_or_missing_embedding_fails(self):
        bad = [b"not json", b"{}", b'{"data": []}', b'{"data": [{"embedding": []}]}',
               b'{"data": [{"embedding": [true]}]}', b'{"data": [{"embedding": [NaN]}]}',
               b'{"data": [{"embedding": "base64"}]}']
        for body in bad:
            with self.subTest(body=body):
                result, _ = run_with(body)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["error"])
        result, _ = run_with(b"oops", "text/html")
        self.assertEqual(result["status"], "failed")
        self.assertIn("expected JSON", result["error"])

    def test_cli_suite_and_single_use_only_e2e_samples(self):
        body = b'{"data": [{"embedding": [0.1, 0.2]}]}'
        for settings in (["--run", "2x1"], ["--run", "2x1", "--run", "2x2"]):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "result.json"
                argv = ["stream_metrics.py", "--endpoint", "/v1/embeddings", "--model", "embed",
                        "--no-backend-lookup", "--output-json", str(output), *settings]
                with patch.object(sys, "argv", argv), patch.object(metrics.urllib.request, "urlopen", side_effect=lambda *a, **k: Response(body)), contextlib.redirect_stdout(io.StringIO()):
                    metrics.main()
                document = json.loads(output.read_text())
                runs = document.get("runs", [document])
                self.assertEqual(len(runs), len(settings) // 2)
                for run in runs:
                    self.assertEqual(run["valid_responses"], 2)
                    self.assertEqual(run["metrics"]["e2e_ms"]["n"], 2)
                    self.assertEqual(run["metrics"]["ttft_ms"]["n"], 0)
                    self.assertEqual(run["metrics"]["ttfa_ms"]["n"], 0)

    def test_dashboard_params_and_live_cluster_check(self):
        params = RunParams(endpoint="/v1/embeddings", model="embed", profiles=["default"],
                           no_backend_lookup=True, voice="stale", audio_format="pcm")
        args = params.common_argv(Path("out.json"), None)
        self.assertIn("/v1/embeddings", args)
        self.assertNotIn("--tokenizer", args)
        self.assertNotIn("--voice", args)
        self.assertNotIn("--audio-format", args)
        with patch.object(dashboard_app.cluster, "fetch_config", side_effect=HTTPException(503, "unavailable")) as fetch:
            checked = dashboard_app.profiles_check("/v1/embeddings")
        fetch.assert_called_once()
        self.assertEqual(checked["cluster_access"], "unavailable")
        self.assertEqual(checked["cluster_error"], "unavailable")

    def test_existing_streaming_request_paths(self):
        for endpoint, modalities, body in (
            ("/v1/chat/completions", ["text"], b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'),
            ("/v1/audio/speech", ["audio"], b'data: {"type":"speech.audio.delta","audio":"abc"}\n\ndata: {"type":"speech.audio.done"}\n\n'),
        ):
            with self.subTest(endpoint=endpoint):
                args = argparse.Namespace(endpoint=endpoint, model="model", url="http://localhost:8000",
                    api_key=None, profile="queue", session_length=0, timeout=5, voice=None,
                    audio_format=None, no_usage=False)
                with patch.object(metrics.urllib.request, "urlopen", return_value=Response(body, "text/event-stream")) as opened:
                    result = metrics.run_request(1, args, "hello", modalities, "test-run")
                metrics.add_metrics(result, None, modalities)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["missing_modalities"], [])
                request = opened.call_args.args[0]
                self.assertEqual(request.get_header("Accept"), "text/event-stream")
                self.assertEqual(request.get_header("Epp-profile"), "queue")
                self.assertTrue(json.loads(request.data)["stream"])


if __name__ == "__main__":
    unittest.main()
