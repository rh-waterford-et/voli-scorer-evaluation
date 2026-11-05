"""End-to-end image-generation CLI test with a local HTTP server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


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


PNG = make_png()


class Handler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, self.headers.get("Accept"), self.headers.get("EPP-Profile"), request))
        body = json.dumps({
            "created": 1,
            "data": [{"object": "image", "index": 0, "b64_json": base64.b64encode(PNG).decode()}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HttpTests(unittest.TestCase):
    def test_real_http_suite(self):
        Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "results.json"
                completed = subprocess.run([
                    sys.executable, str(ROOT / "scripts" / "stream_metrics.py"),
                    "--url", f"http://127.0.0.1:{server.server_port}", "--model", "flux",
                    "--endpoint", "/v1/images/generations", "--profile", "default", "--prompt", "a cat",
                    "--size", "512x512", "--run", "3x2", "--run", "2x1",
                    "--no-backend-lookup", "--output-json", str(output),
                ], capture_output=True, text=True, timeout=15, check=True)
                results = json.loads(output.read_text())
                self.assertEqual(results["modalities"], ["image"])
                self.assertEqual([r["valid_responses"] for r in results["runs"]], [3, 2])
                self.assertEqual([r["validated_responses"] for r in results["runs"]], [3, 2])
                self.assertEqual([r["unverified_responses"] for r in results["runs"]], [0, 0])
                self.assertEqual(len(Handler.requests), 5)
                for path, accept, profile, body in Handler.requests:
                    self.assertEqual(path, "/v1/images/generations")
                    self.assertEqual(accept, "application/json")
                    self.assertIsNone(profile)
                    self.assertEqual(body["prompt"], "a cat")
                    self.assertEqual(body["n"], 1)
                    self.assertEqual(body["response_format"], "b64_json")
                    self.assertEqual(body["size"], "512x512")
                self.assertIn("Profile suite results", completed.stdout)
                self.assertIn("(0 unverified)", completed.stdout)
                self.assertIn("content-verified PNG output", completed.stdout)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
