"""End-to-end transcription CLI test with a local multipart-parsing server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


def make_wav(seconds=1.5, byte_rate=8000):
    data_size = int(byte_rate * seconds)
    fmt = struct.pack("<HHIIHH", 1, 1, byte_rate, byte_rate, 2, 16)
    body = b"\x00" * data_size

    def chunk(tag, payload):
        return tag + struct.pack("<I", len(payload)) + payload

    return b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(body)) + b"WAVE" + chunk(b"fmt ", fmt) + chunk(b"data", body)


INPUT_WAV = make_wav(1.5)


class Handler(BaseHTTPRequestHandler):
    requests = []

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
        response = json.dumps({"text": "stub heard hello"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


class HttpTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
