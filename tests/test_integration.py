"""Opt-in integration test: real ffmpeg extraction + real local HTTP server.

No external API is called. Run with:

    RUN_INTEGRATION=1 pytest tests/test_integration.py -q
"""

import email
import email.policy
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import analyzer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_VIDEO = os.path.join(REPO_ROOT, "examples", "example_video.mp4")

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1",
        reason="set RUN_INTEGRATION=1 to run integration tests",
    ),
    pytest.mark.skipif(
        shutil.which("ffmpeg") is None,
        reason="ffmpeg is not installed",
    ),
    pytest.mark.skipif(
        not os.path.exists(EXAMPLE_VIDEO),
        reason="examples/example_video.mp4 is missing",
    ),
]

RESPONSE_PAYLOAD = {
    "title": "Integration title",
    "description": "Integration description",
    "keywords": "frame, test",
}


class RecordingHandler(BaseHTTPRequestHandler):
    """Records multipart requests and returns a fixed metadata response."""

    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")

        message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
            b"Content-Type: " + content_type.encode()
            + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        parts = []
        for part in message.iter_parts():
            parts.append({
                "name": part.get_param("name", header="content-disposition"),
                "filename": part.get_filename(),
                "data": part.get_payload(decode=True),
            })
        type(self).requests.append({"path": self.path, "parts": parts})

        payload = json.dumps(RESPONSE_PAYLOAD).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def recording_server():
    RecordingHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, RecordingHandler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_two_frames_are_extracted_and_sent_in_one_request(tmp_path, recording_server):
    server, handler = recording_server
    port = server.server_address[1]

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    shutil.copy2(EXAMPLE_VIDEO, input_dir / "clip.mp4")
    output_dir = tmp_path / "output"

    config = analyzer.Config(
        api_key="integration-key",
        webhook_url=f"http://127.0.0.1:{port}/analyze",
        analyze_multiple_url=f"http://127.0.0.1:{port}/analyze-multiple",
        output_dir=str(output_dir),
        fractions=[0.5, 0.9],
        dedup_threshold=0,  # keep both frames regardless of similarity
        cleanup_thumbnails=False,
        force=False,
        extensions=(".mp4",),
        provider=None,
    )

    analyzer.process_videos(str(input_dir), config)

    assert len(handler.requests) == 1, "expected exactly one API request"
    request = handler.requests[0]
    assert request["path"] == "/analyze-multiple"

    image_parts = [part for part in request["parts"] if part["name"] == "images"]
    assert [part["filename"] for part in image_parts] == [
        "clip_001.jpg",
        "clip_002.jpg",
    ]
    assert all(part["data"] for part in image_parts), "image payloads must not be empty"

    fields = {
        part["name"]: part["data"].decode("utf-8")
        for part in request["parts"]
        if part["name"] != "images"
    }
    assert fields["filename"] == "clip.mp4"
    assert fields["generateTwoPartKeywords"] == "true"
    assert fields["useFilename"] == "true"

    csv_path = output_dir / "clip.csv"
    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Filename,Title,Description,Keywords"
    assert lines[1] == 'clip.mp4,Integration title,Integration description,"frame, test"'
