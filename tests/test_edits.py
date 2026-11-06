"""Image-edit requests and dashboard integration without a live cluster."""

import argparse
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
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
from store import normalize_output
from fastapi import HTTPException


def make_png(width=2, height=3):
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


def edit_response(image=None, url=None):
    item = {}
    if image is not None:
        item["b64_json"] = base64.b64encode(image).decode()
    if url is not None:
        item["url"] = url
    return json.dumps({"created": 1, "data": [item]}).encode()


def parse_multipart(request):
    """Split a multipart body into {field: value} and {field: file bytes}."""
    content_type = request.get_header("Content-type")
    boundary = content_type.split("boundary=")[1].strip()
    sections = request.data.split(f"--{boundary}".encode())
    fields, files = {}, {}
    for section in sections[1:-1]:
        section = section.strip(b"\r\n")
        if not section:
            continue
        header_blob, _, value = section.partition(b"\r\n\r\n")
        disposition = header_blob.decode()
        name = disposition.split('name="')[1].split('"')[0]
        if "filename=" in disposition:
            files[name] = value
        else:
            fields[name] = value.decode()
    return fields, files


def run_with(body, size=None, image=None, content_type="application/json"):
    png = image if image is not None else make_png(3, 2)
    args = argparse.Namespace(
        endpoint="/v1/images/edits", model="flux-edit", url="http://localhost:8000",
        api_key=None, profile=None, session_length=0, timeout=5, size=size,
        edit_image={
            "name": "input.png", "bytes": len(png), "sha256": hashlib.sha256(png).hexdigest(),
            "format": "png", "dimensions": [3, 2], "data": png,
        },
    )
    with patch.object(metrics.urllib.request, "urlopen", return_value=Response(body, content_type)) as opened:
        result = metrics.run_request(1, args, "add a hat", ["image"], "test-run")
    request = opened.call_args.args[0]
    metrics.add_metrics(result, None, ["image"])
    return result, request


