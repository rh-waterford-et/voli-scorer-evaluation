"""Transcription requests and dashboard integration without a live cluster."""

import argparse
import asyncio
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "dashboard" / "backend")]

import stream_metrics as metrics
from bench import RunParams
import app as dashboard_app
from store import normalize_output, summarize_output
from fastapi import HTTPException


def make_wav(seconds=2.0, byte_rate=8000, sample_width=2):
    """A minimal PCM WAV with a known duration (silence)."""
    data_size = int(byte_rate * seconds)
    fmt = struct.pack("<HHIIHH", 1, 1, byte_rate, byte_rate, sample_width, 16)
    body = b"\x00" * data_size

    def chunk(tag, payload):
        return tag + struct.pack("<I", len(payload)) + payload

    return b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(body)) + b"WAVE" + chunk(b"fmt ", fmt) + chunk(b"data", body)


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


def transcript_response(text="hello world"):
    return json.dumps({"text": text}).encode()


def parse_multipart(request):
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
            files[name] = (disposition.split('filename="')[1].split('"')[0], value)
        else:
            fields[name] = value.decode()
    return fields, files


def run_with(body, audio=None, prompt=None, language=None, content_type="application/json"):
    wav = audio if audio is not None else make_wav(1.0)
    args = argparse.Namespace(
        endpoint="/v1/audio/transcriptions", model="whisper", url="http://localhost:8000",
        api_key=None, profile=None, session_length=0, timeout=5, size=None,
        language=language,
        transcribe_audio={
            "name": "clip.wav", "bytes": len(wav), "sha256": hashlib.sha256(wav).hexdigest(),
            "format": "wav", "duration_seconds": 1.0, "data": wav,
        },
    )
    with patch.object(metrics.urllib.request, "urlopen", return_value=Response(body, content_type)) as opened:
        result = metrics.run_request(1, args, prompt, ["transcription"], "test-run")
    request = opened.call_args.args[0]
    metrics.add_metrics(result, None, ["transcription"])
    return result, request


