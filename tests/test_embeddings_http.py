"""End-to-end CLI test with a local OpenAI-compatible HTTP server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, self.headers.get("Accept"), self.headers.get("EPP-Profile"), request))
        body = json.dumps({"data": [{"object": "embedding", "index": 0, "embedding": [0.5, -0.25]}],
                           "usage": {"prompt_tokens": 1, "total_tokens": 1}}).encode()
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
                    "--url", f"http://127.0.0.1:{server.server_port}", "--model", "embed",
                    "--endpoint", "/v1/embeddings", "--profile", "default", "--prompt", "hello",
                    "--run", "3x2", "--run", "2x1", "--no-backend-lookup", "--output-json", str(output),
                ], capture_output=True, text=True, timeout=15, check=True)
                results = json.loads(output.read_text())
                self.assertEqual(results["modalities"], ["embedding"])
                self.assertEqual([r["valid_responses"] for r in results["runs"]], [3, 2])
                self.assertEqual(len(Handler.requests), 5)
                for path, accept, profile, body in Handler.requests:
                    self.assertEqual(path, "/v1/embeddings")
                    self.assertEqual(accept, "application/json")
                    self.assertIsNone(profile)
                    self.assertEqual(body["input"], "hello")
                self.assertIn("Embeddings are non-streaming", completed.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
