"""End-to-end transcription CLI test with a local multipart-parsing server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]


def make_wav(seconds=1.5, sample_rate=8000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00" * (int(sample_rate * seconds) * 2))
    return buffer.getvalue()


INPUT_WAV = make_wav(1.5)

sys.path.insert(0, str(ROOT / "dashboard" / "backend"))
from runner import RunManager
from store import RunStore
import app as dashboard_app


class Handler(BaseHTTPRequestHandler):
    requests = []
    release = None

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        boundary = self.headers["Content-Type"].split("boundary=")[1].strip()
        fields, files = {}, {}
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
        self.requests.append((self.path, self.headers.get("Accept"), fields, files))
        if fields.get("stream") == "true":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"type":"transcript.text.delta","delta":"hello"}\n\n')
            self.wfile.flush()
            if self.release is not None:
                self.release.wait(timeout=5)
            self.wfile.write(b'data: {"type":"transcript.text.done","text":"hello world"}\n\n')
            self.wfile.flush()
            return
        response = json.dumps({"text": "stub heard hello"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


class HttpTests(unittest.TestCase):
    def test_streaming_cli_and_incremental_delivery(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import stream_metrics

        Handler.requests = []
        Handler.release = threading.Event()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        first_received = threading.Event()
        captured = []

        def consume():
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/v1/audio/transcriptions",
                data=b'--b\r\nContent-Disposition: form-data; name="stream"\r\n\r\ntrue\r\n--b--\r\n',
                headers={"Content-Type": "multipart/form-data; boundary=b"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                for _, data, _ in stream_metrics.iter_transcription_events(response):
                    captured.append(data)
                    first_received.set()

        client = threading.Thread(target=consume, daemon=True)
        try:
            client.start()
            self.assertTrue(first_received.wait(timeout=3), "first event was buffered until completion")
            self.assertEqual(len(captured), 1)
            Handler.release.set()
            client.join(timeout=5)
            self.assertFalse(client.is_alive())
            self.assertEqual(len(captured), 2)
            with tempfile.TemporaryDirectory() as temp:
                audio_path = Path(temp) / "clip.wav"
                audio_path.write_bytes(INPUT_WAV)
                output = Path(temp) / "result.json"
                subprocess.run([
                    sys.executable, str(ROOT / "scripts" / "stream_metrics.py"),
                    "--url", f"http://127.0.0.1:{server.server_port}", "--model", "whisper",
                    "--endpoint", "/v1/audio/transcriptions", "--profile", "default",
                    "--audio", str(audio_path), "--transcription-stream", "--run", "2x1",
                    "--no-backend-lookup", "--output-json", str(output),
                ], capture_output=True, text=True, timeout=15, check=True)
                result = json.loads(output.read_text())
                self.assertTrue(result["transcription_stream"])
                self.assertEqual(result["valid_responses"], 2)
                self.assertEqual(result["metrics"]["ttft_ms"]["n"], 2)
                self.assertTrue(all(r["text"] == "hello world" for r in result["results"]))
                self.assertTrue(all(fields.get("stream") == "true" for _, _, fields, _ in Handler.requests))
        finally:
            Handler.release.set()
            client.join(timeout=5)
            server.shutdown()
            server.server_close()
            Handler.release = None

    def test_real_http_transcription_suite(self):
        Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                audio_path = Path(temp) / "clip.wav"
                audio_path.write_bytes(INPUT_WAV)
                output = Path(temp) / "results.json"
                completed = subprocess.run([
                    sys.executable, str(ROOT / "scripts" / "stream_metrics.py"),
                    "--url", f"http://127.0.0.1:{server.server_port}", "--model", "whisper",
                    "--endpoint", "/v1/audio/transcriptions", "--profile", "default",
                    "--audio", str(audio_path), "--language", "en", "--run", "3x2", "--run", "2x1",
                    "--no-backend-lookup", "--output-json", str(output),
                ], capture_output=True, text=True, timeout=15, check=True)
                results = json.loads(output.read_text())
                self.assertEqual(results["modalities"], ["transcription"])
                self.assertEqual(results["language"], "en")
                self.assertEqual(results["transcribe_audio"]["name"], "clip.wav")
                self.assertEqual([r["valid_responses"] for r in results["runs"]], [3, 2])
                self.assertEqual(len(Handler.requests), 5)
                for path, accept, fields, files in Handler.requests:
                    self.assertEqual(path, "/v1/audio/transcriptions")
                    self.assertEqual(accept, "application/json")
                    self.assertEqual(fields["model"], "whisper")
                    self.assertEqual(fields["language"], "en")
                    self.assertEqual(fields["response_format"], "json")
                    self.assertNotIn("prompt", fields)  # no default prompt as hint
                    self.assertEqual(files["file"], ("clip.wav", INPUT_WAV))
                self.assertIn("Profile suite results", completed.stdout)
                self.assertIn("same input audio", completed.stdout)
        finally:
            server.shutdown()
            server.server_close()


class DashboardStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_uploaded_file_runs_streaming_through_dashboard(self):
        Handler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                store = RunStore(Path(temp))
                manager = RunManager(store)
                params = {"params": {"endpoint": "/v1/audio/transcriptions", "model": "whisper",
                    "profiles": ["default"], "url": f"http://127.0.0.1:{server.server_port}",
                    "no_backend_lookup": True, "transcription_stream": True,
                    "runs": [{"iterations": 2, "concurrency": 1}]}}
                boundary = "dashboard-audio-test"
                body = (f'--{boundary}\r\nContent-Disposition: form-data; name="params"\r\n\r\n'
                    f'{json.dumps(params)}\r\n--{boundary}\r\n'
                    'Content-Disposition: form-data; name="file"; filename="clip.wav"\r\n'
                    'Content-Type: audio/wav\r\n\r\n').encode() + INPUT_WAV + f"\r\n--{boundary}--\r\n".encode()
                scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                    "method": "POST", "scheme": "http", "path": "/api/runs", "raw_path": b"/api/runs",
                    "query_string": b"", "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
                    (b"content-length", str(len(body)).encode())], "client": ("127.0.0.1", 1234),
                    "server": ("localhost", 80), "root_path": ""}
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
                    self.assertTrue(results["transcription_stream"])
                    self.assertEqual(results["runs"][0]["metrics"]["ttft_ms"]["n"], 2)
                    self.assertTrue(all(fields.get("stream") == "true" for _, _, fields, _ in Handler.requests))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