class TranscriptionTests(unittest.TestCase):
    def test_multipart_request_shape(self):
        wav = make_wav(3.0)
        result, request = run_with(
            transcript_response("hello"), audio=wav, prompt="greeting context", language="en",
        )
        self.assertEqual(request.full_url, "http://localhost:8000/v1/audio/transcriptions")
        self.assertTrue(request.get_header("Content-type").startswith("multipart/form-data; boundary="))
        self.assertEqual(request.get_header("Accept"), "application/json")
        fields, files = parse_multipart(request)
        self.assertEqual(fields["model"], "whisper")
        self.assertEqual(fields["response_format"], "json")
        self.assertEqual(fields["prompt"], "greeting context")
        self.assertEqual(fields["language"], "en")
        self.assertEqual(files["file"], ("clip.wav", wav))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["transcript_chars"], 5)
        self.assertFalse(result["transcript_empty"])
        self.assertEqual(result["text"], "hello")

    def test_prompt_and_language_omitted_when_unset(self):
        _, request = run_with(transcript_response())
        fields, _files = parse_multipart(request)
        self.assertNotIn("prompt", fields)
        self.assertNotIn("language", fields)

    def test_response_tiers(self):
        result, _ = run_with(transcript_response("hello world"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["transcript_chars"], result["transcript_empty"]), (11, False))
        # Empty transcript: valid response, flagged, excluded from rankings.
        result, _ = run_with(transcript_response(""))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["transcript_empty"])
        # Plain-text responses are accepted (servers may ignore response_format).
        result, _ = run_with(b"hello world", content_type="text/plain")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["transcript_format"], "text")
        self.assertEqual(result["text"], "hello world")
        for bad in (b"not json", b"{}", b'{"text": 42}', b'{"error": "no model"}'):
            with self.subTest(bad=bad):
                result, _ = run_with(bad)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["error"])
        result, _ = run_with(b"oops", content_type="audio/wav")
        self.assertIn("expected JSON or text", result["error"])

    def test_audio_description_and_duration(self):
        wav = make_wav(2.5)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "clip.wav"
            path.write_bytes(wav)
            audio = metrics.load_transcribe_audio(path)
            self.assertEqual(audio["format"], "wav")
            self.assertEqual(audio["duration_seconds"], 2.5)
            self.assertEqual(audio["sha256"], hashlib.sha256(wav).hexdigest())
            self.assertEqual(audio["data"], wav)
            # Unrecognized formats are accepted, not rejected.
            mystery = Path(temp) / "mystery.bin"
            mystery.write_bytes(b"\x00\x01\x02 strange bytes")
            audio = metrics.load_transcribe_audio(mystery)
            self.assertIsNone(audio["format"])
            self.assertIsNone(audio["duration_seconds"])
            self.assertEqual(audio["bytes"], 17)
            with self.assertRaises(SystemExit):
                metrics.load_transcribe_audio(Path(temp) / "missing.wav")
        self.assertEqual(metrics.sniff_audio_format(b"fLaC" + b"\x00" * 8), "flac")
        self.assertEqual(metrics.sniff_audio_format(b"OggS" + b"\x00" * 8), "ogg")
        self.assertEqual(metrics.sniff_audio_format(b"ID3\x03\x00" + b"\x00" * 8), "mp3")

    def test_cli_suite_excludes_empty_transcripts(self):
        bodies = [transcript_response("hello"), transcript_response(""), transcript_response("world")]
        with tempfile.TemporaryDirectory() as temp:
            audio_path = Path(temp) / "clip.wav"
            audio_path.write_bytes(make_wav(1.0))
            output = Path(temp) / "result.json"
            state = {"index": 0}

            def next_response(*args, **kwargs):
                body = bodies[state["index"] % len(bodies)]
                state["index"] += 1
                return Response(body)

            argv = ["stream_metrics.py", "--endpoint", "/v1/audio/transcriptions", "--model", "whisper",
                    "--audio", str(audio_path), "--language", "en",
                    "--no-backend-lookup", "--output-json", str(output), "--run", "3x1", "--run", "3x2"]
            with patch.object(sys, "argv", argv), patch.object(
                metrics.urllib.request, "urlopen", side_effect=next_response,
            ), contextlib.redirect_stdout(io.StringIO()):
                metrics.main()
            document = json.loads(output.read_text())
            self.assertEqual(document["language"], "en")
            self.assertEqual(document["transcribe_audio"]["sha256"], hashlib.sha256(audio_path.read_bytes()).hexdigest())
            self.assertNotIn("data", document["transcribe_audio"])
            for run in document["runs"]:
                self.assertEqual(run["valid_responses"], 2)
                self.assertEqual(run["empty_transcripts"], 1)
                self.assertEqual(run["metrics"]["e2e_ms"]["n"], 2)

    def test_cli_prompt_default_not_sent_as_hint(self):
        wav = make_wav(0.5)
        with tempfile.TemporaryDirectory() as temp:
            audio_path = Path(temp) / "clip.wav"
            audio_path.write_bytes(wav)
            output = Path(temp) / "result.json"
            argv = ["stream_metrics.py", "--endpoint", "/v1/audio/transcriptions", "--model", "whisper",
                    "--audio", str(audio_path), "--no-backend-lookup", "--output-json", str(output)]
            captured = {}

            def capture(request, timeout=None):
                captured["request"] = request
                return Response(transcript_response("hi"))

            with patch.object(sys, "argv", argv), patch.object(
                metrics.urllib.request, "urlopen", side_effect=capture,
            ), contextlib.redirect_stdout(io.StringIO()):
                metrics.main()
            fields, _files = parse_multipart(captured["request"])
            self.assertNotIn("prompt", fields)

    def test_dashboard_params_and_summary(self):
        params = RunParams(endpoint="/v1/audio/transcriptions", model="whisper", profiles=["default"],
                           no_backend_lookup=True, input_file="/tmp/clip.wav", language="en")
        args = params.common_argv(Path("out.json"), None)
        self.assertIn("--audio", args)
        self.assertIn("/tmp/clip.wav", args)
        self.assertIn("--language", args)
        self.assertNotIn("--image", args)
        # The audio path is silently ignored outside transcription runs.
        tts = RunParams(endpoint="/v1/audio/speech", model="m", profiles=["default"],
                        input_file="/tmp/clip.wav")
        self.assertNotIn("--audio", tts.common_argv(Path("out.json"), None))
        normalized = normalize_output({
            "model": "m", "endpoint": "http://x/v1/audio/transcriptions", "modalities": ["transcription"],
            "transcribe_audio": {"name": "a.wav", "sha256": "abc"}, "language": "en",
            "runs": [{"profile": "p", "metrics": {}, "empty_transcripts": 2}],
        })
        self.assertEqual(normalized["transcribe_audio"]["sha256"], "abc")
        summary = summarize_output(normalized)
        self.assertEqual(summary["empty_transcripts"], 2)
        with patch.object(dashboard_app.cluster, "fetch_config", side_effect=HTTPException(503, "unavailable")) as fetch:
            checked = dashboard_app.profiles_check("/v1/audio/transcriptions")
        fetch.assert_called_once()
        self.assertEqual(checked["cluster_access"], "unavailable")