class EditTests(unittest.TestCase):
    def test_multipart_request_shape(self):
        png = make_png(3, 2)
        result, request = run_with(edit_response(image=make_png()), size="512x512", image=png)
        self.assertEqual(request.full_url, "http://localhost:8000/v1/images/edits")
        self.assertTrue(request.get_header("Content-type").startswith("multipart/form-data; boundary="))
        self.assertEqual(request.get_header("Accept"), "application/json")
        fields, files = parse_multipart(request)
        self.assertEqual(fields["model"], "flux-edit")
        self.assertEqual(fields["prompt"], "add a hat")
        self.assertEqual(fields["n"], "1")
        self.assertEqual(fields["response_format"], "b64_json")
        self.assertEqual(fields["size"], "512x512")
        self.assertEqual(files["image"], png)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["image_content"], "b64-validated")

    def test_size_omitted_when_unset(self):
        _, request = run_with(edit_response(image=make_png()))
        fields, _files = parse_multipart(request)
        self.assertNotIn("size", fields)

    def test_response_tiers_shared_with_generations(self):
        png = make_png(4, 4)
        result, _ = run_with(edit_response(image=png))
        self.assertEqual((result["image_content"], result["image_dimensions"]), ("b64-validated", [4, 4]))
        result, _ = run_with(edit_response(image=b"\xff\xd8\xff\xe0" + b"\x00" * 16))
        self.assertEqual(result["image_content"], "b64-unverified")
        self.assertIsNone(result["image_dimensions"])
        result, _ = run_with(edit_response(url="https://example.com/out.png"))
        self.assertEqual((result["image_content"], result["image_bytes"]), ("url-unverified", None))
        for bad in (b"not json", b'{"data": []}', b'{"data": [{}]}', edit_response(image=b"no image magic")):
            with self.subTest(bad=bad):
                result, _ = run_with(bad)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["error"])
        result, _ = run_with(b"oops", content_type="text/html")
        self.assertIn("expected JSON", result["error"])

    def test_load_edit_image(self):
        with tempfile.TemporaryDirectory() as temp:
            good = Path(temp) / "photo.png"
            good.write_bytes(make_png(6, 4))
            info = metrics.load_edit_image(good)
            self.assertEqual(info["name"], "photo.png")
            self.assertEqual(info["format"], "png")
            self.assertEqual(info["dimensions"], [6, 4])
            self.assertEqual(info["bytes"], len(good.read_bytes()))
            self.assertEqual(info["sha256"], hashlib.sha256(good.read_bytes()).hexdigest())
            self.assertEqual(info["data"], good.read_bytes())
            public = metrics.public_edit_image(info)
            self.assertEqual(public["sha256"], info["sha256"])
            self.assertNotIn("data", public)
            bad = Path(temp) / "not-image.txt"
            bad.write_text("hello")
            with self.assertRaises(SystemExit):
                metrics.load_edit_image(bad)
            with self.assertRaises(SystemExit):
                metrics.load_edit_image(Path(temp) / "missing.png")
            bad_png = Path(temp) / "broken.png"
            for data in (b"\x89PNG\r\n\x1a\n", make_png()[:29] + b"\x00\x00\x00\x00"):
                with self.subTest(data=data):
                    bad_png.write_bytes(data)
                    with self.assertRaisesRegex(SystemExit, "invalid PNG header"):
                        metrics.load_edit_image(bad_png)

    def test_cli_suite_saves_edit_image_and_counts(self):
        png = make_png(2, 2)
        body = edit_response(image=make_png(5, 5))
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "input.png"
            image_path.write_bytes(png)
            output = Path(temp) / "result.json"
            argv = ["stream_metrics.py", "--endpoint", "/v1/images/edits", "--model", "flux-edit",
                    "--image", str(image_path), "--size", "512x512",
                    "--no-backend-lookup", "--output-json", str(output), "--run", "4x1", "--run", "4x2"]
            with patch.object(sys, "argv", argv), patch.object(
                metrics.urllib.request, "urlopen", side_effect=lambda *a, **k: Response(body),
            ), contextlib.redirect_stdout(io.StringIO()):
                metrics.main()
            document = json.loads(output.read_text())
            self.assertEqual(document["image_size"], "512x512")
            self.assertEqual(document["edit_image"]["sha256"], hashlib.sha256(png).hexdigest())
            self.assertEqual(document["edit_image"]["name"], "input.png")
            self.assertNotIn("data", document["edit_image"])
            for run in document["runs"]:
                self.assertEqual(run["validated_responses"], 4)
                self.assertEqual(run["metrics"]["e2e_ms"]["n"], 4)

    def test_cli_requires_image_for_edits(self):
        argv = ["stream_metrics.py", "--endpoint", "/v1/images/edits", "--model", "m"]
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                metrics.main()

    def test_dashboard_params_and_store_roundtrip(self):
        params = RunParams(endpoint="/v1/images/edits", model="flux-edit", profiles=["default"],
                           no_backend_lookup=True, input_file="/tmp/some-input.png", image_size="1024x1024")
        args = params.common_argv(Path("out.json"), None)
        self.assertIn("--image", args)
        self.assertIn("/tmp/some-input.png", args)
        self.assertIn("--size", args)
        # The image path is silently ignored outside edit runs.
        generation = RunParams(endpoint="/v1/images/generations", model="flux", profiles=["default"],
                               input_file="/tmp/some-input.png")
        self.assertNotIn("--image", generation.common_argv(Path("out.json"), None))
        # Combined results keep the edit-image metadata for Compare.
        normalized = normalize_output({
            "model": "m", "endpoint": "http://x/v1/images/edits", "modalities": ["image"],
            "edit_image": {"name": "a.png", "sha256": "abc"}, "runs": [{"profile": "p", "metrics": {}}],
        })
        self.assertEqual(normalized["edit_image"]["sha256"], "abc")
        # Cluster access still degrades to unknown for the new endpoint.
        with patch.object(dashboard_app.cluster, "fetch_config", side_effect=HTTPException(503, "unavailable")) as fetch:
            checked = dashboard_app.profiles_check("/v1/images/edits")
        fetch.assert_called_once()
        self.assertEqual(checked["cluster_access"], "unavailable")

    def test_save_run_image_lives_inside_the_run_directory(self):
        from store import RunStore
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp))
            png = make_png(2, 2)
            path, info = store.save_run_input("run-x", png, 'weird "name".png')
            self.assertEqual(path.parent, store.run_dir("run-x") / "input")
            self.assertTrue(path.suffix == ".png")
            self.assertEqual(path.name, 'weird "name".png')
            self.assertEqual(path.read_bytes(), png)
            self.assertEqual(info["sha256"], hashlib.sha256(png).hexdigest())
            self.assertEqual(info["bytes"], len(png))
            self.assertEqual(info["name"], 'weird "name".png')
            self.assertEqual(metrics.load_edit_image(path)["name"], info["name"])

    def test_preview_includes_image_placeholder(self):
        from runner import RunManager
        from store import RunStore
        with tempfile.TemporaryDirectory() as temp:
            manager = RunManager(RunStore(Path(temp)))
            params = RunParams(endpoint="/v1/images/edits", profiles=["default"])
            argv = manager.preview(params)["profiles"][0]["argv"]
            self.assertEqual(argv[argv.index("--image") + 1], "YOUR_IMAGE_PATH")
            self.assertIsNone(params.input_file)

    def test_stub_reports_actual_input_image(self):
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "original.png"
            output = Path(temp) / "result.json"
            hashes = []
            for png in (make_png(2, 2), make_png(3, 3)):
                image_path.write_bytes(png)
                subprocess.run([
                    sys.executable, str(ROOT / "dashboard" / "dev" / "stub_benchmark.py"),
                    "--endpoint", "/v1/images/edits", "--image", str(image_path),
                    "--run", "1x1", "--output-json", str(output),
                ], check=True, capture_output=True)
                info = json.loads(output.read_text())["edit_image"]
                self.assertEqual(info["name"], "original.png")
                self.assertEqual(info["bytes"], len(png))
                self.assertEqual(info["sha256"], hashlib.sha256(png).hexdigest())
                hashes.append(info["sha256"])
            self.assertNotEqual(*hashes)


class DashboardCreateTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, body, content_type="application/json"):
        messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/api/runs",
            "raw_path": b"/api/runs", "query_string": b"",
            "headers": [(b"content-type", content_type.encode()),
                        (b"content-length", str(len(body)).encode())],
            "client": ("127.0.0.1", 1234), "server": ("localhost", 80), "root_path": "",
        }
        await dashboard_app.app(scope, receive, send)
        status = next(message["status"] for message in messages if message["type"] == "http.response.start")
        content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return status, json.loads(content)

    async def test_invalid_json_and_run_params_report_client_errors(self):
        for body in (b"bad json", b"[]", b'{"params":{"profiles":[]}}',
                     b'{"params":{"profiles":["default"],"session_length":1}}'):
            with self.subTest(body=body):
                status, result = await self.request(body)
                self.assertEqual(status, 422)
                self.assertIn("detail", result)

    async def test_upload_validation_and_filename(self):
        from store import RunStore

        class Manager:
            params = None

            def plan(self, params):
                return "test-run", []

            def create(self, name, params, run_id):
                self.params = params
                return type("Run", (), {"run_id": run_id})()

        boundary = "test-boundary"
        payload = json.dumps({"params": {"endpoint": "/v1/images/edits", "profiles": ["default"]}})
        prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="params"\r\n\r\n{payload}\r\n'
                  f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="original.png"\r\n'
                  'Content-Type: image/png\r\n\r\n').encode()
        suffix = f"\r\n--{boundary}--\r\n".encode()
        with tempfile.TemporaryDirectory() as temp:
            manager = Manager()
            store = RunStore(Path(temp))
            with patch.object(dashboard_app, "manager", manager), patch.object(dashboard_app, "store", store):
                status, result = await self.request(prefix + b"\x89PNG\r\n\x1a\n" + suffix,
                                                    f"multipart/form-data; boundary={boundary}")
                self.assertEqual(status, 400)
                self.assertIn("PNG header", result["detail"])
                self.assertFalse(store.run_dir("test-run").exists())
                status, result = await self.request(prefix + make_png() + suffix,
                                                    f"multipart/form-data; boundary={boundary}")
                self.assertEqual(status, 200)
                self.assertEqual(result["id"], "test-run")
                info = metrics.load_edit_image(manager.params.input_file)
                self.assertEqual(info["name"], "original.png")
                self.assertEqual(info["sha256"], manager.params.input_info["sha256"])


if __name__ == "__main__":
    unittest.main()
