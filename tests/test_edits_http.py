"""End-to-end image-edit CLI test with a local multipart-parsing server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "dashboard" / "backend")]

import app as dashboard_app
from runner import RunManager
from store import RunStore


def make_png(width=2, height=2):
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


INPUT_PNG = make_png(3, 2)
OUTPUT_PNG = make_png(4, 4)


def parse_multipart_body(boundary, body):
    fields = {}
    files = {}
    for section in body.split(f"--{boundary}".encode())[1:-1]:
        section = section.strip(b"\r\n")
        if not section:
            continue
        header_blob, _, value = section.partition(b"\r\n\r\n")
        disposition = header_blob.decode()
        name = disposition.split('name="')[1].split('"')[0]
        if "filename=" in disposition:
            files[name] = (disposition.split('filename="')[1].split('"')[0], value)
        else:
            fields[name] = value.decode()
    return fields, files


class Handler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        boundary = self.headers["Content-Type"].split("boundary=")[1].strip()
        fields, files = parse_multipart_body(boundary, body)
        self.requests.append((self.path, self.headers.get("Accept"), fields, files))
        response = json.dumps({
            "created": 1,
            "data": [{"object": "image", "index": 0, "b64_json": base64.b64encode(OUTPUT_PNG).decode()}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


class HttpTests(unittest.TestCase):
    def test_real_http_edit_suite(self):
        Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                image_path = Path(temp) / "cat.png"
                image_path.write_bytes(INPUT_PNG)
                output = Path(temp) / "results.json"
                completed = subprocess.run([
                    sys.executable, str(ROOT / "scripts" / "stream_metrics.py"),
                    "--url", f"http://127.0.0.1:{server.server_port}", "--model", "flux-edit",
                    "--endpoint", "/v1/images/edits", "--profile", "default", "--prompt", "add a hat",
                    "--image", str(image_path), "--size", "512x512", "--run", "3x2", "--run", "2x1",
                    "--no-backend-lookup", "--output-json", str(output),
                ], capture_output=True, text=True, timeout=15, check=True)
                results = json.loads(output.read_text())
                self.assertEqual(results["modalities"], ["image"])
                self.assertEqual(results["image_size"], "512x512")
                self.assertEqual(results["edit_image"]["name"], "cat.png")
                self.assertEqual([r["validated_responses"] for r in results["runs"]], [3, 2])
                self.assertEqual(len(Handler.requests), 5)
                for path, accept, fields, files in Handler.requests:
                    self.assertEqual(path, "/v1/images/edits")
                    self.assertEqual(accept, "application/json")
                    self.assertEqual(fields["prompt"], "add a hat")
                    self.assertEqual(fields["n"], "1")
                    self.assertEqual(fields["size"], "512x512")
                    self.assertEqual(files["image"], ("cat.png", INPUT_PNG))
                self.assertIn("Profile suite results", completed.stdout)
                self.assertIn("reuse the same input image", completed.stdout)
        finally:
            server.shutdown()
            server.server_close()


class DashboardHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_runs_benchmark_and_keeps_image_provenance(self):
        Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                store = RunStore(Path(temp))
                manager = RunManager(store)
                params = {"params": {
                    "endpoint": "/v1/images/edits", "model": "flux-edit", "profiles": ["default"],
                    "url": f"http://127.0.0.1:{server.server_port}", "no_backend_lookup": True,
                    "prompt": "add a hat", "runs": [{"iterations": 2, "concurrency": 1}],
                }}
                boundary = "dashboard-test-boundary"
                body = (f'--{boundary}\r\nContent-Disposition: form-data; name="params"\r\n\r\n'
                        f'{json.dumps(params)}\r\n--{boundary}\r\n'
                        'Content-Disposition: form-data; name="file"; filename="my-cat.png"\r\n'
                        'Content-Type: image/png\r\n\r\n').encode() + INPUT_PNG + f"\r\n--{boundary}--\r\n".encode()
                scope = {
                    "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                    "method": "POST", "scheme": "http", "path": "/api/runs",
                    "raw_path": b"/api/runs", "query_string": b"",
                    "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
                                (b"content-length", str(len(body)).encode())],
                    "client": ("127.0.0.1", 1234), "server": ("localhost", 80), "root_path": "",
                }
                messages = []

                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}

                async def send(message):
                    messages.append(message)

                with patch.object(dashboard_app, "manager", manager), patch.object(dashboard_app, "store", store):
                    await dashboard_app.app(scope, receive, send)
                    self.assertEqual(next(m["status"] for m in messages if m["type"] == "http.response.start"), 200)
                    run_id = json.loads(next(m["body"] for m in messages if m["type"] == "http.response.body"))["id"]
                    run = manager.get(run_id)
                    for _ in range(150):
                        if run.status not in ("queued", "running"):
                            break
                        await asyncio.sleep(0.1)
                    self.assertEqual(run.status, "completed")
                    results = store.load_results(run.meta)
                    self.assertEqual(results["runs"][0]["validated_responses"], 2)
                    self.assertEqual(results["edit_image"]["name"], "my-cat.png")
                    self.assertEqual(results["edit_image"]["sha256"], hashlib.sha256(INPUT_PNG).hexdigest())
                    self.assertEqual([files["image"] for _, _, _, files in Handler.requests],
                                     [("my-cat.png", INPUT_PNG)] * 2)
                    self.assertTrue(store.delete(run_id))
                    self.assertFalse(store.run_dir(run_id).exists())
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