class CreateRunUploadTests(unittest.TestCase):
    """The multipart run-creation path with an unknown-format audio file."""

    class Manager:
        params = None

        def plan(self, params):
            return "test-run", []

        def create(self, name, params, run_id):
            CreateRunUploadTests.Manager.params = params
            return type("Run", (), {"run_id": run_id})()

    async def request(self, body, content_type):
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
            "method": "POST", "scheme": "http", "path": "/api/runs", "query_string": "",
            "headers": [(b"content-type", content_type.encode()),
                        (b"content-length", str(len(body)).encode())],
            "client": ("127.0.0.1", 1234), "server": ("localhost", 80), "root_path": "",
        }
        await dashboard_app.app(scope, receive, send)
        status = next(m["status"] for m in messages if m["type"] == "http.response.start")
        content = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return status, json.loads(content)

    def test_upload_accepted_and_metadata_recorded(self):
        from store import RunStore
        asyncio.set_event_loop(asyncio.new_event_loop())
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp))
            manager = self.Manager()
            boundary = "test-boundary"
            payload = json.dumps({"params": {"endpoint": "/v1/audio/transcriptions", "profiles": ["default"], "language": "hr"}})
            wav = make_wav(1.0)
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="params"\r\n\r\n{payload}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.wav"\r\n'
                'Content-Type: audio/wav\r\n\r\n'
            ).encode() + wav + f"\r\n--{boundary}--\r\n".encode()
            with patch.object(dashboard_app, "manager", manager), patch.object(dashboard_app, "store", store):
                status, result = asyncio.get_event_loop().run_until_complete(
                    self.request(body, f"multipart/form-data; boundary={boundary}"))
            self.assertEqual(status, 200)
            self.assertEqual(result["id"], "test-run")
            self.assertEqual(manager.params.input_info["sha256"], hashlib.sha256(wav).hexdigest())
            self.assertEqual(manager.params.input_info["name"], "clip.wav")
            self.assertEqual(manager.params.language, "hr")
            saved = Path(manager.params.input_file)
            self.assertEqual(saved.parent, store.run_dir("test-run") / "input")
            self.assertEqual(saved.read_bytes(), wav)
            # Missing upload is a client error and creates nothing.
            missing = json.dumps({"params": {"endpoint": "/v1/audio/transcriptions", "profiles": ["default"]}})
            with patch.object(dashboard_app, "manager", manager), patch.object(dashboard_app, "store", store):
                status, result = asyncio.get_event_loop().run_until_complete(
                    self.request(missing.encode(), "application/json"))
            self.assertEqual(status, 400)
            self.assertIn("audio file", result["detail"])


if __name__ == "__main__":
    unittest.main()
