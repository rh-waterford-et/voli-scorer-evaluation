"""Image-generation requests and dashboard integration without a live cluster."""

import argparse
import base64
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "dashboard" / "backend")]

import stream_metrics as metrics
from bench import RunParams
import app as dashboard_app
from fastapi import HTTPException
from store import normalize_output, summarize_output


def make_png(width=2, height=3):
    """A minimal valid PNG so tests need no binary fixtures in the repo."""

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\xff" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


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


def image_document(image=None, url=None):
    item = {}
    if image is not None:
        item["b64_json"] = base64.b64encode(image).decode()
    if url is not None:
        item["url"] = url
    return json.dumps({"created": 1, "data": [item]}).encode()


def run_with(body, content_type="application/json", size=None):
    args = argparse.Namespace(
        endpoint="/v1/images/generations", model="flux-model", url="http://localhost:8000",
        api_key=None, profile=None, session_length=0, timeout=5, size=size,
    )
    with patch.object(metrics.urllib.request, "urlopen", return_value=Response(body, content_type)) as opened:
        result = metrics.run_request(1, args, "a cat", ["image"], "test-run")
    request = opened.call_args.args[0]
    metrics.add_metrics(result, None, ["image"])
    return result, request


class ImageTests(unittest.TestCase):
    def test_valid_png_response_and_request(self):
        png = make_png(4, 5)
        result, request = run_with(image_document(image=png))
        self.assertEqual(json.loads(request.data), {
            "model": "flux-model", "prompt": "a cat", "n": 1, "response_format": "b64_json",
        })
        self.assertEqual(request.full_url, "http://localhost:8000/v1/images/generations")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["image_content"], "b64-validated")
        self.assertEqual(result["image_format"], "png")
        self.assertEqual(result["image_bytes"], len(png))
        self.assertEqual(result["image_dimensions"], [4, 5])
        self.assertIsNone(result["ttft_ms"])
        self.assertIsNone(result["ttfa_ms"])
        self.assertEqual(result["missing_modalities"], [])
        self.assertGreaterEqual(result["e2e_ms"], 0)

    def test_size_is_sent_only_when_set(self):
        _, request = run_with(image_document(image=make_png()), size="512x512")
        self.assertEqual(json.loads(request.data)["size"], "512x512")

    def test_url_only_response_is_ok_but_unverified(self):
        result, _ = run_with(image_document(url="https://example.com/img.png"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["image_content"], "url-unverified")
        self.assertIsNone(result["image_bytes"])
        self.assertIsNone(result["image_format"])

    def test_non_png_base64_is_ok_but_unverified(self):
        result, _ = run_with(image_document(image=b"\xff\xd8\xff\xe0" + b"\x00" * 32))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["image_content"], "b64-unverified")
        self.assertEqual(result["image_format"], "jpeg")
        self.assertIsNone(result["image_dimensions"])

    def test_invalid_or_missing_image_fails(self):
        bad = [
            b"not json",
            b"{}",
            b'{"data": []}',
            b'{"data": [{}]}',
            b'{"data": [{"b64_json": "not base64 !!"}]}',
            b'{"data": [{"b64_json": "' + base64.b64encode(b"plain text, no image") + b'"}]}',
            b'{"error": "model unavailable"}',
            image_document(image=b"\x89PNG\r\n\x1a\n"),
            image_document(image=make_png()[:24]),
            image_document(image=make_png()[:29] + b"\x00\x00\x00\x00"),
        ]
        for body in bad:
            with self.subTest(body=body):
                result, _ = run_with(body)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["error"])
        result, _ = run_with(b"oops", "text/html")
        self.assertEqual(result["status"], "failed")
        self.assertIn("expected JSON", result["error"])

    def test_cli_suite_counts_validated_separately(self):
        png = image_document(image=make_png())
        url_only = image_document(url="https://example.com/img.png")
        cycle = [png, png, url_only, png, url_only]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "result.json"
            argv = ["stream_metrics.py", "--endpoint", "/v1/images/generations", "--model", "flux",
                    "--no-backend-lookup", "--output-json", str(output), "--run", "5x1", "--run", "5x2"]
            state = {"index": 0}

            def next_response(*args, **kwargs):
                body = cycle[state["index"] % len(cycle)]
                state["index"] += 1
                return Response(body)

            with patch.object(sys, "argv", argv), patch.object(
                metrics.urllib.request, "urlopen", side_effect=next_response,
            ), contextlib.redirect_stdout(io.StringIO()):
                metrics.main()
            document = json.loads(output.read_text())
            for run in document["runs"]:
                self.assertEqual(run["valid_responses"], 3)
                self.assertEqual(run["validated_responses"], 3)
                self.assertEqual(run["unverified_responses"], 2)
                # Latency samples cover only content-verified responses.
                self.assertEqual(run["metrics"]["e2e_ms"]["n"], 3)
                self.assertEqual(run["metrics"]["ttfa_ms"]["n"], 0)
            self.assertEqual(summarize_output(normalize_output(document))["valid"], 6)
            self.assertEqual(summarize_output(normalize_output(document))["unverified"], 4)

    def test_requested_size_and_endpoint_survive_single_and_suite_reports(self):
        png = image_document(image=make_png())
        for settings in (["--run", "1x1"], ["--run", "1x1", "--run", "1x2"]):
            for size in ("512x512", "1024x1024", None):
                with self.subTest(settings=settings, size=size), tempfile.TemporaryDirectory() as temp:
                    output = Path(temp) / "result.json"
                    argv = ["stream_metrics.py", "--endpoint", "/v1/images/generations", "--model", "flux",
                            "--no-backend-lookup", "--output-json", str(output), *settings]
                    if size is not None:
                        argv += ["--size", size]
                    with patch.object(sys, "argv", argv), patch.object(
                        metrics.urllib.request, "urlopen", side_effect=lambda *a, **k: Response(png),
                    ), contextlib.redirect_stdout(io.StringIO()):
                        metrics.main()
                    document = json.loads(output.read_text())
                    normalized = normalize_output(document)
                    self.assertEqual(normalized["image_size"], size)
                    self.assertEqual(normalized["model"], "flux")
                    self.assertTrue(normalized["endpoint"].endswith("/v1/images/generations"))
                    self.assertEqual(normalized["modalities"], ["image"])

    def test_session_latency_excludes_unverified_images(self):
        base = {
            "session_id": "session-1", "session_token_sent": None, "session_token_received": None,
            "pod": None, "status": "ok", "missing_modalities": [], "ttft_ms": None,
            "ttfa_ms": None, "e2e_ms": 1.0,
        }
        results = [
            dict(base, session_turn=1, image_content="url-unverified"),
            dict(base, session_turn=2, image_content="b64-validated", session_token_sent="token"),
        ]
        args = argparse.Namespace(session_header="x-session-token", session_length=2)
        summary = metrics.summarize_sessions(args, results, 1)
        self.assertEqual(summary["latency"]["initial"]["e2e_ms"]["n"], 0)
        self.assertEqual(summary["latency"]["replayed"]["e2e_ms"]["n"], 1)

    def test_dashboard_params_and_live_cluster_check(self):
        params = RunParams(endpoint="/v1/images/generations", model="flux", profiles=["default"],
                           no_backend_lookup=True, image_size="1024x1024",
                           voice="stale", audio_format="pcm")
        args = params.common_argv(Path("out.json"), None)
        self.assertIn("/v1/images/generations", args)
        self.assertIn("1024x1024", args)
        self.assertNotIn("--voice", args)
        self.assertNotIn("--audio-format", args)
        self.assertNotIn("--tokenizer", args)
        # Size is silently ignored outside image runs, like voice outside audio runs.
        chat = RunParams(endpoint="/v1/chat/completions", model="m", profiles=["default"],
                         tokenizer="tok", image_size="1024x1024")
        self.assertNotIn("--size", chat.common_argv(Path("out.json"), None))
        with patch.object(dashboard_app.cluster, "fetch_config", side_effect=HTTPException(503, "unavailable")) as fetch:
            checked = dashboard_app.profiles_check("/v1/images/generations")
        fetch.assert_called_once()
        self.assertEqual(checked["cluster_access"], "unavailable")


if __name__ == "__main__":
    unittest.main()
